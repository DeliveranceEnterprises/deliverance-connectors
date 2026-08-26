#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Deliverance Enterprises
#
# SPDX-License-Identifier: MIT
"""ROS2 (rclpy) port of deliverance_agent_node.py -- same design, same
platform-DB upsert logic, only the ROS API differs (rclpy vs rospy).

Why this file exists: deliverance_agent_node.py was validated once, against
WDC (ROS1). "Our own Agent SDK" is only a real SDK if it isn't secretly
WDC-shaped -- the single strongest way to prove that is to run the same idea
against a genuinely different robot, on a genuinely different ROS major
version. TurtleBot (turtlebot_robot_sdk/, ROS2 Humble, real Gazebo+Nav2
simulation) is that second robot, live in this same workspace already.

Everything else is intentionally identical to the ROS1 version -- same env
vars, same _upsert_device/_upsert_device_status shape (copied from
integrations/deliverance-integrations-siruiy/service/unified_sync_platform.py),
same conservative offline/idle-only status logic, same open questions
(DB-direct vs API, no map/scene name). See deliverance_agent_node.py's
docstring and deliverance_agent_sdk/CLAUDE.md for the full reasoning --
not repeated here to avoid the two files drifting out of sync in prose while
staying in sync in code.

Topics read here differ from WDC's, on purpose, to prove genuine
robot-agnosticism -- not `/battery_state` (WDC has no ROS-native battery
topic; wdc_bridge_node.py had to synthesize one) but TurtleBot's own REAL
`/scan` (Gazebo's LiDAR) and `map` -> `base_link` tf (Nav2/AMCL's own
localization, nothing synthesized). No battery topic exists for TurtleBot
either (Gazebo doesn't simulate one -- same gap turtlebot_connector's Edge
SDK backend has to fake), so battery_level is reported as 0 here rather than
inventing a fake value this node has no way to make honest.
"""

import os
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

import psycopg
import rclpy
from psycopg.types.json import Json
from rclpy.node import Node
from rclpy.qos import QoSDurabilityPolicy, QoSProfile, QoSReliabilityPolicy
from sensor_msgs.msg import LaserScan
from tf2_ros import TransformListener
from tf2_ros.buffer import Buffer

# ===========================================================================
# Config -- identical shape/defaults to the ROS1 version
# ===========================================================================

POSTGRES_SERVER = os.environ.get("POSTGRES_SERVER", "host.docker.internal")
POSTGRES_PORT = int(os.environ.get("POSTGRES_PORT", "5435"))
POSTGRES_DB_REAL = os.environ.get("POSTGRES_DB_REAL", "unified_api_real")
POSTGRES_USER = os.environ.get("POSTGRES_USER", "postgres")
POSTGRES_PASSWORD = os.environ.get("POSTGRES_PASSWORD", "postgres")

ORG_NAME = os.environ.get("DELIVERANCE_AGENT_ORG_NAME", "Deliverance")
ROBOT_NAME = os.environ.get("DELIVERANCE_AGENT_ROBOT_NAME", "turtlebot-agent-sdk-test")
SYNC_PERIOD_SEC = float(os.environ.get("DELIVERANCE_AGENT_SYNC_PERIOD_SEC", "5.0"))
STALE_AFTER_SEC = float(os.environ.get("DELIVERANCE_AGENT_STALE_AFTER_SEC", "15.0"))

_UUID_NS = uuid.UUID("6ee00003-dead-cafe-babe-c0ffeebeef00")


def _stable_uuid(*parts: str) -> str:
    return str(uuid.uuid5(_UUID_NS, "/".join(str(p) for p in parts)))


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ===========================================================================
# Platform DB -- byte-for-byte the same upsert logic as
# deliverance_agent_node.py (ROS1 version). Duplicated rather than imported
# because the two files are meant to run in separate ROS environments
# (Humble vs Noetic containers) that don't share a Python path -- a shared
# module would need its own packaging story, deliberately out of scope for
# this prototype (see CLAUDE.md "Open questions").
# ===========================================================================

def _get_conn() -> psycopg.Connection:
    return psycopg.connect(
        host=POSTGRES_SERVER, port=POSTGRES_PORT, dbname=POSTGRES_DB_REAL,
        user=POSTGRES_USER, password=POSTGRES_PASSWORD, autocommit=True,
    )


def _ensure_org(cur, org_name: str) -> str:
    cur.execute("SELECT uid::text FROM organizations WHERE name = %s LIMIT 1", (org_name,))
    row = cur.fetchone()
    if row:
        return row[0]
    raise RuntimeError(
        f"Organizacion '{org_name}' no encontrada. DELIVERANCE_AGENT_ORG_NAME debe "
        "coincidir con FIRST_ORGANIZATION del launcher."
    )


