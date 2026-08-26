#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Deliverance Enterprises
#
# SPDX-License-Identifier: MIT
"""Plain ROS1 node that republishes the WDC's REAL telemetry -- read from
Siruiy's public cloud API, no LAN access to the embedded computer needed --
as real ROS1 topics/tf, so InOrbit's Agent Core (installed on THIS machine,
not on the isolated robot) can auto-detect them exactly like it did for
TurtleBot's own /map /scan tf.

Why this is possible at all: `GET {robot_url}/events/service` (SSE, no auth
needed -- confirmed live 2026-08-26) echoes back data shaped EXACTLY like ROS
messages, field names included -- `frame_id: "laser_link"`, `angle_min`,
`angle_increment`, `range_min/max` -- not a vendor-invented shape. This is
almost certainly the vendor's own tablet app relaying real ROS1 topics from
the embedded computer over its own (non-ROS, confirmed by Eduardo 2026-07-30)
WebSocket, which Siruiy's cloud then wraps into this SSE feed. We can't reach
the isolated LAN directly (confirmed 2026-08-26: ROS1 ports 11311/9090 closed
on the robot's public proxy) -- but we don't have to. We just need the DATA,
which this public endpoint already delivers straight to us.

This node is the WDC equivalent of turtlebot_robot_sdk/src/mission_data_node.py:
no InOrbit SDK involved, plain ROS1, one small script. Reuses field names
confirmed live against the real robot 2026-08-26 -- see
integrations/deliverance-integrations-siruiy/CLAUDE.md and
integrations/deliverance-integrations-siruiy/service/client.py for the
already-proven-working request shapes this borrows from.

NOT the mission-tracking equivalent -- this only proves telemetry (pose,
laser, battery). Siruiy's API has no mission/task history at all (see the
Edge SDK repo's CLAUDE.md), so there is no WDC equivalent of mission_status/
mission_tracking to write here.
"""

import json
import os
import time
from typing import Optional

import requests
import rospy
import tf2_ros
from geometry_msgs.msg import Pose, TransformStamped
from nav_msgs.msg import MapMetaData, OccupancyGrid
from PIL import Image
from sensor_msgs.msg import BatteryState, LaserScan
from std_msgs.msg import String
from tf.transformations import quaternion_from_euler

ROBOT_URL = "http://63tq2dqn2cp8itkuw3or.siruiy.com:9999"
SSE_URL = f"{ROBOT_URL}/events/service"
POLL_PERIOD_SEC = 2.0
# NOT "/inorbit/custom_data" (no suffix) -- that plain topic is what
# mission_data_node.py (ROS2, TurtleBot) uses and it works there, but this
# agent's ROS1 build subscribes literally to the "0" (default field id)
# suffixed topic -- confirmed live 2026-08-26 via `rostopic list -v`: the
# agent's subscriber sits on /inorbit/custom_data/0, publishing to the plain
# topic reached a topic with zero subscribers. Whether this is a ROS1-vs-ROS2
# agent build difference or something else is unconfirmed -- what matters is
# this is the topic this exact agent is actually listening on.
CUSTOM_DATA_TOPIC = "/inorbit/custom_data/0"

# location.laser.laserOffset from a live SSE read, 2026-08-26 -- [x, y, z]
# translation of the lidar relative to base_link. No orientation given by
# the API; assumed identity (lidar facing forward, same as base_link) since
# nothing in the payload suggests otherwise. Unconfirmed against a CAD/spec
# sheet -- if InOrbit's rendered robot looks visibly rotated, revisit this.
LASER_OFFSET = (0.1768, 0.0, -0.01)

# Real ESPAITEC_1 map JPEG, kept alongside this script so the node finds it
# regardless of the container's cwd. See _publish_real_map()'s docstring.
REAL_MAP_JPG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "espaitec1_map.jpg")


def _fetch_sse_payload() -> Optional[dict]:
    """One-shot read of the first `data:` line from the SSE stream, same
    pattern as SiruiyClient._read_state_info() but synchronous (no asyncio
    needed for a single rospy node) and returning the FULL payload -- we need
    `location` (laser+pose), not just `stateInfo` (battery+status)."""
    try:
        with requests.get(
            SSE_URL, headers={"Accept": "text/event-stream"}, stream=True, timeout=4
        ) as resp:
            for line in resp.iter_lines(decode_unicode=True):
                if line and line.startswith("data:"):
                    return json.loads(line[len("data:"):].strip())
    except Exception as exc:
        rospy.logwarn("SSE read failed: %s", exc)
    return None


