# SPDX-FileCopyrightText: 2026 Deliverance Enterprises
#
# SPDX-License-Identifier: MIT

"""Small deterministic fake backend used by the demo TurtleBot connector."""

from __future__ import annotations

import math
import time

from turtlebot_connector.src.config.models import TurtlebotConfig, TurtlebotRobotConfig
from turtlebot_connector.src.backends.base import (
    NoActiveTaskError,
    OperationalState,
    TaskState,
    TurtlebotPose,
    TurtlebotState,
    TurtlebotTask,
    UnknownWaypointError,
)


class FakeTurtlebotSimulator:
    """In-memory TurtleBot-like simulator.

    The simulator only advances when ``step`` is called. This keeps unit tests
    deterministic and lets the connector decide how often to publish telemetry.
    """

    def __init__(
        self,
        robot_config: TurtlebotRobotConfig,
        connector_config: TurtlebotConfig,
    ) -> None:
        self.robot_id = robot_config.robot_id
        self.name = robot_config.name
        self.provider_name = connector_config.provider_name
        self.online = robot_config.online
        self.pose = TurtlebotPose(
            x=robot_config.initial_pose.x,
            y=robot_config.initial_pose.y,
            yaw=robot_config.initial_pose.yaw,
        )
        self.battery = robot_config.initial_battery
        self.speed = 0.0
        self.operational_state = (
            OperationalState.IDLE if robot_config.online else OperationalState.ERROR
        )
        self.waypoints = {waypoint.name: waypoint for waypoint in robot_config.waypoints}
        self.movement_speed_mps = connector_config.movement_speed_mps
        self.battery_drain_per_second = connector_config.battery_drain_per_second
        self.charge_rate_per_second = connector_config.charge_rate_per_second
        self.current_task: TurtlebotTask | None = None
        self.last_task: TurtlebotTask | None = None
        self._target_waypoint: str | None = None
        self._target_start_distance = 1.0

    def dispatch_to(self, waypoint: str, task_id: str = "", label: str = "") -> TurtlebotTask:
        """Start moving toward a named waypoint."""

        if waypoint not in self.waypoints:
            raise UnknownWaypointError(f"Unknown waypoint: {waypoint}")

        now_ms = int(time.time() * 1000)
        task = TurtlebotTask(
            task_id=task_id or f"{self.robot_id}-{waypoint}-{now_ms}",
            label=label or f"Go to {waypoint}",
            waypoint=waypoint,
            state=TaskState.EXECUTING,
            start_ts=now_ms,
        )
        self.current_task = task
        self.last_task = task
        self._target_waypoint = waypoint
        target = self.waypoints[waypoint]
        self._target_start_distance = max(
            math.hypot(target.x - self.pose.x, target.y - self.pose.y),
            0.001,
        )
        self.operational_state = OperationalState.MOVING
        return task

    def cancel_task(self, task_id: str = "") -> TurtlebotTask:
        """Cancel the active simulated task."""

        if self.current_task is None:
            raise NoActiveTaskError("No active task to cancel")
        if task_id and task_id != self.current_task.task_id:
            raise NoActiveTaskError(f"Active task is {self.current_task.task_id}, not {task_id}")

        self.current_task.state = TaskState.CANCELED
        self.current_task.end_ts = int(time.time() * 1000)
        self.current_task.completed_percent = 0.0
        canceled_task = self.current_task
        self.current_task = None
        self._target_waypoint = None
        self._target_start_distance = 1.0
        self.speed = 0.0
        self.operational_state = OperationalState.IDLE if self.online else OperationalState.ERROR
        return canceled_task

    def close(self) -> None:
        """No-op for the fake backend."""

    def step(self, delta_seconds: float) -> TurtlebotState:
        """Advance the simulation by ``delta_seconds`` seconds."""

        if delta_seconds <= 0:
            return self.snapshot()
        if not self.online:
            self.speed = 0.0
            self.operational_state = OperationalState.ERROR
            return self.snapshot()

        if self.current_task and self._target_waypoint:
            self._step_motion(delta_seconds)
            self.battery = max(0.0, self.battery - self.battery_drain_per_second * delta_seconds)
        elif self.operational_state == OperationalState.CHARGING:
            self.battery = min(1.0, self.battery + self.charge_rate_per_second * delta_seconds)
            if self.battery >= 0.99:
                self.operational_state = OperationalState.IDLE
        else:
            self.speed = 0.0
            self.operational_state = OperationalState.IDLE

        return self.snapshot()

    def snapshot(self) -> TurtlebotState:
        """Return a copy-like state object for publishing."""

        return TurtlebotState(
            robot_id=self.robot_id,
            name=self.name,
            online=self.online,
            operational_state=self.operational_state,
            pose=TurtlebotPose(self.pose.x, self.pose.y, self.pose.yaw),
            battery=self.battery,
            speed=self.speed,
            current_task=self.current_task,
            last_task=self.last_task,
            provider_name=self.provider_name,
        )

    def _step_motion(self, delta_seconds: float) -> None:
        waypoint = self.waypoints[self._target_waypoint or ""]
        dx = waypoint.x - self.pose.x
        dy = waypoint.y - self.pose.y
        distance = math.hypot(dx, dy)
        max_step = self.movement_speed_mps * delta_seconds

        if distance <= max_step:
            self.pose.x = waypoint.x
            self.pose.y = waypoint.y
            self.pose.yaw = waypoint.yaw
            self.speed = 0.0
            self._complete_current_task()
            if waypoint.name == "charger":
                self.operational_state = OperationalState.CHARGING
            else:
                self.operational_state = OperationalState.IDLE
            return

        ratio = max_step / distance
        self.pose.x += dx * ratio
        self.pose.y += dy * ratio
        self.pose.yaw = math.atan2(dy, dx)
        self.speed = self.movement_speed_mps
        if self.current_task:
            remaining = max(distance - max_step, 0.0)
            self.current_task.completed_percent = min(
                1.0,
                max(0.0, 1.0 - remaining / self._target_start_distance),
            )
        self.operational_state = OperationalState.MOVING

    def _complete_current_task(self) -> None:
        if self.current_task is None:
            return
        self.current_task.state = TaskState.COMPLETED
        self.current_task.completed_percent = 1.0
        self.current_task.end_ts = int(time.time() * 1000)
        self.current_task = None
        self._target_waypoint = None
        self._target_start_distance = 1.0
