# SPDX-FileCopyrightText: 2026 Deliverance Enterprises
#
# SPDX-License-Identifier: MIT

"""Shared data models and helpers for the Allybot API integration."""

import math
from dataclasses import dataclass, field

# aliveStatus values from /robot/singleRobotInfo
ALIVE_STATUS_MAP: dict[int, str] = {
    0: "offline",
    1: "online",
    2: "mobile_connected",  # connected to mobile app WS, not fleet WS
}


def quaternion_to_yaw(qx: float, qy: float, qz: float, qw: float) -> float:
    """Extract yaw (rotation around z-axis) from a unit quaternion.

    Uses the standard formula: yaw = 2 * atan2(qz, qw), which is exact when
    roll and pitch are zero (flat 2-D navigation).
    """
    return 2.0 * math.atan2(qz, qw)


# Task status codes from devicestasktatus WS messages
TASK_STATUS_MAP: dict[int, str] = {
    3: "Starting",
    5: "Running",
    9: "Paused",
}

# The robot's devicestatus WS reports work_status in two languages depending on
# which side of the Allybot cloud produced the message: seen live,
# one ~1 Hz stream alternating "Charging" / "Cargando", "Operating" /
# "En funcionamiento" and "Returning" / "Volviendo". Everything downstream
# (mission_status, the InOrbit status widgets) compares against the English
# names, so a Spanish message made a docked robot flip to "Idle".
_WORK_STATUS_CANONICAL: dict[str, str] = {
    "charging": "Charging",
    "cargando": "Charging",
    "operating": "Operating",
    "en funcionamiento": "Operating",
    "returning": "Returning",
    "volviendo": "Returning",
    "idle": "Idle",
}


def normalize_work_status(raw: str | None) -> str | None:
    """Return the canonical English work_status; unknown values pass through."""
    if not raw:
        return raw
    return _WORK_STATUS_CANONICAL.get(raw.strip().casefold(), raw)


def _flag(value: object) -> bool | None:
    """A boolean flag of a REST response (bool, 0/1 or text), or None when it is missing or unreadable."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    text = str(value).strip().casefold()
    if text in ("true", "1", "yes"):
        return True
    if text in ("false", "0", "no", ""):
        return False
    return None


def chassis_emergency_stop(device_status: dict | None) -> bool | None:
    """Emergency stop from a REST ``device/status`` response, or None when it does not say.

    ``chassisStatus.emergencyStop`` is the physical button and ``emergencyStopManual`` a stop
    from the app; either one stops the robot. Same reading as deliverance-integrations-allybot.
    """
    if not isinstance(device_status, dict):
        return None
    chassis = device_status.get("chassisStatus")
    if not isinstance(chassis, dict):
        return None
    flags = [_flag(chassis.get("emergencyStop")), _flag(chassis.get("emergencyStopManual"))]
    if all(f is None for f in flags):
        return None
    return any(bool(f) for f in flags)


@dataclass
class AllybotRobotState:
    """Cached state for a single Allybot robot, updated by the App WS and REST polling."""

    # Live pose (from App WS device_position)
    x: float | None = None
    y: float | None = None
    yaw: float | None = None  # radians
    speed: float | None = None  # m/s

    # Active map metadata (from POST /fleetapi/device/usemap)
    active_map_id: str | None = None
    map_name: str | None = None
    map_image_url: str | None = None
    map_origin_x: float | None = None
    map_origin_y: float | None = None
    map_resolution: float | None = None  # metres per pixel

    # Robot metadata (from GET /robot/singleRobotInfo — REST auth)
    robot_name: str | None = None
    alive_status: int | None = None  # 0=offline, 1=online, 2=mobile_connected

    # Task progress (from App WS devicestasktatus)
    task_id: str | None = None
    task_name: str | None = None
    task_percentage: float | None = None  # 0-100
    task_status_code: int | None = None  # 3=Starting, 5=Running, 9=Paused
    task_start_ts: int | None = None  # epoch ms
    task_end_ts: int | None = None  # epoch ms, fixed the first time the run is seen finished
    run_seen_at: float | None = None  # time.monotonic() when the current run was first seen
    # Cleaning report (partial - built from the data the App WS exposes; the
    # full manufacturer report with electric/water consumption + coverage image
    # needs the robot's cleaning-report endpoint, which is not available here).
    cleaned_area: float | None = None  # m² cleaned (devicestasktatus.area)
    plan_area: float | None = None     # m² total plan (devicestasktatus.msg.workingScope)
    task_mode: str | None = None       # cleaning mode (devicestatus.data.clean.task_mode)
    # The robot's own time estimate for the run, in whole MINUTES (devicestasktatus.msg.totalTime). It is a live projection, not a plan: measured
    # over a real 5 min 3 s run it read 3 at 0 %, 10 at 11 %, fell to 3 at 35 %, then stayed between 4 and 5 from 50 % on and ended at 5.
    task_estimate_start_min: int | None = None  # first estimate of the run (3 in two separate runs: looks like a default that falls short)
    task_estimate_min: int | None = None        # latest estimate

    # Device status (from App WS devicestatus)
    battery: int | None = None  # 0-100
    fresh_water: float | None = None  # %
    sewage_water: float | None = None  # %
    work_status: str | None = None  # "Charging" / "Idle" / "Operating"
    have_task_running: bool | None = None
    # Emergency stop from the App WS: a fallback heuristic, NOT VERIFIED against a real robot. The
    # devicestatus documented for this connector carries no emergency field; this reads a
    # devicestatus `emergencyStop` key or a work_status that says emergency, if the robot ever sends
    # one; see `AllybotAppWebSocket._on_device_status`.
    emergency_stop: bool = False
    # Emergency stop from REST device/status chassisStatus (the primary signal), polled by the
    # connector. None when the last poll failed or did not say (then the WS heuristic is used).
    rest_emergency_stop: bool | None = None

    @property
    def is_emergency_stopped(self) -> bool:
        """REST chassisStatus when known, the App WS heuristic otherwise."""
        if self.rest_emergency_stop is not None:
            return self.rest_emergency_stop
        return self.emergency_stop

    # Connectivity health
    ws_connected: bool = False
    last_ws_message: float = field(default=0.0)
    last_update: float = field(default=0.0)
