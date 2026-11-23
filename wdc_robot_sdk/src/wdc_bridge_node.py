#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Deliverance Enterprises
#
# SPDX-License-Identifier: MIT
"""Plain ROS1 node that republishes the WDC's telemetry as real ROS1
topics/tf, so InOrbit's Agent Core (installed on a machine with network
access to the robot's LAN, not necessarily physically on the robot) can
auto-detect them.

The data is read locally from the WebSocket API that the robot's own tablet
app serves on the tablet itself (port 9015, path "/robot"). No cloud server
is involved: an integration that depends on an external server is a
connector, not an agent. The API is a simple JSON request/response with no
authentication, for example `{"cmd":"getPoses"}`, `{"cmd":"obtainingPower"}`
and `{"cmd":"scan"}`.

Besides telemetry (pose, laser, battery, map) it publishes the mission
tracking and mode key values, and it implements the write path for the robot
actions (go to a named point, stop, charge). No InOrbit SDK is involved.
"""

import base64
import io
import json
import math
import os
import socket
import struct
import threading
import time
from typing import Optional, Tuple

import rospy
import tf2_ros
from geometry_msgs.msg import Pose, TransformStamped
from nav_msgs.msg import MapMetaData, OccupancyGrid
from PIL import Image
from sensor_msgs.msg import BatteryState, LaserScan
from std_msgs.msg import String
from tf.transformations import quaternion_from_euler

from wdc_points import GOTO_PREFIX, PointsFileError, load_points, resolve_goto

# The tablet's own IP on the local network -- NOT the isolated network of the
# robot's embedded computer. Required: there is no default, set
# WDC_LOCAL_API_HOST to the tablet's address.
LOCAL_API_HOST = os.environ.get("WDC_LOCAL_API_HOST", "")
LOCAL_API_PORT = int(os.environ.get("WDC_LOCAL_API_PORT", "9015"))
LOCAL_API_PATH = "/robot"
POLL_PERIOD_SEC = 2.0
# The ROS1 Agent Core subscribes to the "/0" (default field id) suffixed
# topic, not to plain "/inorbit/custom_data" (checked with `rostopic list -v`).
CUSTOM_DATA_TOPIC = "/inorbit/custom_data/0"

# Topic the Agent Core publishes to when a PublishToTopic action fires. The
# agent source uses the singular "custom_command", although some InOrbit docs
# say "custom_commands".
CUSTOM_COMMAND_TOPIC = "/inorbit/custom_command"

# Distance (metres) that counts as "arrived" for mission tracking. An
# estimate, not the robot's own stopping tolerance.
ARRIVAL_RADIUS_M = 0.3

# location.laser.laserOffset as reported by the robot: [x, y, z] of the lidar
# relative to base_link. The API gives no orientation, so identity is assumed.
LASER_OFFSET = (0.1768, 0.0, -0.01)

# Optional static map JPEG next to this script (not shipped). When it is
# missing the node publishes a blank placeholder map.
REAL_MAP_JPG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static_map.jpg")

# Optional map_server-style PGM + metadata pair, tried before the static JPEG
# when cmd:"map" fails. Some robots never return a map, so it has to be
# provided per deployment.
LOCAL_PGM_MAP_PATH = os.environ.get("WDC_LOCAL_PGM_MAP_PATH", "")
LOCAL_PGM_YAML_PATH = os.environ.get("WDC_LOCAL_PGM_YAML_PATH", "")

# YAML file with the robot's named points (see config/points.example.yaml).
# The ~points_file ROS parameter takes precedence. Without a file every
# GOTO_<NAME> command is refused.
POINTS_FILE = os.environ.get("WDC_POINTS_FILE", "")


