#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Deliverance Enterprises
#
# SPDX-License-Identifier: MIT
"""Plain ROS1 node that republishes the WDC's REAL telemetry -- read LOCALLY
from the tablet's own WebSocket API, no cloud server involved -- as real
ROS1 topics/tf, so InOrbit's Agent Core (installed on a machine with network
access to the robot's own LAN, not necessarily physically on the robot) can
auto-detect them exactly like it did for TurtleBot's own /map /scan tf.

Supersedes the earlier Siruiy-cloud-SSE version of this file (still in git
history). The project requirement is that the Agent SDK reads the robot's data
locally, on the robot itself: an integration that depends on an external server
is a connector, not an agent, and does not have to run on the robot at all. The
old version read `GET {robot_url}/events/service` from Siruiy's own cloud --
exactly the pattern ruled out, even though the data itself was real.

Why this local path exists at all: the manufacturer's own Android app
(`wdc_fabricante.apk`, decompiled in this same directory) hosts a plain
WebSocket SERVER on the tablet itself, port 9015, path "/robot" -- found by
reading `MainActivity.java` (`Websocketservice.newServiceWebSocket(...)
.init("/robot", "9015")`) and `WdcRobotApi.java` (the command handler), NOT
from the vendor PDF (`WDC_Robot_Interaction_Capabilities.pdf`), which claims a
different port (6060) never confirmed against the real app. Simple JSON
request/response, no auth: `{"cmd":"getPoses"}`, `{"cmd":"obtainingPower"}`,
`{"cmd":"scan"}`. Confirmed live 2026-08-27 against the real tablet
(192.168.3.102) from a dev machine, reachable via a Tailscale subnet
router (`raspberry-oficina`, advertising the office LAN 192.168.3.0/24) --
see project_wdc_local_api_found memory for the full trail.

This node is the WDC equivalent of turtlebot_robot_sdk/src/mission_data_node.py:
no InOrbit SDK involved, plain ROS1, one small script.

NOT the mission-tracking equivalent -- this only proves telemetry (pose,
laser, battery). The local API's `info` command has no mission/task history
either (same as the old cloud API), so there is no WDC equivalent of
mission_status/mission_tracking to write here.
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

# The tablet's own local IP on the office LAN -- NOT the isolated embedded-
# computer network (192.168.31.x). Confirmed live 2026-08-27. Overridable
# since a DHCP lease change would otherwise silently break this.
LOCAL_API_HOST = os.environ.get("WDC_LOCAL_API_HOST", "192.168.3.102")
LOCAL_API_PORT = int(os.environ.get("WDC_LOCAL_API_PORT", "9015"))
LOCAL_API_PATH = "/robot"
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

# Topic InOrbit's own CustomCommandsAgentlet publishes to when an
# ActionDefinition of type "PublishToTopic" fires from the cloud -- confirmed
# live 2026-08-28 by reading /root/.inorbit/dist/inorbit/agentlets/
# custom_commands.py directly on the tablet (the actual constant is
# ROS_CUSTOM_COMMAND_TOPIC = "inorbit/custom_command", singular -- InOrbit's
# own public docs say "/inorbit/custom_commands", plural, but the real
# shipped agent code is the ground truth here, not the doc summary).
CUSTOM_COMMAND_TOPIC = "/inorbit/custom_command"

# How close (metres) counts as "arrived" for _mission_tracking()'s proximity
# check. Not measured against this robot's own real docking/stopping
# tolerance -- a reasonable indoor-robot guess, easy to tune if arrivals are
# seen completing too early/late once watched live.
ARRIVAL_RADIUS_M = 0.3

# location.laser.laserOffset from a live SSE read, 2026-08-26 -- [x, y, z]
# translation of the lidar relative to base_link. No orientation given by
# the API; assumed identity (lidar facing forward, same as base_link) since
# nothing in the payload suggests otherwise. Unconfirmed against a CAD/spec
# sheet -- if InOrbit's rendered robot looks visibly rotated, revisit this.
LASER_OFFSET = (0.1768, 0.0, -0.01)

# Real ESPAITEC_1 map JPEG, kept alongside this script so the node finds it
# regardless of the container's cwd. See _publish_real_map()'s docstring.
REAL_MAP_JPG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "espaitec1_map.jpg")

# Real x/y/yaw for every named point, read directly off the tablet's own
# manufacturer app storage -- confirmed live 2026-08-28, `su -c sqlite3
# /data/data/com.sirui.wdc_robot/databases/DCStorage "SELECT value FROM
# DC_3928737_storage WHERE key='pointPosition'"` (delivery points A-E) and
# key='regular' (system points). NOT guessed, NOT recorded by physically
# driving the robot -- these are the robot's own saved coordinates, straight
# from the same storage its own "Delivery Mode" screen reads. Kept as a
# plain dict here rather than re-querying the tablet's sqlite db at runtime,
# since this bridge already can't touch the Android side beyond the local
# WebSocket API -- if these points are ever redefined in the app, this dict
# needs updating by hand (same maintenance burden as Keenon's own hardcoded
# `point_uuid`/x/y in `keenon_connector/cac/actions.yaml`).
NAMED_POINTS = {
    "A": (0.276, 0.612, -0.046),
    "B": (-0.712, 0.617, -1.260),
    "C": (3.623, -2.191, -1.024),
    "D": (4.266, -1.959, 1.969),
    "E": (4.646, -2.560, 2.103),
    "HOME": (-0.334, -0.250, -0.000),
    "RETURN_POINT": (-0.335, -0.250, -0.001),
    "RECYCLING_POINT": (-0.333, -0.262, 0.001),
}


class LocalApiClient:
    """Minimal, dependency-free WebSocket client for the tablet's own local
    `/robot` API (see module docstring). Hand-rolled with stdlib `socket` --
    no `websocket-client`/`websockets` package available in this ROS1
    container's Python, and the protocol is simple enough not to need one
    (RFC6455 client handshake + masked text frames, confirmed working
    2026-08-27 against the real tablet).

    Keeps one persistent connection across ticks and reconnects on any
    failure -- the tablet's own server has no session/keepalive quirks we've
    seen so far, but a flaky office WiFi hop is expected, so every request()
    call is defensive.
    """

    def __init__(self, host: str, port: int, path: str) -> None:
        self._host = host
        self._port = port
        self._path = path
        self._sock: Optional[socket.socket] = None
        # One request/response pair at a time. This client is shared by two
        # rospy threads -- the poll timer (_tick) and the command subscriber
        # callback (_on_custom_command) -- and this protocol has no request
        # ids to match replies against, so a second caller interleaving on
        # the same socket gets whichever frame arrives next.
        #
        # Real symptom seen while debugging 2026-08-31: an `info` reply came
        # back as the answer to a `navigation` request, i.e. every later
        # reply shifted one request behind. Harmless-looking in steady state
        # (each field still parses) but it silently corrupts exactly the
        # commands that move the robot, so it is worth the lock.
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
        """Sends {"cmd": cmd, **extra} and returns the response's "data"
        field, or None on any failure (connection reset, timeout, bad JSON,
        etc). Never raises -- callers just skip that tick's publish, same
        tolerance the old cloud version had for a dropped SSE read.
        `**extra` is for commands that need parameters beyond the bare cmd
        -- e.g. `navigation` needs name/x/y/yaw, per WdcRobotApi.java's
        `navigation(jSONObject)` (see CLAUDE.md's full decompiled command
        set)."""
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
        self._api = LocalApiClient(LOCAL_API_HOST, LOCAL_API_PORT, LOCAL_API_PATH)
        self._publish_static_laser_tf()
        self._publish_real_map()
        # Write path, added 2026-08-28 with explicit go-ahead
        # (overriding this file's own
        # earlier "read-only, no writes to the real robot" stance). STOP and
        # CHARGE need no coordinates; GOTO_<name> uses NAMED_POINTS' real
        # recorded x/y/yaw (see that dict's own comment for where they came
        # from -- the tablet app's own local storage, not guessed).
        rospy.Subscriber(CUSTOM_COMMAND_TOPIC, String, self._on_custom_command)
        # Mission tracking state -- see _mission_tracking() docstring.
        self._task_id: Optional[str] = None
        self._task_label = ""
        self._task_waypoint = ""
        self._task_start_ts = 0
        self._task_end_ts: Optional[int] = None
        self._task_was_moving = False
        # Added for distance-based progress (see _compute_progress()) and
        # the overlapping-task fix (see _start_task()). _last_pose is kept
        # up to date every tick by _publish_pose_tf(), independent of
        # whether a task is active -- cheap (two floats) and it means
        # _start_task() (called from the command handler, not the poll
        # loop) always has a recent position to snapshot without an extra
        # API round-trip.
        self._last_pose: Optional[Tuple[float, float]] = None
        self._task_start_pose: Optional[Tuple[float, float]] = None
        self._task_dest: Optional[Tuple[float, float]] = None
        rospy.Timer(rospy.Duration(POLL_PERIOD_SEC), self._tick)
        rospy.loginfo(
            "wdc_bridge_node started -- polling ws://%s:%d%s every %.1fs",
            LOCAL_API_HOST, LOCAL_API_PORT, LOCAL_API_PATH, POLL_PERIOD_SEC,
        )

    def _publish_real_map(self) -> None:
        """Publishes WDC's actual scanned floor plan, fetched LIVE from the
        robot itself via cmd:"map" (WdcRobotApi.getAMap() ->
        SelfChassisState.getMapData(), confirmed live 2026-08-28 by reading
        the decompiled app source in full) -- a base64 JPEG data-URI plus
        REAL resolution/width/height/offx/offy straight from the robot's own
        SLAM stack, no more guessing. Supersedes the earlier static
        `espaitec1_map.jpg` (Siruiy cloud cache, no calibration metadata,
        resolution copied by eye from Keenon/Allybot's own entries) -- kept
        only as `_publish_static_fallback_map()` for if this live request
        ever fails (e.g. robot has no map cached yet).

        offx/offy are treated as the OccupancyGrid origin (world position of
        the map's bottom-left cell) -- the standard map_server/nav2_map_server
        convention this field's naming matches; not independently confirmed
        against a WDC spec sheet, same caveat as this file's other
        unconfirmed-but-consistent inferences (see LASER_OFFSET above).

        The map still has to be aligned onto the shared Floorplan0 by hand in
        InOrbit Control's Locations editor either way (same pattern as every
        other office robot here) -- this just removes the guesswork from the
        resolution/origin that alignment starts from.

        **Briefly disabled, then re-enabled the same day (2026-08-28)**: at
        first looked wrong compared against Siruiy cloud's own live map view
        (`.../pages/deploy/map`) -- that view's shape (a large step narrowing
        the room for the whole bottom half) didn't match this JPEG's shape
        (a small triangular notch, stays near full width to the bottom).
        Reverted to the static jpg out of caution. Re-enabled after finding
        the REAL bug the static jpg had: its origin (-9.6, -9.6) was a
        guess borrowed from Keenon/Allybot's own convention, with no actual
        relationship to WDC's coordinate frame -- confirmed live by checking
        whether the robot's own current pose falls inside each map's bounds:
        it does NOT reliably land inside the static jpg's guessed bounds
        (robot rendered outside its own map in InOrbit's Navigation tab,
        even before considering Floorplan0 alignment at all), but DOES land
        cleanly inside cmd:"map"'s real bounds (checked live: pose
        (-1.171, 5.160) vs bounds x:[-10.00,9.20] y:[-10.00,9.20]) -- expected,
        since pose and this map both come from the same SelfChassisState
        instance on the robot, so they share a coordinate frame by
        construction, unlike the static jpg's borrowed guess. The earlier
        shape mismatch against Siruiy's cloud view is suspected (not
        confirmed) to be comparing against that view's LIVE scan overlay
        (which draws real-time sensor data extending past whatever was
        baked into the last saved map, not the saved map's own boundary) --
        an apples-to-oranges comparison, not proof cmd:"map" is wrong.
        _publish_static_fallback_map() kept below as a fallback only.
        """
        map_data = self._api.request("map")
        if isinstance(map_data, dict) and all(k in map_data for k in ("data", "width", "height", "resolution")):
            try:
                self._publish_live_map(map_data)
                return
            except Exception as exc:
                rospy.logerr("Live map fetch/decode failed (%s) -- falling back to static jpg", exc)
        else:
            rospy.logwarn("WDC local API 'map' command returned nothing usable -- falling back to static jpg")
        self._publish_static_fallback_map()

    def _publish_live_map(self, map_data: dict) -> None:
        data_uri = map_data["data"]
        b64 = data_uri.split(",", 1)[1] if "," in data_uri else data_uri
        raw = base64.b64decode(b64)
        im = Image.open(io.BytesIO(raw)).convert("L")
        w, h = im.size
        pixels = list(im.getdata())

        def to_cell(v: int) -> int:
            # Same tri-modal histogram shape confirmed live 2026-08-28
            # against this live JPEG (dominant ~205 grey background, 255
            # white interior, 0 black walls) as the old static jpg's ~160,
            # so the same thresholds carry over unchanged.
            if v >= 220:
                return 0        # free
            if v <= 40:
                return 100      # occupied (wall)
            return -1            # unknown

        # NOT flipped -- confirmed live 2026-08-28 this image is already in
        # OccupancyGrid's own row-0-is-bottom order (unlike the old static
        # jpg, which needed the flip below). Found by comparing where the
        # charging-dock "X" marker landed: with the flip applied, the robot's
        # own live pose rendered entirely outside/above the published map in
        # InOrbit's Navigation tab; the earlier bounds-only check (pose x/y
        # within [offx, offx+w*res]) didn't catch this because flipping row
        # order doesn't change those bounds, only which pixel row a given y
        # maps to -- a real gap in that check, not proof the flip was fine.
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
        """Fallback only, see _publish_real_map(). Same static jpg + guessed
        resolution this node used before the live "map" command was found."""
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
        rospy.loginfo("Published static fallback ESPAITEC_1 map (%dx%d px)", w, h)

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

    def _on_custom_command(self, msg: String) -> None:
        """Handles a command that arrived via InOrbit's ActionDefinition
        (type: PublishToTopic) -> CustomCommandsAgentlet -> CUSTOM_COMMAND_TOPIC
        chain (see that constant's own comment). `msg.data` is whatever
        literal string the ActionDefinition's own `arguments[].value` sends --
        matched here against fixed command words WE define (not something
        InOrbit prescribes), same as Keenon's own `filename` argument values
        are just strings that connector's own code recognizes.

        Deliberately a small, explicit if/elif chain, not a generic
        dispatch table -- every command this accepts moves or otherwise acts
        on a real physical robot, so an unrecognized string should do
        nothing rather than something unexpected via a coding mistake in a
        lookup table.
        """
        command = (msg.data or "").strip().upper()
        rospy.loginfo("Received custom command: %r", command)
        if command == "STOP":
            self._api.request("stopAction")
        elif command == "CHARGE":
            # No coordinates on hand here (the regular poll loop's "info"
            # isn't cached) -- one extra round-trip only on this rare event
            # to get the real dock position for progress tracking, see
            # _compute_progress(). Falls back to no destination (progress
            # stays 0 until Completed) if this particular call fails.
            charge_info = self._api.request("info")
            charge_pos = charge_info.get("chargingPosition") if isinstance(charge_info, dict) else None
            dest = (charge_pos["x"], charge_pos["y"]) if isinstance(charge_pos, dict) and "x" in charge_pos else None
            self._start_task("charge", "Go Charge", dest)
            self._api.request("charging")
        elif command.startswith("GOTO_"):
            point_name = command[len("GOTO_"):]
            point = NAMED_POINTS.get(point_name)
            if point is None:
                rospy.logwarn("Unknown named point %r -- ignoring", point_name)
                return
            x, y, yaw = point
            rospy.loginfo("Sending robot to point %r (x=%.3f y=%.3f yaw=%.3f)", point_name, x, y, yaw)
            self._start_task(point_name.lower(), f"Go to {point_name.title()}", (x, y))
            resp = self._api.request("navigation", name=point_name, x=x, y=y, yaw=yaw)
            self._check_nav_response(resp, point_name)
        else:
            rospy.logwarn("Unrecognized custom command %r -- ignoring", command)

    # NOTE -- auto-`stopAction`-before-navigating: TRIED AND REVERTED, 2026-08-31.
    #
    # Requested because the robot
    # needs its previous job released before it will accept a new
    # destination, and having to remember to press STOP first is a bad
    # interface. The idea is sound; this specific implementation was not.
    #
    # Sending `stopAction` and then `navigation` ~1.5s apart appears to
    # destabilise the manufacturer's own Android app. Evidence gathered
    # right after deploying it:
    #   - `wdc_watchdog.log` recorded the app dying TWICE within minutes
    #     (13:47, 13:49), immediately after commands. Its previous entries
    #     are hours apart.
    #   - The reply to the `navigation` request came back as the `info`
    #     JSON instead of `开始任务` -- i.e. the reply stream had shifted by
    #     one, the same desync the new client lock was meant to prevent,
    #     so back-to-back writes are upsetting something below our layer.
    #   - the app was seen closing and relaunching itself, an "unhealthy"
    #     popup, and InOrbit briefly showing battery 0% / Error (garbage
    #     published while the API was down -- the robot itself was fine at
    #     87%).
    #
    # Reverted rather than tuned, because this runs against a real robot in
    # daily use and crashing its control app is worse than the problem being
    # solved. If picked up again, do it reactively instead of proactively:
    # send navigation first, and only on a `BUSY！` reply send `stopAction`
    # and retry once, with a longer gap (the manual checks that worked used
    # ~3s). That way the extra command is sent rarely, not on every button
    # press.

    def _check_nav_response(self, resp, point_name: str) -> None:
        """Surfaces the robot's own answer to a `navigation` request instead
        of discarding it.

        Real incident 2026-08-31: two "Go to Point" actions in a row did
        nothing at all, with no error anywhere -- the robot was answering
        the literal string `"BUSY！"` (Chinese full-width exclamation mark)
        to every navigation request, and this code threw that reply away
        without looking at it, so both InOrbit and the logs showed a
        perfectly successful command that the robot had in fact refused.

        The refusal itself is legitimate robot behaviour, not a fault:
        `readycode` sits at 300 (it reads 0 when free) after the robot
        reaches a delivery point, and it rejects further navigation until
        the pending job is cleared -- consistent with a waiter robot
        waiting at a table for someone to confirm at its own screen.
        `stopAction` clears it reliably (confirmed live: 300 -> 0, stable
        afterwards), which is what the existing STOP action already sends.

        Deliberately only reports -- does NOT auto-send stopAction and
        retry. That would silently cancel whatever the robot was waiting on
        (potentially an undelivered order) as a side effect of pressing a
        different button, which is a product decision for the project owner to
        make explicitly, not something to sneak in here.
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
        """Begins tracking a new mission -- see _mission_tracking()'s own
        docstring for the full shape/mechanism.

        `dest` is the real target (x, y) -- the named point's own recorded
        coordinates for GOTO_*, the live charging-dock position for CHARGE
        -- used by _compute_progress() for a real distance-based percentage
        instead of the old binary 0.0/1.0. None (STOP doesn't call this at
        all, and CHARGE falls back to None if its extra lookup fails) just
        means progress stays 0.0 until the task ends, same as before.

        Overlapping-task fix, 2026-08-31 (documented as a known gap in
        CLAUDE.md until now): a task already in progress used to be
        silently overwritten, leaving its own mission_tracking entry frozen
        at "Executing" forever in InOrbit -- confirmed live the same day
        several actions were fired in quick succession while testing.
        Now the previous task, if still open, is explicitly closed out as
        Aborted (interrupted by this new command) before the new one starts
        -- matches the robot's own real behaviour (WdcRobotApi.navigation()
        has no queueing either; a new command simply replaces whatever it
        was doing), it just also reports that truthfully instead of leaving
        a stale record."""
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
        """Publishes one mission_tracking key-value for the CURRENTLY
        tracked task, forcing `state` rather than deriving it from a fresh
        "info" poll -- used only by _start_task()'s overlap fix above, where
        there's no fresh "info" on hand and the outcome (interrupted) is
        already known without one. Same JSON shape as _mission_tracking()'s
        own return value, kept in sync by hand since the two are built at
        different times for different reasons."""
        tracking = {
            "missionId": self._task_id,
            "inProgress": False,
            "state": state,
            "label": self._task_label,
            "startTs": self._task_start_ts,
            "data": {"waypoint": self._task_waypoint, "reason": reason} if reason else {"waypoint": self._task_waypoint},
            "status": "OK",
            # Same Keenon-derived shape as _mission_tracking()'s own return
            # (task carries its own inProgress, currentTaskId stays set) --
            # see that method for why.
            "tasks": [{"taskId": "0", "label": self._task_label, "inProgress": False}],
            "completedPercent": self._compute_progress(),
            "currentTaskId": "0",
            "endTs": self._task_end_ts,
        }
        msg = String()
        msg.data = f"mission_tracking={json.dumps(tracking)}"
        self._custom_data_pub.publish(msg)

    def _compute_progress(self) -> float:
        """Real progress (0.0-1.0) toward `self._task_dest`, by straight-line
        distance from where the task started to where the robot is now,
        against the total straight-line distance to the destination --
        confirmed reasonable given this robot's own indoor paths are short
        and mostly direct (no attempt to account for a curved/obstacle-
        routed path, unavailable from this local API either way, see
        CLAUDE.md's "Progreso de misión por distancia" limitation entry).

        Returns 0.0 whenever any piece is missing (no destination on hand,
        no pose seen yet, or the task hasn't moved from its start point) --
        the same conservative default this always reported before distance
        tracking existed, just no longer the ONLY value it can report."""
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
        # Four separate request/response round-trips over the same
        # persistent connection, same cadence the old SSE version polled at.
        # The local API has no single "give me everything" command, so each
        # piece is asked for explicitly. "info" added 2026-08-28 -- carries
        # a lot more than pose/scan/battery (error code, localization
        # confidence, active map, firmware version, charging state), all of
        # it real fields confirmed live against WdcRobotApi.getInfo() in the
        # decompiled source, not guessed.
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
        # Raw values are millimetres (same convention confirmed for the old
        # cloud API, still true here -- e.g. 1180 == 1.18m against a
        # plausible indoor obstacle distance); ROS LaserScan expects metres.
        msg.ranges = [v / 1000.0 for v in raw]
        self._scan_pub.publish(msg)

    def _publish_battery(self, power_data) -> None:
        # obtainingPower's real shape (confirmed live 2026-08-28, not what
        # was assumed when this was first written against the cloud API):
        # a dict -- {"charging":.., "dCConnected":.., "home":.., "percentage":100}
        # -- not a bare number. Pull "percentage" out of it.
        if not isinstance(power_data, dict) or "percentage" not in power_data:
            return
        power_quantity = power_data["percentage"]
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

    def _publish_info(self, info) -> None:
        """Publishes extra fields from the "info" command as InOrbit
        key-values, on top of pose/scan/battery -- these aren't things
        InOrbit auto-discovers from ROS (no standard message type for
        "localization confidence" or "error code"), so they go through the
        same custom_data channel already used for battery percent. Field
        names/meaning confirmed live against WdcRobotApi.getInfo() in the
        decompiled source (this directory's CLAUDE.md), not guessed:
        readycode, result, stop, chargestep, chargingCurrent, agvStop,
        quantity, robtId, version, mapName, floor, confidenceCoefficient,
        errorcode, agvlocaltime, chargingPosition.
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

    def _compute_mission_status(self, info: dict) -> str:
        """Maps our available fields to one of InOrbit's "Modes" values so
        the account-wide "Modes and Tags" widget (Settings > Organization >
        Modes, data source "mission_status") can classify this robot -- same
        mechanism every Edge SDK connector here already uses (confirmed live
        2026-08-28 by reading `allybot_connector/cac/data_sources.yaml`'s own
        `mission_status` DataSourceDefinition override, `key: mission_status`,
        values "Idle"/"Mission"/"Paused"/"Charging"/"Error"). The transport
        differs (Edge SDK publishes this key-value directly over MQTT; we go
        ROS topic -> CustomDataAgentlet -> MQTT) but a key-value looks the
        same to InOrbit's cloud once it arrives either way -- same channel
        already proven working today for every other field in this method.

        Only a heuristic, not a real robot-reported mode string (the local
        API has no such field) -- priority order: an active error code wins
        over everything else, then actually drawing charge current, then
        `agvStop` distinguishes stopped (Idle) from moving (Mission). No
        available field distinguishes "Manual" (teleop) or "Paused" from the
        states above, so this never reports those two -- acceptable, not
        every robot has to hit every mode.
        """
        if info.get("errorcode"):
            return "Error"
        if (info.get("chargingCurrent") or 0) > 0:
            return "Charging"
        if info.get("agvStop"):
            return "Idle"
        return "Mission"

    def _mission_tracking(self, info: dict) -> Optional[dict]:
        """Builds InOrbit's standard mission_tracking JSON (same shape/state
        machine as `turtlebot_robot_sdk/src/mission_data_node.py`'s own
        `_mission_tracking()` -- kept field-for-field comparable, see that
        file's docstring) so `MissionTracking`/`MissionDefinition` CAC can
        classify each Go-To-Point/Charge action the same way TurtleBot's own
        Nav2-driven missions are classified.

        We have no Nav2 action-status topic to observe here, so `agvStop`
        (from the "info" command, real-time, not guessed) stands in as the
        ground truth for "is it actually moving right now". `errorcode`
        becoming nonzero mid-task means Aborted.

        Arrival is a proximity check (stopped AND within ARRIVAL_RADIUS_M of
        `self._task_dest`) whenever a destination is known, not a bare
        moving-then-stopped transition -- **real bug found live 2026-08-31**
        (a "Go Charge" mission was found stuck at "Executing" for 65
        hours in InOrbit's own Missions widget): the old transition-only
        check never fired at all if the robot was ALREADY at/near the
        destination when the command was sent (it needs a genuine
        moving->stopped edge, and there never was one to detect), so that
        task simply never closed. Proximity also happens to be strictly
        better than the old transition check even when the robot DOES
        travel -- a transition-only check would wrongly call a mid-route
        pause (an obstacle, briefly) an arrival, where proximity correctly
        doesn't. Falls back to the old transition heuristic only when no
        destination is known at all (e.g. the CHARGE command's extra
        `chargingPosition` lookup itself failed) -- the one case proximity
        genuinely can't be checked.

        Returns None when no task has ever been started (never publishes a
        `mission_tracking` key-value at all until the first action fires) --
        once one exists, every field that should eventually disappear
        (`currentTaskId`, `endTs`) is set to `None` explicitly rather than
        omitted, since InOrbit merges each custom_data publish into the
        previous JSON value instead of replacing it -- confirmed the hard
        way by TurtleBot's own investigation, see that file's docstring.
        """
        if self._task_id is None:
            return None

        is_moving = not info.get("agvStop", True)
        has_error = bool(info.get("errorcode"))

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
            # No destination known at all (e.g. CHARGE's extra
            # chargingPosition lookup failed) -- proximity can't be
            # checked, fall back to the old moving->stopped transition as
            # the only signal left.
            #
            # Known accepted gap: a STOP command sent mid-route (destination
            # known, robot genuinely far from it) closes neither path above,
            # so that task stays "Executing" rather than some other
            # state -- there's no real "Cancelled" state available from
            # this local API to report anyway (can't tell a deliberate stop
            # from arriving, per this method's own long-standing limits).
            # Not permanently stuck, though: _start_task()'s own overlap
            # fix closes any still-open task as Aborted the moment the next
            # real command fires, so this can only linger until then, never
            # forever like the bug this whole fix addresses.
            self._task_end_ts = int(time.time() * 1000)
        self._task_was_moving = is_moving

        in_progress = self._task_end_ts is None
        if has_error:
            mission_state = "Aborted"
        elif in_progress:
            mission_state = "Executing"
        else:
            mission_state = "Completed"

        # Real distance-based progress (see _compute_progress()) -- except
        # once Completed, pinned to 1.0 rather than whatever the last
        # distance calculation gave (arrival doesn't always land exactly on
        # the destination coordinate).
        completed_percent = 1.0 if mission_state == "Completed" else self._compute_progress()

        return {
            "missionId": self._task_id,
            "inProgress": in_progress,
            "state": mission_state,
            "label": self._task_label,
            "startTs": self._task_start_ts,
            "data": {"waypoint": self._task_waypoint},
            "status": "error" if has_error else "OK",
            # `inProgress` on the task itself, and `currentTaskId` kept as
            # "0" even once finished -- both copied from Keenon's own
            # working payload, NOT from TurtleBot's (which sets
            # currentTaskId to None on completion, the pattern this file
            # originally followed).
            #
            # Real bug this fixes, found live 2026-08-31: every WDC mission
            # stayed "Executing" in InOrbit's Missions widget forever even
            # though the key-value we published said "Completed" -- verified
            # by two independent reads (the raw ROS topic, and
            # `GET /robots/223623373/attributes/mission_tracking`, both
            # showing state Completed / completedPercent 1.0). Comparing
            # `GET /missions?robotId=...` (the widget's real backing data)
            # against Keenon's working payload showed InOrbit had stored our
            # mission with `tasks:[{...,"inProgress":true}]` -- its internal
            # task never closed, so the mission never left Executing no
            # matter what the top-level `state` field said. Keenon's payload
            # keeps `currentTaskId` populated throughout; ours nulled it on
            # completion, leaving InOrbit with no task to close out.
            "tasks": [{"taskId": "0", "label": self._task_label, "inProgress": in_progress}],
            "completedPercent": completed_percent,
            "currentTaskId": "0",
            "endTs": self._task_end_ts if not in_progress else None,
        }


if __name__ == "__main__":
    WdcBridgeNode()
    rospy.spin()
