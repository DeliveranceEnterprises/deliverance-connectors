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

    # Device status (from App WS devicestatus)
    battery: int | None = None  # 0-100
    fresh_water: float | None = None  # %
    sewage_water: float | None = None  # %
    work_status: str | None = None  # "Charging" / "Idle" / "Operating"
    have_task_running: bool | None = None

    # Connectivity health
    ws_connected: bool = False
    last_ws_message: float = field(default=0.0)
    last_update: float = field(default=0.0)
