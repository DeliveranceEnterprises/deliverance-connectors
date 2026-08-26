#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Deliverance Enterprises
#
# SPDX-License-Identifier: MIT
"""Prototype of Deliverance's OWN Agent SDK -- Eduardo's second objective
(2026-08-26, see workspace memory project_robot_sdk_task): "por un lado
utilizar el Agent SDK de InOrbit... y por otro, diseñar nuestro propio Agent
SDK que sea especifico para actualizar la informacion en el formato de
nuestra plataforma."

This is deliberately the InOrbit-Agent-Core-shaped hole in the pipeline we
already built and validated today, filled with our own code instead:

    ANTES:  robot -> wdc_bridge_node.py -> topics ROS -> [Agent Core InOrbit] -> InOrbit Cloud
    AHORA:  robot -> wdc_bridge_node.py -> topics ROS -> [ESTE nodo]         -> Deliverance DB

`wdc_bridge_node.py` is untouched and still the one reading the real robot.
This node knows NOTHING about Siruiy, WDC, or InOrbit -- it only subscribes
to plain, standard ROS1 topics/tf (`/scan`, `/battery_state`, the `map` ->
`base_link` tf) and writes straight into the Deliverance platform DB, using
the exact same `devices`/`device_status` upsert shape every existing
connector already uses (copied from
integrations/deliverance-integrations-siruiy/service/unified_sync_platform.py,
the freshest reference in this workspace as of today).

That "knows nothing about the specific robot" property is the whole point --
in principle this same script would work unmodified against ANY ROS1 robot
publishing those three standard things, not just WDC. WDC is only today's
test bench, not what this is built for.

Deliberate choices for THIS prototype phase (see workspace memory
reference_inorbit_floorplan_alignment_pattern and the conversation that led
here -- these are not oversights):
- Writes DIRECTLY to the platform DB (psycopg), the same simple pattern
  every existing connector uses -- NOT the richer device_provider_mappings /
  device_status_events adapter design that exists in backend_introduction's
  unified_api/app/integrations/inorbit/. That richer pattern was designed and
  tested there but never reached the real platform schema (confirmed live
  2026-08-26: `deliverance-db` has no device_provider_mappings or
  device_status_events table at all) -- porting it is a separate, bigger
  conversation, parked deliberately, not something this prototype should
  half-reinvent.
- A direct DB connection (real credentials in this process) is the right
  call ONLY because Deliverance is the one running this right now, on our
  own machine, same as every existing connector. The day this is actually
  handed to the hardware-manufacturer partner to embed on THEIR computers,
  this must NOT keep working this way -- direct DB credentials on hardware
  we don't control is a real security problem (a compromised or buggy
  partner device would have write access to the whole platform DB, not just
  its own robot). That's a real architectural decision for later, flagged
  here so it isn't quietly forgotten, not solved by this file.
"""

import os
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

import psycopg
import rospy
import tf2_ros
from psycopg.types.json import Json
from sensor_msgs.msg import BatteryState, LaserScan

# ===========================================================================
# Config -- env vars, same names/defaults pattern as every existing connector
# ===========================================================================

POSTGRES_SERVER = os.environ.get("POSTGRES_SERVER", "host.docker.internal")
POSTGRES_PORT = int(os.environ.get("POSTGRES_PORT", "5435"))
POSTGRES_DB_REAL = os.environ.get("POSTGRES_DB_REAL", "unified_api_real")
POSTGRES_USER = os.environ.get("POSTGRES_USER", "postgres")
POSTGRES_PASSWORD = os.environ.get("POSTGRES_PASSWORD", "postgres")

ORG_NAME = os.environ.get("DELIVERANCE_AGENT_ORG_NAME", "Deliverance")
ROBOT_NAME = os.environ.get("DELIVERANCE_AGENT_ROBOT_NAME", "wdc-agent-sdk-test")
SYNC_PERIOD_SEC = float(os.environ.get("DELIVERANCE_AGENT_SYNC_PERIOD_SEC", "5.0"))
# No heartbeat within this window -> reported "offline". Generic, not tied to
# any robot-specific health field (we deliberately don't have one -- see
# _compute_status below).
STALE_AFTER_SEC = float(os.environ.get("DELIVERANCE_AGENT_STALE_AFTER_SEC", "15.0"))