class WdcBridgeNode:
    def __init__(self) -> None:
        rospy.init_node("wdc_bridge_node")
        self._scan_pub = rospy.Publisher("/scan", LaserScan, queue_size=1)
        self._custom_data_pub = rospy.Publisher(CUSTOM_DATA_TOPIC, String, queue_size=10)
        # Standard sensor_msgs/BatteryState, on the conventional /battery_state
        # topic name -- added 2026-08-26 for deliverance_agent_sdk (see that
        # sibling directory). InOrbit's Agent Core has no use for this (it
        # reads CUSTOM_DATA_TOPIC above instead); this exists so a consumer
        # that knows nothing about InOrbit -- our own agent -- can still get
        # real battery data via a plain, standard ROS message.
        self._battery_pub = rospy.Publisher("/battery_state", BatteryState, queue_size=1)
        # latch=True: RosLocalizationAgentlet._ros_on_laser_all() bails at its
        # very first line, silently, whenever RosMapAgentlet.map_published is
        # False -- confirmed live 2026-08-26 by reading the installed agent's
        # own source, same gate as the (different) TurtleBot map/QoS bug. We
        # have no real occupancy grid yet (see CLAUDE.md "Open questions"), so
        # this publishes a placeholder just to flip that flag -- content is
        # never validated by _ros_on_map(), only that *a* message arrives on
        # `map`. latch=True (ROS1's answer to ROS2's transient-local QoS)
        # means the agent gets it even though it subscribes well after this
        # single publish.
        self._map_pub = rospy.Publisher("/map", OccupancyGrid, queue_size=1, latch=True)
        self._tf_broadcaster = tf2_ros.TransformBroadcaster()
        self._static_tf_broadcaster = tf2_ros.StaticTransformBroadcaster()
        self._publish_static_laser_tf()
        self._publish_real_map()
        rospy.Timer(rospy.Duration(POLL_PERIOD_SEC), self._tick)
        rospy.loginfo("wdc_bridge_node started -- polling %s every %.1fs", SSE_URL, POLL_PERIOD_SEC)

    def _publish_real_map(self) -> None:
        """Publishes WDC's actual scanned floor plan, not a blank placeholder.

        `espaitec1_map.jpg` came from Siruiy's own cloud cache (`POST
        /cache/getKey`, key `centretalk:map`), found live 2026-08-26 by
        reading the robot's own web UI's network traffic (not guessed) --
        see CLAUDE.md "Open questions". It's the exact image the vendor's own
        "地图" (map) page renders for ESPAITEC_1.

        No real resolution/origin ships with it -- deliberately not treated
        as a blocker (see reference_inorbit_floorplan_alignment_pattern
        memory): per Carlos, every office robot's own map gets manually
        aligned onto the shared "Floorplan0" via InOrbit Control's Locations
        editor regardless of how it was generated -- Keenon's own map isn't
        pixel-perfect-calibrated either, a human drags/rotates/scales it into
        place. So a plausible guessed resolution here is enough; the human
        alignment step is what actually registers it, not this metadata.
        """
        try:
            im = Image.open(REAL_MAP_JPG).convert("L")
        except Exception as exc:
            rospy.logerr("Could not load %s (%s) -- falling back to a blank placeholder", REAL_MAP_JPG, exc)
            self._publish_blank_placeholder_map()
            return

        w, h = im.size
        pixels = list(im.getdata())

        def to_cell(v: int) -> int:
            # Confirmed via histogram, 2026-08-26: 160 dominates (grey
            # background outside the scanned room -> unknown), 255 is the
            # white interior (-> free), 0 is the black wall outline
            # (-> occupied). JPEG compression smears a few pixels around
            # those three values, hence ranges rather than exact matches.
            if v >= 220:
                return 0        # free
            if v <= 40:
                return 100      # occupied (wall)
            return -1            # unknown (background, or ambiguous edge pixel)

        # OccupancyGrid row 0 is the BOTTOM row in world coordinates, but
        # image row 0 is the TOP -- flip vertically or the map renders
        # upside down (row order is the only fix needed; Carlos aligns the
        # rest by hand regardless).
        data = []
        for row in range(h - 1, -1, -1):
            data.extend(to_cell(px) for px in pixels[row * w:(row + 1) * w])

        grid = OccupancyGrid()
        grid.header.stamp = rospy.Time.now()
        grid.header.frame_id = "map"
        grid.info = MapMetaData()
        # Was a guessed 0.03 -- corrected 2026-08-26 once Carlos pulled the
        # real values from Keenon's and Allybot's own floorplan entries in
        # InOrbit (same physical space, maps "provided by the robots" the
        # same way this one is): BOTH read exactly 0.05000000074505806 --
        # the classic float32-widened-to-float64 representation of 0.05,
        # confirming it's ROS's own map_server/nav2_map_server default
        # resolution, not something either of those robots picked by hand.
        # Matching that convention here too, since nothing suggests WDC's
        # own SLAM stack would differ.
        grid.info.resolution = 0.05
        grid.info.width = w
        grid.info.height = h
        grid.info.origin = Pose()
        grid.info.origin.position.x = -(w * grid.info.resolution) / 2.0
        grid.info.origin.position.y = -(h * grid.info.resolution) / 2.0
        grid.info.origin.orientation.w = 1.0
        grid.data = data
        self._map_pub.publish(grid)
        rospy.loginfo("Published real ESPAITEC_1 map (%dx%d px)", w, h)

    def _publish_blank_placeholder_map(self) -> None:
        """Fallback only -- see _publish_real_map(). Purely to keep
        RosMapAgentlet.map_published True (unblocks the laser gate, see
        CLAUDE.md) if the real image is ever missing/unreadable."""
        grid = OccupancyGrid()
        grid.header.stamp = rospy.Time.now()
        grid.header.frame_id = "map"
        grid.info = MapMetaData()
        grid.info.resolution = 0.05
        grid.info.width = 20
        grid.info.height = 20
        grid.info.origin = Pose()
        grid.info.origin.orientation.w = 1.0
        grid.data = [-1] * (grid.info.width * grid.info.height)
        self._map_pub.publish(grid)

    def _publish_static_laser_tf(self) -> None:
        t = TransformStamped()
        t.header.stamp = rospy.Time.now()
        t.header.frame_id = "base_link"
        t.child_frame_id = "laser_link"
        t.transform.translation.x, t.transform.translation.y, t.transform.translation.z = LASER_OFFSET
        t.transform.rotation.w = 1.0
        self._static_tf_broadcaster.sendTransform(t)

    def _tick(self, _event) -> None:
        payload = _fetch_sse_payload()
        if payload is None:
            return
        loc = payload.get("location") or {}
        state = payload.get("stateInfo") or {}
        self._publish_pose_tf(loc.get("position"))
        self._publish_scan(loc.get("scans"))
        self._publish_battery(state.get("powerquantity"))

    def _publish_pose_tf(self, position) -> None:
        if not position or len(position) < 3:
            return
        x, y, theta = position[0], position[1], position[2]
        t = TransformStamped()
        t.header.stamp = rospy.Time.now()
        t.header.frame_id = "map"
        t.child_frame_id = "base_link"
        t.transform.translation.x = x
        t.transform.translation.y = y
        t.transform.translation.z = 0.0
        qx, qy, qz, qw = quaternion_from_euler(0, 0, theta)
        t.transform.rotation.x, t.transform.rotation.y = qx, qy
        t.transform.rotation.z, t.transform.rotation.w = qz, qw
        self._tf_broadcaster.sendTransform(t)

    def _publish_scan(self, scans) -> None:
        if not scans:
            return
        s = scans[0]
        raw = s.get("scan")
        if not raw:
            return
        msg = LaserScan()
        msg.header.stamp = rospy.Time.now()
        msg.header.frame_id = s.get("frame_id", "laser_link")
        msg.angle_min = s["angle_start"]
        msg.angle_max = s["angle_max"]
        msg.angle_increment = s["increment"]
        msg.range_min = s["range_min"]
        msg.range_max = s["range_max"]
        # Raw values are millimetres (confirmed live 2026-08-26 -- e.g. 1190 ==
        # 1.19m against a plausible indoor obstacle distance); ROS LaserScan
        # expects metres.
        msg.ranges = [v / 1000.0 for v in raw]
        self._scan_pub.publish(msg)

    def _publish_battery(self, power_quantity) -> None:
        if power_quantity is None:
            return
        # Same two-key pattern as turtlebot_robot_sdk/src/mission_data_node.py:
        # "battery percent" (0-1, space in the key) feeds InOrbit's account-
        # level Vitals gauge; Siruiy already reports 0-100 directly.
        value = round(power_quantity / 100.0, 4)
        msg = String()
        msg.data = f"battery percent={value}"
        self._custom_data_pub.publish(msg)

        # Plain sensor_msgs/BatteryState, for consumers that know nothing
        # about InOrbit's custom-data convention -- see deliverance_agent_sdk.
        bs = BatteryState()
        bs.header.stamp = rospy.Time.now()
        bs.percentage = float(value)
        bs.power_supply_status = BatteryState.POWER_SUPPLY_STATUS_UNKNOWN
        self._battery_pub.publish(bs)


if __name__ == "__main__":
    WdcBridgeNode()
    rospy.spin()
