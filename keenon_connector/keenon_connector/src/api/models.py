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