_UUID_NS = uuid.UUID("6ee00003-dead-cafe-babe-c0ffeebeef00")


def _stable_uuid(*parts: str) -> str:
    return str(uuid.uuid5(_UUID_NS, "/".join(str(p) for p in parts)))


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ===========================================================================
# Platform DB -- upsert shape copied from
# deliverance-integrations-siruiy/service/unified_sync_platform.py, trimmed
# to what a generic ROS source can actually know (no map_name, no vendor
# error codes -- those don't exist as standard ROS concepts).
# ===========================================================================

def _get_conn() -> psycopg.Connection:
    return psycopg.connect(
        host=POSTGRES_SERVER, port=POSTGRES_PORT, dbname=POSTGRES_DB_REAL,
        user=POSTGRES_USER, password=POSTGRES_PASSWORD, autocommit=True,
    )


def _ensure_org(cur, org_name: str) -> str:
    """Lookup-only, same rule every connector in this workspace follows --
    never create an organization from a sync process."""
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
            "Deliverance Agent SDK prototype -- generic ROS1 bridge, robot-agnostic",
            "Generic ROS1 robot", "robot",
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
# Agent node
# ===========================================================================

class DeliveranceAgentNode:
    def __init__(self) -> None:
        rospy.init_node("deliverance_agent_node")

        self._tf_buffer = tf2_ros.Buffer()
        tf2_ros.TransformListener(self._tf_buffer)

        self._last_scan_ts: Optional[float] = None
        self._last_battery_pct: Optional[float] = None

        rospy.Subscriber("/scan", LaserScan, self._on_scan)
        rospy.Subscriber("/battery_state", BatteryState, self._on_battery)

        self._device_uid = _stable_uuid("deliverance_agent_sdk", ROBOT_NAME)
        rospy.loginfo(
            "deliverance_agent_node started -- robot=%s device_uid=%s -> %s:%d/%s (period=%.1fs)",
            ROBOT_NAME, self._device_uid, POSTGRES_SERVER, POSTGRES_PORT, POSTGRES_DB_REAL,
            SYNC_PERIOD_SEC,
        )

        rospy.Timer(rospy.Duration(SYNC_PERIOD_SEC), self._tick)

    def _on_scan(self, _msg: LaserScan) -> None:
        self._last_scan_ts = time.time()

    def _on_battery(self, msg: BatteryState) -> None:
        # percentage is 0-1 per the sensor_msgs/BatteryState convention.
        self._last_battery_pct = msg.percentage

    def _get_pose(self):
        """map -> base_link, if a recent transform exists. Standard tf2 --
        no knowledge of who publishes it."""
        try:
            t = self._tf_buffer.lookup_transform("map", "base_link", rospy.Time(0))
            return t.transform.translation.x, t.transform.translation.y
        except Exception:
            return None, None

    def _compute_status(self) -> str:
        """Deliberately conservative -- see CLAUDE.md. With only standard ROS
        signals (tf freshness, battery) available, generically, across ANY
        robot, we can honestly tell offline vs online -- not "running" vs
        "idle" (that needs a robot-specific concept, e.g. WDC's own `mode`
        register, that a generic node can't assume exists). Same discipline
        this workspace already applies elsewhere: don't guess a status
        bucket from data that isn't actually confirmed to mean that."""
        now = time.time()
        if self._last_scan_ts is None or (now - self._last_scan_ts) > STALE_AFTER_SEC:
            return "offline"
        return "idle"

    def _tick(self, _event) -> None:
        status = self._compute_status()
        x, y = self._get_pose()
        battery_level = (
            max(0, min(100, round(self._last_battery_pct * 100)))
            if self._last_battery_pct is not None else 0
        )

        status_map = {
            "status": status,
            "battery_level": battery_level,
            "last_connection": _utcnow_naive(),
            "scene": {
                "map": None,
                # No standard ROS concept of a named "scene"/floor -- a real
                # per-robot value would need to come from something
                # robot-specific layered on top, out of scope for this
                # generic prototype.
                "name": None,
                "level": "1",
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
            rospy.loginfo_throttle(
                30, "synced status=%s battery=%d%% pose=(%s,%s)",
                status, battery_level, x, y,
            )
        except Exception as exc:
            rospy.logwarn("DB sync failed: %s", exc)


if __name__ == "__main__":
    DeliveranceAgentNode()
    rospy.spin()
