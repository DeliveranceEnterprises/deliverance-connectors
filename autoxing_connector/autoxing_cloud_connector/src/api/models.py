# SPDX-FileCopyrightText: 2026 Deliverance Enterprises
#
# SPDX-License-Identifier: MIT

"""Shared data models for the AutoXing Cloud API integration."""

import math
import time
from dataclasses import dataclass, field


def degrees_to_radians(degrees: float) -> float:
    return degrees * math.pi / 180.0


@dataclass
class RobotState:
    """Cached state for a single AutoXing robot, updated each poll cycle."""

    # Pose
    x: float | None = None
    y: float | None = None
    yaw: float | None = None  # radians
    speed: float | None = None

    # Area / map
    area_id: str | None = None
    area_name: str | None = None

    # Battery & charging
    battery: int | None = None  # 0-100
    is_charging: bool | None = None
    is_go_home: bool | None = None

    # Status flags
    online: bool = False
    is_task: bool = False
    is_emergency_stop: bool | None = None
    is_manual_mode: bool | None = None
    is_remote_mode: bool | None = None
    has_obstruction: bool | None = None
    loc_quality: int | None = None  # 0-100
    errors: list[int] = field(default_factory=list)

    # Current task
    task_id: str | None = None
    task_name: str | None = None
    task_is_finish: bool | None = None
    task_is_cancel: bool | None = None
    task_start_ts: int | None = None  # epoch ms

    # Connectivity
    api_connected: bool = False
    last_update: float = field(default_factory=time.time)
