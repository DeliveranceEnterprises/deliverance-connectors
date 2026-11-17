# SPDX-FileCopyrightText: 2026 Deliverance Enterprises
#
# SPDX-License-Identifier: MIT

"""Tests for the fake TurtleBot simulator."""

from __future__ import annotations

import pytest

from turtlebot_connector.src.config.models import TurtlebotConfig, TurtlebotRobotConfig
from turtlebot_connector.src.simulator import (
    FakeTurtlebotSimulator,
    NoActiveTaskError,
    OperationalState,
    TaskState,
    UnknownWaypointError,
)


def test_movement_reaches_waypoint_and_returns_to_idle(
    robot_config: TurtlebotRobotConfig,
    connector_config: TurtlebotConfig,
) -> None:
    simulator = FakeTurtlebotSimulator(robot_config, connector_config)

    task = simulator.dispatch_to("station_1", task_id="task-1")
    moving_state = simulator.step(1.0)

    assert task.state == TaskState.EXECUTING
    assert moving_state.operational_state == OperationalState.MOVING
    assert moving_state.pose.x == pytest.approx(0.5)

    final_state = simulator.step(1.0)

    assert final_state.operational_state == OperationalState.IDLE
    assert final_state.pose.x == pytest.approx(1.0)
    assert final_state.last_task is not None
    assert final_state.last_task.state == TaskState.COMPLETED
    assert final_state.last_task.completed_percent == pytest.approx(1.0)
    assert final_state.current_task is None


def test_state_changes_idle_to_moving_to_idle(
    robot_config: TurtlebotRobotConfig,
    connector_config: TurtlebotConfig,
) -> None:
    simulator = FakeTurtlebotSimulator(robot_config, connector_config)

    assert simulator.snapshot().operational_state == OperationalState.IDLE
    simulator.dispatch_to("station_1")
    assert simulator.snapshot().operational_state == OperationalState.MOVING
    simulator.step(3.0)
    assert simulator.snapshot().operational_state == OperationalState.IDLE


def test_cancel_task_marks_last_task_canceled(
    robot_config: TurtlebotRobotConfig,
    connector_config: TurtlebotConfig,
) -> None:
    simulator = FakeTurtlebotSimulator(robot_config, connector_config)

    task = simulator.dispatch_to("station_1", task_id="task-cancel")
    canceled = simulator.cancel_task(task.task_id)

    assert canceled.state == TaskState.CANCELED
    assert simulator.snapshot().operational_state == OperationalState.IDLE
    assert simulator.snapshot().last_task is not None
    assert simulator.snapshot().last_task.state == TaskState.CANCELED


def test_cancel_without_active_task_raises(
    robot_config: TurtlebotRobotConfig,
    connector_config: TurtlebotConfig,
) -> None:
    simulator = FakeTurtlebotSimulator(robot_config, connector_config)
    with pytest.raises(NoActiveTaskError):
        simulator.cancel_task()


def test_unknown_waypoint_raises(
    robot_config: TurtlebotRobotConfig,
    connector_config: TurtlebotConfig,
) -> None:
    simulator = FakeTurtlebotSimulator(robot_config, connector_config)
    with pytest.raises(UnknownWaypointError, match="Unknown waypoint"):
        simulator.dispatch_to("missing")


def test_waypoints_are_loaded_from_config(
    robot_config: TurtlebotRobotConfig,
    connector_config: TurtlebotConfig,
) -> None:
    simulator = FakeTurtlebotSimulator(robot_config, connector_config)
    assert set(simulator.waypoints) == {"home", "station_1", "station_2", "charger"}