def _upsert_device(cur, device_uid: str, name: str, org_uid: str) -> None:
    cur.execute(
        """
        INSERT INTO devices (
            uid, name, description, model, category,
            serial_number, mac_address, image, owner_id, enabled
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (uid) DO UPDATE SET
            name        = EXCLUDED.name,
            description = EXCLUDED.description
        """,
        (
            device_uid, name,
            "Deliverance Agent SDK prototype -- generic ROS2 bridge, robot-agnostic",
            "Generic ROS2 robot", "robot",
            device_uid[:255], device_uid[:17],
            None, org_uid, False,
        ),
    )


def _upsert_device_status(cur, device_uid: str, device_name: str, status: dict) -> None:
    cur.execute("SELECT uid FROM device_status WHERE device_uid = %s LIMIT 1", (device_uid,))
    existing = cur.fetchone()
    if existing is None:
        cur.execute(
            """
            INSERT INTO device_status (
                uid, device_uid, device_name, status, battery_level,
                last_connection, scene, error_code, maintenance
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (
                device_uid, device_uid, device_name,
                status["status"], status["battery_level"], status["last_connection"],
                Json(status["scene"]), status["error_code"], Json(status["maintenance"]),
            ),
        )
    else:
        cur.execute(
            """
            UPDATE device_status SET
                device_name = %s, status = %s, battery_level = %s,
                last_connection = %s, scene = %s, error_code = %s, maintenance = %s
            WHERE device_uid = %s
            """,
            (
                device_name, status["status"], status["battery_level"], status["last_connection"],
                Json(status["scene"]), status["error_code"], Json(status["maintenance"]),
                device_uid,
            ),
        )


# ===========================================================================
# Agent node -- rclpy this time
# ===========================================================================

class DeliveranceAgentNode(Node):
    def __init__(self) -> None:
        super().__init__("deliverance_agent_node")

        self._tf_buffer = Buffer()
        self._tf_listener = TransformListener(self._tf_buffer, self)

        self._last_scan_ts: Optional[float] = None

        # TurtleBot's real /scan is published BEST_EFFORT by Gazebo's lidar
        # plugin -- the rclpy default subscription QoS is RELIABLE, which is
        # incompatible and silently receives nothing (no error, just zero
        # messages, exactly the kind of "quiet gap" this workspace has hit
        # before with QoS -- see turtlebot_robot_sdk/CLAUDE.md's map/QoS
        # bug). Match it explicitly rather than rediscover that the hard way.
        scan_qos = QoSProfile(depth=10)
        scan_qos.reliability = QoSReliabilityPolicy.BEST_EFFORT
        scan_qos.durability = QoSDurabilityPolicy.VOLATILE
        self.create_subscription(LaserScan, "/scan", self._on_scan, scan_qos)

        self._device_uid = _stable_uuid("deliverance_agent_sdk", ROBOT_NAME)
        self.get_logger().info(
            f"deliverance_agent_node (ROS2) started -- robot={ROBOT_NAME} "
            f"device_uid={self._device_uid} -> {POSTGRES_SERVER}:{POSTGRES_PORT}/{POSTGRES_DB_REAL} "
            f"(period={SYNC_PERIOD_SEC}s)"
        )

        self.create_timer(SYNC_PERIOD_SEC, self._tick)

    def _on_scan(self, _msg: LaserScan) -> None:
        self._last_scan_ts = time.time()

    def _get_pose(self):
        """map -> base_link, via TurtleBot's own real AMCL/Nav2 localization
        -- nothing synthesized, same tf convention as the ROS1 version."""
        try:
            t = self._tf_buffer.lookup_transform("map", "base_link", rclpy.time.Time())
            return t.transform.translation.x, t.transform.translation.y
        except Exception:
            return None, None

    def _compute_status(self) -> str:
        now = time.time()
        if self._last_scan_ts is None or (now - self._last_scan_ts) > STALE_AFTER_SEC:
            return "offline"
        return "idle"

    def _tick(self) -> None:
        status = self._compute_status()
        x, y = self._get_pose()

        status_map = {
            "status": status,
            # No ROS-native battery topic for TurtleBot either (Gazebo
            # doesn't simulate one) -- reported honestly as 0 rather than
            # inventing a plausible-looking fake value, same discipline as
            # the rest of this prototype.
            "battery_level": 0,
            "last_connection": _utcnow_naive(),
            "scene": {
                "map": None, "name": None, "level": "1",
                "coordinates_x": round(x, 4) if x is not None else None,
                "coordinates_y": round(y, 4) if y is not None else None,
                "map_image": None,
            },
            "error_code": 0,
            "maintenance": {"machine_status": 100 if status != "offline" else 0},
        }

        try:
            with _get_conn() as conn:
                cur = conn.cursor()
                org_uid = _ensure_org(cur, ORG_NAME)
                _upsert_device(cur, self._device_uid, ROBOT_NAME, org_uid)
                _upsert_device_status(cur, self._device_uid, ROBOT_NAME, status_map)
            self.get_logger().info(f"synced status={status} pose=({x},{y})")
        except Exception as exc:
            self.get_logger().warn(f"DB sync failed: {exc}")


def main() -> None:
    rclpy.init()
    node = DeliveranceAgentNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
