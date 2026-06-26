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
    # Execution metrics from taskObj — captured while the task is active so the
    # final mission_tracking carries them (AutoXing has no task-report endpoint;
    # taskObj is gone once the task finishes).
    task_mileage: float | None = None   # distance travelled so far (m)
    task_total_dis: float | None = None  # total planned distance (m)
    task_duration: int | None = None     # elapsed seconds
    task_target_name: str | None = None  # real destination (taskPts[0].ext.name)
    task_type: int | None = None         # AutoXing taskType code
    # Task detail fields — fetched once per task from GET /task/v1.1/{taskId}.
    # taskObj.target is the RETURN point, not the destination; the real
    # destination lives in taskPts. These mirror the direct integration report.
    task_detail_fetched: str | None = None  # task_id for which detail was fetched
    task_target_x: float | None = None
    task_target_y: float | None = None
    task_back_name: str | None = None   # return point name (backPt.ext.name)
    task_back_x: float | None = None
    task_back_y: float | None = None
    task_origin_x: float | None = None  # robot position at task start (curPt)
    task_origin_y: float | None = None
    task_area_id: str | None = None
    task_building_id: str | None = None

    # Connectivity
    api_connected: bool = False
    last_update: float = field(default_factory=time.time)

    # Set to True after the first successful poll. Prevents the connector from
    # publishing pose (0, 0) as an InOrbit SDK initialisation artefact before
    # real coordinates arrive from the API.
    has_data: bool = False

    # Grace period counter: number of consecutive polls where taskObj was absent
    # while a task_id was active. The Autoxing API sometimes drops taskObj for
    # 1-2 cycles mid-task (especially when a second client polls the same API
    # simultaneously). We wait TASK_ABSENT_GRACE polls before declaring the task
    # finished to avoid creating duplicate missions in InOrbit.
    _task_absent_polls: int = 0

    # Cache of task_id → task_start_ts (epoch ms) for the current session.
    # If the API sends a false isFinish=True and the same task_id reappears,
    # we reuse the original start_ts so the missionId stays identical and
    # InOrbit treats it as an update to the same mission rather than a new one.
    # Cleared only when a genuinely different task_id appears.
    _task_start_ts_cache: dict = field(default_factory=dict)
