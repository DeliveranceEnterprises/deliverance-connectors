# SPDX-FileCopyrightText: 2026 Deliverance Enterprises
#
# SPDX-License-Identifier: MIT

"""Shared data models and helpers for the Keenon API integration."""

import math
import struct
from dataclasses import dataclass, field

# Standard Keenon map resolution (metres per pixel), confirmed empirically.
KEENON_MAP_RESOLUTION = 0.05


def png_dimensions(image: bytes) -> tuple[int, int]:
    """Return (width, height) in pixels from a PNG file header."""
    if len(image) < 24 or image[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("Not a valid PNG image")
    width = struct.unpack(">I", image[16:20])[0]
    height = struct.unpack(">I", image[20:24])[0]
    return width, height


def keenon_map_origin(width_px: int, height_px: int) -> tuple[float, float]:
    """Return (origin_x, origin_y) in metres for a Keenon map image.

    Keenon maps are centred on the robot navigation origin (0, 0), so the
    bottom-left corner of a W×H image at 0.05 m/px is at (−W/2·res, −H/2·res).
    """
    half_w = width_px * KEENON_MAP_RESOLUTION / 2
    half_h = height_px * KEENON_MAP_RESOLUTION / 2
    return -half_w, -half_h

ROBOT_STATE_MAP: dict[int, str] = {
    1: "on_task",
    2: "idle",
    3: "operating",
    4: "scheduling",
    5: "charging",
    6: "powering_on",
}

ONLINE_TYPE_MAP: dict[int, str] = {
    2: "wifi",
    3: "3G",
    4: "4G",
    5: "unknown",
}

TASK_STATUS_MAP: dict[int, str] = {
    0: "failed",
    1: "queued",
    2: "calling",
    3: "in_progress",
    4: "completed",
    5: "cancelled",
    6: "target_reached",
    7: "waiting",
}

CLEAN_MAIN_STATE_MAP: dict[int, str] = {
    1: "idle",
    2: "operating",
    3: "working",
    4: "charging",
    -1: "offline",
}

CLEAN_SUB_STATE_MAP: dict[int, str] = {
    11: "idle",
    21: "in_operation",
    30: "charging_default",
    31: "charging_matching",
    32: "charging",
    33: "under_pile",
    34: "line_charging",
    40: "working_default",
    41: "navigating",
    42: "cleaning",
    43: "self_cleaning",
    44: "returning",
    45: "cleaning_pause",
    46: "return_suspended",
    47: "hand_push_work",
    -1: "offline",
}

TANK_STATE_MAP: dict[int, str] = {
    -1: "no_hw",
    0: "empty",
    1: "medium",
    2: "full",
}

WATER_TANK_STATE_MAP: dict[int, str] = {
    -1: "no_hw",
    0: "empty",
    1: "low",
    2: "medium",
    3: "full",
}

# Task statuses that indicate the task is no longer active
TERMINAL_TASK_STATUSES = {0, 4, 5}

# Task statuses that mean the robot genuinely arrived (as opposed to failing,
# being cancelled, or merely being accepted) -- used to trigger the position
# snap below. Deliberately does NOT include 0 (failed) or 5 (cancelled).
ARRIVED_TASK_STATUSES = {4, 6}  # completed, target_reached

# Known-good real-world coordinates for `call_to_point` destinations, in the
# SAME frame/units the robot's own /custom/robot/location endpoint reports
# (metres, robot-local frame -- NOT the map-image pixel coordinates from
# /map/position, a different scale entirely). Keenon's own live position feed
# has been found unreliable for anything that didn't complete a real,
# API-tracked call_to_point task -- confirmed live 2026-09-09: `location`
# reported a stale/stuck coordinate while the robot was, per direct visual
# confirmation, actually somewhere else. Since we KNOW where a `call_to_point`
# target really is once the task genuinely reaches it (taskStatus 4/6, see
# ARRIVED_TASK_STATUSES), snap the published pose to that known point instead
# of trusting the live feed for that moment -- see
# DataPoller._update_task_status()'s use of this dict.
#
# Each entry MUST come from watching a real arrival (coordinate changing live,
# confirmed visually against the robot, not read off /map/position's
# different pixel-scale coordinate system) -- never guessed. Keyed by the
# same point_uuid the `call_to_point` command itself uses
# (keenon_connector/cac/actions.yaml's Send to Mesa N / Demo Delivery
# entries). Points not listed here simply don't get snapped -- the live feed
# is used as-is, unreliable or not.
KNOWN_POINT_COORDINATES: dict[str, tuple[float, float, float]] = {
    # Mesa 3 (pointId 6) -- confirmed live 2026-09-09: dispatched via
    # `call_to_point`, watched `location` change in real time
    # (3.9,1.54 staging -> here), Carlos confirmed visually it was a real,
    # new arrival, not a stuck reading.
    "bf13d6f6d4c31e00b678493da35aee41": (-1.74, 1.23, 0.0),
    # Mesa 1 (3b2a81089aae8186d7c9a413725a3a5d) and Mesa 2
    # (cec1284e136c488b3fd227a6b51b6b0a): NOT yet captured. Mesa 2's one real
    # attempt got stuck mid-route (never arrived) -- do not add either
    # without a real, watched arrival first, same standard as Mesa 3 above.
}


def detect_robot_type(robot_model: str | None) -> str:
    """Detect robot type from model string.

    T-series → food delivery, W-series → hotel, C-series/CLEAN → cleaning.
    Defaults to 'food'.
    """
    if not robot_model:
        return "food"
    m = robot_model.upper()
    if m.startswith("W"):
        return "hotel"
    if m.startswith("C") or "CLEAN" in m:
        return "clean"
    return "food"


def parse_coordinate(coordinate: str) -> tuple[float, float, float] | None:
    """Parse Keenon 'x,y,angle_degrees' string into (x, y, yaw_radians).

    Returns None if parsing fails.
    """
    try:
        parts = coordinate.split(",")
        if len(parts) < 3:
            return None
        return float(parts[0]), float(parts[1]), math.radians(float(parts[2]))
    except (ValueError, AttributeError):
        return None


@dataclass
class RobotState:
    """Cached state for a single Keenon robot, updated by polling and webhooks."""

    # Static metadata (refreshed every 60 s from robot list)
    robot_model: str | None = None
    app_version: str | None = None
    robot_type: str | None = None  # food | hotel | clean

    # Online & battery (from robot status / webhooks)
    online_status: bool | None = None
    online_type: int | None = None
    battery: int | None = None  # 0–100
    charge_status: int | None = None  # 1 = charging, -1 = discharging
    can_be_called: bool | None = None
    robot_state: int | None = None  # 1–6, see ROBOT_STATE_MAP

    # Scene / location (from robot status + location endpoints / webhooks)
    scene_code: str | None = None
    scene_name: str | None = None
    x: float | None = None
    y: float | None = None
    yaw: float | None = None  # radians
    floor: str | None = None
    building: str | None = None
    elevator_status: int | None = None  # 0 = normal, 1 = in elevator

    # Active task
    task_no: str | None = None
    task_status: int | None = None  # see TASK_STATUS_MAP
    task_start_ts: int | None = None  # ms timestamp when task was dispatched
    task_name: str | None = None    # human-readable label (e.g. "Send to Mesa 1")
    task_group: str | None = None   # action group (e.g. "Delivery", "Cleaning", "Hotel")
    task_report: dict | None = None  # fetched from Keenon API after task completes
    task_report_attempts: int = 0    # bounded retries for the report fetch
    task_report_last_attempt: float = 0.0  # monotonic ts of last report fetch try
    task_dest_point_uuid: str | None = None  # set on call_to_point, used for the
                                              # position snap (KNOWN_POINT_COORDINATES)
    task_dest_snapped: bool = False  # True once the snap has been applied for
                                      # this task, so it isn't re-logged every poll

    # Cleaning-specific (populated only when robot_type == "clean")
    clean_main_state: int | None = None
    clean_sub_state: int | None = None
    clean_faulting: bool | None = None
    clean_scram: bool | None = None
    clean_navigating: bool | None = None
    clean_bilge_tank: int | None = None
    clean_water_tank: int | None = None

    # Connectivity
    api_connected: bool = False
    last_update: float = field(default=0.0)