class LocalApiClient:
    """Minimal stdlib WebSocket client for the tablet's `/robot` API.

    No WebSocket package is available in the ROS1 image, and the protocol is
    small (RFC 6455 handshake plus masked text frames). One persistent
    connection is kept and reopened after any failure.
    """

    def __init__(self, host: str, port: int, path: str) -> None:
        self._host = host
        self._port = port
        self._path = path
        self._sock: Optional[socket.socket] = None
        # One request/response pair at a time: the poll timer and the command
        # callback share the socket, and replies carry no request id.
        self._lock = threading.RLock()

    def _connect(self) -> None:
        sock = socket.create_connection((self._host, self._port), timeout=4)
        key = base64.b64encode(os.urandom(16)).decode()
        request = (
            f"GET {self._path} HTTP/1.1\r\n"
            f"Host: {self._host}:{self._port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        sock.sendall(request.encode())
        response = sock.recv(4096)
        if b"101" not in response.split(b"\r\n", 1)[0]:
            sock.close()
            raise ConnectionError(f"WDC local API did not upgrade: {response[:200]!r}")
        self._sock = sock

    def _send_text(self, message: str) -> None:
        payload = message.encode()
        mask = os.urandom(4)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        length = len(payload)
        if length <= 125:
            header = struct.pack("!BB", 0x81, 0x80 | length)
        else:
            header = struct.pack("!BBH", 0x81, 0x80 | 126, length)
        self._sock.sendall(header + mask + masked)

    def _recv_frame(self, timeout: float = 4.0) -> Optional[bytes]:
        self._sock.settimeout(timeout)
        buf = b""
        while True:
            chunk = self._sock.recv(65536)
            if not chunk:
                return None
            buf += chunk
            if len(buf) < 2:
                continue
            second_byte = buf[1]
            masked = second_byte & 0x80
            length = second_byte & 0x7F
            idx = 2
            if length == 126:
                if len(buf) < 4:
                    continue
                length = struct.unpack("!H", buf[2:4])[0]
                idx = 4
            elif length == 127:
                if len(buf) < 10:
                    continue
                length = struct.unpack("!Q", buf[2:10])[0]
                idx = 10
            needed = idx + (4 if masked else 0) + length
            if len(buf) < needed:
                continue
            if masked:
                mask = buf[idx:idx + 4]
                idx += 4
                payload = bytes(b ^ mask[i % 4] for i, b in enumerate(buf[idx:idx + length]))
            else:
                payload = buf[idx:idx + length]
            return payload

    def request(self, cmd: str, **extra) -> Optional[dict]:
        """Sends {"cmd": cmd, **extra} and returns the reply's "data" field,
        or None on any failure. Never raises."""
        with self._lock:
            try:
                if self._sock is None:
                    self._connect()
                payload = {"cmd": cmd}
                payload.update(extra)
                self._send_text(json.dumps(payload))
                raw = self._recv_frame()
                if raw is None:
                    raise ConnectionError("empty read")
                return json.loads(raw.decode()).get("data")
            except Exception as exc:
                rospy.logwarn("WDC local API request(%s) failed: %s", cmd, exc)
            try:
                if self._sock is not None:
                    self._sock.close()
            except Exception:
                pass
            self._sock = None
            return None


class WdcBridgeNode:
    def __init__(self) -> None:
        rospy.init_node("wdc_bridge_node")
        if not LOCAL_API_HOST:
            raise SystemExit("WDC_LOCAL_API_HOST is not set: set it to the tablet's IP address")
        self._scan_pub = rospy.Publisher("/scan", LaserScan, queue_size=1)
        self._custom_data_pub = rospy.Publisher(CUSTOM_DATA_TOPIC, String, queue_size=10)
        # For consumers other than InOrbit, which reads CUSTOM_DATA_TOPIC.
        self._battery_pub = rospy.Publisher("/battery_state", BatteryState, queue_size=1)
        # Latched: the Agent Core ignores laser scans until it has received a
        # map, and it may subscribe after the map was published.
        self._map_pub = rospy.Publisher("/map", OccupancyGrid, queue_size=1, latch=True)
        self._tf_broadcaster = tf2_ros.TransformBroadcaster()
        self._static_tf_broadcaster = tf2_ros.StaticTransformBroadcaster()
        self._points = self._load_named_points()
        self._api = LocalApiClient(LOCAL_API_HOST, LOCAL_API_PORT, LOCAL_API_PATH)
        self._publish_static_laser_tf()
        self._publish_real_map()
        rospy.Subscriber(CUSTOM_COMMAND_TOPIC, String, self._on_custom_command)
        # Mission tracking state -- see _mission_tracking() docstring.
        self._task_id: Optional[str] = None
        self._task_label = ""
        self._task_waypoint = ""
        self._task_start_ts = 0
        self._task_end_ts: Optional[int] = None
        self._task_was_moving = False
        # Updated every tick, so a new task can snapshot its start position
        # without an extra request.
        self._last_pose: Optional[Tuple[float, float]] = None
        self._task_start_pose: Optional[Tuple[float, float]] = None
        self._task_dest: Optional[Tuple[float, float]] = None
        rospy.Timer(rospy.Duration(POLL_PERIOD_SEC), self._tick)
        rospy.loginfo(
            "wdc_bridge_node started -- polling ws://%s:%d%s every %.1fs",
            LOCAL_API_HOST, LOCAL_API_PORT, LOCAL_API_PATH, POLL_PERIOD_SEC,
        )

    @staticmethod
    def _load_named_points() -> dict:
        path = rospy.get_param("~points_file", POINTS_FILE)
        if not path:
            rospy.logwarn("No points file configured (WDC_POINTS_FILE): GOTO commands will be refused")
            return {}
        try:
            points = load_points(path)
        except PointsFileError as exc:
            raise SystemExit(f"Invalid WDC points file: {exc}")
        rospy.loginfo("Loaded %d named points from %s: %s", len(points), path, ", ".join(sorted(points)))
        return points

    def _publish_real_map(self) -> None:
        """Publishes the robot's own map (cmd:"map": a base64 JPEG plus
        resolution, size and offx/offy), falling back to the local PGM pair,
        the static JPEG and finally a blank placeholder.

        offx/offy are taken as the OccupancyGrid origin (bottom-left cell),
        the map_server convention. The live map shares the pose's coordinate
        frame, which the static JPEG does not.
        """
        map_data = self._api.request("map")
        if isinstance(map_data, dict) and all(k in map_data for k in ("data", "width", "height", "resolution")):
            try:
                self._publish_live_map(map_data)
                return
            except Exception as exc:
                rospy.logerr("Live map fetch/decode failed (%s) -- falling back to a local map, if any", exc)
        else:
            rospy.logwarn("WDC local API 'map' command returned nothing usable -- falling back to a local map, if any")
        if LOCAL_PGM_MAP_PATH and LOCAL_PGM_YAML_PATH:
            try:
                self._publish_real_pgm_map()
                return
            except Exception as exc:
                rospy.logerr("Local PGM map fetch/decode failed (%s) -- falling back to static jpg", exc)
        self._publish_static_fallback_map()

    @staticmethod
    def _parse_pgm_yaml(path: str) -> dict:
        """Parses the map metadata: one `key: value` pair per line."""
        values: dict = {}
        with open(path, "r") as f:
            for line in f:
                line = line.strip()
                if not line or ":" not in line:
                    continue
                key, _, value = line.partition(":")
                values[key.strip()] = value.strip()
        return values

    @staticmethod
    def _parse_pgm(path: str) -> Tuple[int, int, int, bytes]:
        """Minimal P5 (binary greymap) PGM reader -- stdlib only, no
        PIL/numpy needed for this simple, uncompressed format. Returns
        (width, height, maxval, raw pixel bytes, row-major, no padding)."""
        with open(path, "rb") as f:
            data = f.read()
        if data[:2] != b"P5":
            raise ValueError(f"{path} is not a binary PGM (P5) file")

        def skip_ws_and_comments(i: int) -> int:
            while True:
                while i < len(data) and data[i:i + 1].isspace():
                    i += 1
                if i < len(data) and data[i:i + 1] == b"#":
                    while i < len(data) and data[i:i + 1] != b"\n":
                        i += 1
                    continue
                return i

        def read_int(i: int) -> Tuple[int, int]:
            i = skip_ws_and_comments(i)
            start = i
            while i < len(data) and not data[i:i + 1].isspace():
                i += 1
            return int(data[start:i]), i

        idx = 2
        width, idx = read_int(idx)
        height, idx = read_int(idx)
        maxval, idx = read_int(idx)
        idx += 1  # single whitespace byte separating the header from pixel data
        pixels = data[idx:idx + width * height]
        return width, height, maxval, pixels

    def _publish_real_pgm_map(self) -> None:
        """Publishes the local PGM + metadata pair with the standard
        map_server conversion (occupied_thresh / free_thresh / negate).

        PGM row 0 is the image top, OccupancyGrid row 0 is the map bottom,
        so rows are flipped.
        """
        width, height, maxval, pixels = self._parse_pgm(LOCAL_PGM_MAP_PATH)
        meta = self._parse_pgm_yaml(LOCAL_PGM_YAML_PATH)
        resolution = float(meta["resolution"])
        origin_x = float(meta["origin_x"])
        origin_y = float(meta["origin_y"])
        occupied_thresh = float(meta.get("occupied_thresh", 0.65))
        free_thresh = float(meta.get("free_thresh", 0.196))
        negate = meta.get("negate", "0") != "0"

        def to_cell(v: int) -> int:
            occ = (v / 255.0) if negate else ((255 - v) / 255.0)
            if occ > occupied_thresh:
                return 100
            if occ < free_thresh:
                return 0
            return -1

        data = []
        for row in range(height - 1, -1, -1):
            data.extend(to_cell(px) for px in pixels[row * width:(row + 1) * width])

        grid = OccupancyGrid()
        grid.header.stamp = rospy.Time.now()
        grid.header.frame_id = "map"
        grid.info = MapMetaData()
        grid.info.resolution = resolution
        grid.info.width = width
        grid.info.height = height
        grid.info.origin = Pose()
        grid.info.origin.position.x = origin_x
        grid.info.origin.position.y = origin_y
        grid.info.origin.orientation.w = 1.0
        grid.data = data
        self._map_pub.publish(grid)
        rospy.loginfo(
            "Published local real PGM map (%dx%d px, resolution=%.5f, origin=(%.3f, %.3f), maxval=%d)",
            width, height, resolution, origin_x, origin_y, maxval,
        )

    def _publish_live_map(self, map_data: dict) -> None:
        data_uri = map_data["data"]
        b64 = data_uri.split(",", 1)[1] if "," in data_uri else data_uri
        raw = base64.b64decode(b64)
        im = Image.open(io.BytesIO(raw)).convert("L")
        w, h = im.size
        pixels = list(im.getdata())

        def to_cell(v: int) -> int:
            # The JPEG has a grey background, white free space and black
            # walls.
            if v >= 220:
                return 0        # free
            if v <= 40:
                return 100      # occupied (wall)
            return -1            # unknown

        # Not flipped: the live image is already bottom-row first (checked
        # against the charging dock position on the robot).
        data = []
        for row in range(h):
            data.extend(to_cell(px) for px in pixels[row * w:(row + 1) * w])

        resolution = float(map_data["resolution"])
        grid = OccupancyGrid()
        grid.header.stamp = rospy.Time.now()
        grid.header.frame_id = "map"
        grid.info = MapMetaData()
        grid.info.resolution = resolution
        grid.info.width = w
        grid.info.height = h
        grid.info.origin = Pose()
        grid.info.origin.position.x = float(map_data.get("offx", 0.0))
        grid.info.origin.position.y = float(map_data.get("offy", 0.0))
        grid.info.origin.orientation.w = 1.0
        grid.data = data
        self._map_pub.publish(grid)
        rospy.loginfo(
            "Published LIVE map from robot (%dx%d px, resolution=%.5f, origin=(%.3f, %.3f))",
            w, h, resolution, grid.info.origin.position.x, grid.info.origin.position.y,
        )

    def _publish_static_fallback_map(self) -> None:
        """Fallback: static JPEG with an assumed resolution and a centred
        origin."""
        try:
            im = Image.open(REAL_MAP_JPG).convert("L")
        except Exception as exc:
            rospy.logerr("Could not load %s (%s) -- falling back to a blank placeholder", REAL_MAP_JPG, exc)
            self._publish_blank_placeholder_map()
            return

        w, h = im.size
        pixels = list(im.getdata())

        def to_cell(v: int) -> int:
            if v >= 220:
                return 0
            if v <= 40:
                return 100
            return -1

        data = []
        for row in range(h - 1, -1, -1):
            data.extend(to_cell(px) for px in pixels[row * w:(row + 1) * w])

        grid = OccupancyGrid()
        grid.header.stamp = rospy.Time.now()
        grid.header.frame_id = "map"
        grid.info = MapMetaData()
        grid.info.resolution = 0.05
        grid.info.width = w
        grid.info.height = h
        grid.info.origin = Pose()
        grid.info.origin.position.x = -(w * grid.info.resolution) / 2.0
        grid.info.origin.position.y = -(h * grid.info.resolution) / 2.0
        grid.info.origin.orientation.w = 1.0
        grid.data = data
        self._map_pub.publish(grid)
        rospy.loginfo("Published static fallback map (%dx%d px)", w, h)

    def _publish_blank_placeholder_map(self) -> None:
        """Last fallback, so the Agent Core still accepts laser scans."""
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

    def _on_custom_command(self, msg: String) -> None:
        """Handles the string sent by a PublishToTopic action. Every command
        moves the robot, so anything unrecognised is ignored."""
        command = (msg.data or "").strip().upper()
        rospy.loginfo("Received custom command: %r", command)
        if command == "STOP":
            self._api.request("stopAction")
        elif command == "CHARGE":
            # One extra request for the dock position, used for progress.
            charge_info = self._api.request("info")
            charge_pos = charge_info.get("chargingPosition") if isinstance(charge_info, dict) else None
            dest = (charge_pos["x"], charge_pos["y"]) if isinstance(charge_pos, dict) and "x" in charge_pos else None
            self._start_task("charge", "Go Charge", dest)
            self._api.request("charging")
        elif command.startswith(GOTO_PREFIX):
            point_name, point = resolve_goto(command, self._points)
            if point is None:
                rospy.logwarn("Unknown named point in %r -- ignoring", command)
                return
            x, y, yaw = point
            rospy.loginfo("Sending robot to point %r (x=%.3f y=%.3f yaw=%.3f)", point_name, x, y, yaw)
            self._start_task(point_name.lower(), f"Go to {point_name.title()}", (x, y))
            resp = self._api.request("navigation", name=point_name, x=x, y=y, yaw=yaw)
            self._check_nav_response(resp, point_name)
        else:
            rospy.logwarn("Unrecognized custom command %r -- ignoring", command)

    # Sending stopAction automatically before each navigation was tried and
    # reverted: back-to-back writes made the vendor tablet app restart and
    # desynchronised its replies. If revisited, do it only after a BUSY reply,
    # with a gap of about 3 s.

    def _check_nav_response(self, resp, point_name: str) -> None:
        """Reports the robot's answer to a `navigation` request.

        After reaching a point the robot keeps the job pending (readycode
        300) and answers "BUSY" followed by a full-width exclamation mark to
        any new destination until stopAction clears it. This only reports
        the refusal: retrying with an automatic stop could cancel a delivery
        that is still waiting at the robot.
        """
        if isinstance(resp, str) and "BUSY" in resp.upper():
            rospy.logwarn(
                "Robot REFUSED navigation to %r -- replied %r. It is busy with a "
                "pending job (readycode 300); send STOP to clear it, then retry.",
                point_name, resp,
            )
        elif resp is not None:
            rospy.loginfo("Robot accepted navigation to %r (replied %r)", point_name, resp)

    def _start_task(self, waypoint_id: str, label: str, dest: Optional[Tuple[float, float]] = None) -> None:
        """Begins tracking a new mission. `dest` is the target (x, y) used for
        progress, or None when unknown.

        A task that is still open is closed as Aborted first: the robot has
        no queue, so a new command replaces the current one."""
        if self._task_id is not None and self._task_end_ts is None:
            self._task_end_ts = int(time.time() * 1000)
            self._publish_tracking_snapshot("Aborted", "interrupted by a new command")

        now_ms = int(time.time() * 1000)
        self._task_id = f"wdc-nav-{now_ms}"
        self._task_label = label
        self._task_waypoint = waypoint_id
        self._task_start_ts = now_ms
        self._task_end_ts = None
        self._task_was_moving = False
        self._task_start_pose = self._last_pose
        self._task_dest = dest

    def _publish_tracking_snapshot(self, state: str, reason: str = "") -> None:
        """Publishes mission_tracking for the current task with a forced
        `state`. Same shape as _mission_tracking()."""
        tracking = {
            "missionId": self._task_id,
            "inProgress": False,
            "state": state,
            "label": self._task_label,
            "startTs": self._task_start_ts,
            "data": {"waypoint": self._task_waypoint, "reason": reason} if reason else {"waypoint": self._task_waypoint},
            "status": "OK",
            "tasks": [{"taskId": "0", "label": self._task_label, "inProgress": False}],
            "completedPercent": self._compute_progress(),
            "currentTaskId": "0",
            "endTs": self._task_end_ts,
        }
        msg = String()
        msg.data = f"mission_tracking={json.dumps(tracking)}"
        self._custom_data_pub.publish(msg)

    def _compute_progress(self) -> float:
        """Progress (0.0-1.0) toward the destination by straight-line
        distance. 0.0 when the destination or a pose is missing."""
        if self._task_dest is None or self._task_start_pose is None or self._last_pose is None:
            return 0.0
        start_x, start_y = self._task_start_pose
        dest_x, dest_y = self._task_dest
        cur_x, cur_y = self._last_pose
        total = math.hypot(dest_x - start_x, dest_y - start_y)
        if total <= 0.0:
            return 0.0
        remaining = math.hypot(dest_x - cur_x, dest_y - cur_y)
        progress = 1.0 - (remaining / total)
        return max(0.0, min(1.0, progress))

    def _publish_static_laser_tf(self) -> None:
        t = TransformStamped()
        t.header.stamp = rospy.Time.now()
        t.header.frame_id = "base_link"
        t.child_frame_id = "laser_link"
        t.transform.translation.x, t.transform.translation.y, t.transform.translation.z = LASER_OFFSET
        t.transform.rotation.w = 1.0
        self._static_tf_broadcaster.sendTransform(t)

    def _tick(self, _event) -> None:
        # The local API has no combined command, so each piece is requested
        # separately over the same connection.
        self._publish_pose_tf(self._api.request("getPoses"))
        self._publish_scan(self._api.request("scan"))
        self._publish_battery(self._api.request("obtainingPower"))
        self._publish_info(self._api.request("info"))

    def _publish_pose_tf(self, pose) -> None:
        if not pose or "x" not in pose or "y" not in pose:
            return
        self._last_pose = (pose["x"], pose["y"])
        t = TransformStamped()
        t.header.stamp = rospy.Time.now()
        t.header.frame_id = "map"
        t.child_frame_id = "base_link"
        t.transform.translation.x = pose["x"]
        t.transform.translation.y = pose["y"]
        t.transform.translation.z = 0.0
        qx, qy, qz, qw = quaternion_from_euler(0, 0, pose.get("yaw", 0.0))
        t.transform.rotation.x, t.transform.rotation.y = qx, qy
        t.transform.rotation.z, t.transform.rotation.w = qz, qw
        self._tf_broadcaster.sendTransform(t)

    def _publish_scan(self, scan) -> None:
        raw = scan.get("data") if scan else None
        if not raw:
            return
        msg = LaserScan()
        msg.header.stamp = rospy.Time.now()
        msg.header.frame_id = "laser_link"
        msg.angle_min = scan["angle_min"]
        msg.angle_max = scan["angle_max"]
        msg.angle_increment = scan["angle_increment"]
        msg.range_min = scan["range_min"]
        msg.range_max = scan["range_max"]
        # The robot reports millimetres; LaserScan uses metres.
        msg.ranges = [v / 1000.0 for v in raw]
        self._scan_pub.publish(msg)

    def _publish_battery(self, power_data) -> None:
        # Reply shape: {"charging", "dCConnected", "home", "percentage"}.
        if not isinstance(power_data, dict) or "percentage" not in power_data:
            return
        power_quantity = power_data["percentage"]
        # "battery percent" (0-1) feeds the account-level Vitals gauge.
        value = round(power_quantity / 100.0, 4)
        msg = String()
        msg.data = f"battery percent={value}"
        self._custom_data_pub.publish(msg)

        bs = BatteryState()
        bs.header.stamp = rospy.Time.now()
        bs.percentage = float(value)
        bs.power_supply_status = BatteryState.POWER_SUPPLY_STATUS_UNKNOWN
        self._battery_pub.publish(bs)

    def _publish_info(self, info) -> None:
        """Publishes fields of the "info" reply as InOrbit key values.

        The reply has readycode, result, stop, chargestep, chargingCurrent,
        agvStop, quantity, robtId, version, mapName, floor,
        confidenceCoefficient, errorcode, agvlocaltime and chargingPosition.
        """
        if not isinstance(info, dict):
            return

        def publish_kv(key: str, value) -> None:
            if value is None:
                return
            msg = String()
            msg.data = f"{key}={value}"
            self._custom_data_pub.publish(msg)

        publish_kv("error_code", info.get("errorcode"))
        publish_kv("localization_confidence", info.get("confidenceCoefficient"))
        publish_kv("active_map", info.get("mapName"))
        publish_kv("firmware_version", info.get("version"))
        publish_kv("charge_step", info.get("chargestep"))
        publish_kv("charging_current", info.get("chargingCurrent"))
        publish_kv("agv_stopped", info.get("agvStop"))
        publish_kv("floor", info.get("floor"))
        publish_kv("mission_status", self._compute_mission_status(info))
        tracking = self._mission_tracking(info)
        if tracking is not None:
            publish_kv("mission_tracking", json.dumps(tracking))

    @staticmethod
    def _info_looks_corrupted(info: dict) -> bool:
        """True when an "info" reply looks misrouted.

        The tablet's server can deliver a reply meant for another client.
        A real reply carries robtId, version or mapName; all three blank
        with an errorcode other than 0 (free) or 300 (busy) is treated as
        misrouted, so it never turns into a false "Error".
        """
        return (
            not info.get("robtId")
            and not info.get("version")
            and not info.get("mapName")
            and info.get("errorcode") not in (0, 300)
        )

    def _compute_mission_status(self, info: dict) -> str:
        """Maps the info fields to an InOrbit mode for the "mission_status"
        key, as the Edge SDK connectors do.

        Heuristic, in priority order: error code, charging current, then
        agvStop (Idle) versus moving (Mission). "Manual" and "Paused" cannot
        be told apart. The error code is ignored on a misrouted reply.
        """
        if self._info_looks_corrupted(info):
            if (info.get("chargingCurrent") or 0) > 0:
                return "Charging"
            if info.get("agvStop"):
                return "Idle"
            return "Mission"
        if info.get("errorcode"):
            return "Error"
        if (info.get("chargingCurrent") or 0) > 0:
            return "Charging"
        if info.get("agvStop"):
            return "Idle"
        return "Mission"

    def _mission_tracking(self, info: dict) -> Optional[dict]:
        """Builds InOrbit's mission_tracking JSON for the current task, or
        None before any task has started.

        `agvStop` tells whether the robot is moving, and a nonzero errorcode
        mid-task means Aborted. With a known destination, arrival means
        stopped within ARRIVAL_RADIUS_M (this also closes a task whose robot
        was already at the destination). Without one, a moving-to-stopped
        transition closes the task.

        Fields that must disappear are sent as null, because InOrbit merges
        each publish into the previous value. A task started on the tablet
        itself is detected from movement and tracked as "Manual task", with
        no destination.
        """
        is_moving = not info.get("agvStop", True)
        task_open = self._task_id is not None and self._task_end_ts is None
        if is_moving and not task_open:
            self._start_task("manual", "Manual task")

        if self._task_id is None:
            return None

        # A misrouted reply's errorcode must not abort a real mission.
        has_error = bool(info.get("errorcode")) and not self._info_looks_corrupted(info)

        arrived = False
        if not is_moving and self._task_dest is not None and self._last_pose is not None:
            dx = self._task_dest[0] - self._last_pose[0]
            dy = self._task_dest[1] - self._last_pose[1]
            arrived = math.hypot(dx, dy) <= ARRIVAL_RADIUS_M

        if has_error and self._task_end_ts is None:
            self._task_end_ts = int(time.time() * 1000)
        elif arrived and self._task_end_ts is None:
            self._task_end_ts = int(time.time() * 1000)
        elif (
            self._task_dest is None
            and self._task_was_moving
            and not is_moving
            and self._task_end_ts is None
        ):
            # No destination: fall back to the moving-to-stopped transition.
            self._task_end_ts = int(time.time() * 1000)
        self._task_was_moving = is_moving

        in_progress = self._task_end_ts is None
        if has_error:
            mission_state = "Aborted"
        elif in_progress:
            mission_state = "Executing"
        else:
            mission_state = "Completed"

        # Pinned to 1.0 once Completed: arrival is within a radius.
        completed_percent = 1.0 if mission_state == "Completed" else self._compute_progress()

        return {
            "missionId": self._task_id,
            "inProgress": in_progress,
            "state": mission_state,
            "label": self._task_label,
            "startTs": self._task_start_ts,
            "data": {"waypoint": self._task_waypoint},
            "status": "error" if has_error else "OK",
            # The task carries its own inProgress and currentTaskId stays
            # "0" after completion, as in the Keenon payload. With
            # currentTaskId nulled, InOrbit never closed the task and the
            # mission stayed "Executing".
            "tasks": [{"taskId": "0", "label": self._task_label, "inProgress": in_progress}],
            "completedPercent": completed_percent,
            "currentTaskId": "0",
            "endTs": self._task_end_ts if not in_progress else None,
        }


if __name__ == "__main__":
    WdcBridgeNode()
    rospy.spin()
