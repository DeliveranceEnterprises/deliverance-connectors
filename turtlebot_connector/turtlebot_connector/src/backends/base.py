# SPDX-FileCopyrightText: 2026 Deliverance Enterprises
#
# SPDX-License-Identifier: MIT

"""Shared backend contract and state models for TurtleBot runtimes."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol


class OperationalState(str, Enum):
    """Simplified operational state published by the connector."""

    IDLE = "idle"
    MOVING = "moving"
    CHARGING = "charging"
    ERROR = "error"


class TaskState(str, Enum):
    """Lifecycle state for simulated or Nav2-backed tasks."""

    EXECUTING = "executing"
    COMPLETED = "completed"
    CANCELED = "canceled"
    ERROR = "error"


@dataclass
class TurtlebotPose:
    """Current robot pose."""

    x: float
    y: float
    yaw: float


@dataclass
class TurtlebotTask:
    """Current or last task."""

    task_id: str
    label: str
    waypoint: str
    state: TaskState
    start_ts: int
    end_ts: int | None = None
    completed_percent: float = 0.0


@dataclass
class TurtlebotState:
    """Snapshot returned by a backend for publishing."""

    robot_id: str
    name: str
    online: bool
    operational_state: OperationalState
    pose: TurtlebotPose
    battery: float
    speed: float
    current_task: TurtlebotTask | None
    last_task: TurtlebotTask | None
    provider_name: str


class UnknownWaypointError(ValueError):
    """Raised when a command references an unknown waypoint."""


class NoActiveTaskError(ValueError):
    """Raised when cancellation is requested without an active task."""


class TurtlebotBackend(Protocol):
    """Common backend API used by the connector."""

    robot_id: str
    online: bool

    def dispatch_to(self, waypoint: str, task_id: str = "", label: str = "") -> TurtlebotTask:
        """Start navigation toward a named waypoint."""

    def cancel_task(self, task_id: str = "") -> TurtlebotTask:
        """Cancel the active task."""

    def step(self, delta_seconds: float) -> TurtlebotState:
        """Advance or refresh backend state and return a snapshot."""

    def snapshot(self) -> TurtlebotState:
        """Return the current state without advancing time."""

    def close(self) -> None:
        """Release backend resources."""
