# SPDX-FileCopyrightText: 2026 Deliverance Enterprises
#
# SPDX-License-Identifier: MIT

"""Tests for TurtlebotConnector command handling and publishing."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest

from inorbit_connector.commands import CommandFailure, CommandResultCode

from turtlebot_connector.src.backends.ros2_gazebo import Ros2UnavailableError
from turtlebot_connector.src.commands import CustomScripts
from turtlebot_connector.src.config.models import TurtlebotBackendType, TurtlebotConnectorConfig
from turtlebot_connector.src.connector import TurtlebotConnector
from turtlebot_connector.src.simulator import FakeTurtlebotSimulator


def _make_connector() -> TurtlebotConnector:
    config = TurtlebotConnectorConfig(
        connector_type="turtlebot",
        update_freq=1.0,
        connector_config={"provider_name": "fake_turtlebot", "movement_speed_mps": 1.0},
        fleet=[
            {
                "robot_id": "turtlebot-demo-01",
                "name": "TurtleBot Demo 01",
                "initial_pose": {"x": 0.0, "y": 0.0, "yaw": 0.0},
                "waypoints": [
                    {"name": "home", "x": 0.0, "y": 0.0, "yaw": 0.0},
                    {"name": "station_1", "x": 1.0, "y": 0.0, "yaw": 0.0},
                    {"name": "station_2", "x": -1.0, "y": 0.0, "yaw": 3.14},
                    {"name": "charger", "x": 0.0, "y": -1.0, "yaw": -1.57},
                ],
            }
        ],
    )
    connector = TurtlebotConnector.__new__(TurtlebotConnector)
    connector._backends = {
        robot.robot_id: FakeTurtlebotSimulator(robot, config.connector_config)
        for robot in config.fleet
    }
    connector._logger = logging.getLogger("test")
    return connector


def _result_collector():
    calls: list = []

    def result_fn(code, **kwargs):
        calls.append((code, kwargs))

    return calls, result_fn


async def test_go_to_command_starts_simulated_task() -> None:
    connector = _make_connector()
    calls, result_fn = _result_collector()

    await connector._inorbit_robot_command_handler(
        robot_id="turtlebot-demo-01",
        command_name="customCommand",
        args=[CustomScripts.GO_TO, ["waypoint", "station_1", "task_id", "task-1"]],
        options={"result_function": result_fn},
    )

    state = connector._backends["turtlebot-demo-01"].snapshot()
    assert state.current_task is not None
    assert state.current_task.task_id == "task-1"
    assert calls[0][0] == CommandResultCode.SUCCESS


async def test_unknown_waypoint_command_raises_command_failure() -> None:
    connector = _make_connector()
    _, result_fn = _result_collector()

    with pytest.raises(CommandFailure, match="Unknown waypoint"):
        await connector._inorbit_robot_command_handler(
            robot_id="turtlebot-demo-01",
            command_name="customCommand",
            args=[CustomScripts.GO_TO, ["waypoint", "missing"]],
            options={"result_function": result_fn},
        )


def test_publish_robot_data_includes_demo_key_values() -> None:
    connector = _make_connector()
    connector.publish_robot_pose = MagicMock()
    connector.publish_robot_odometry = MagicMock()
    connector.publish_robot_key_values = MagicMock()

    simulator = connector._backends["turtlebot-demo-01"]
    simulator.dispatch_to("station_1", task_id="task-1")
    state = simulator.step(0.25)

    connector._publish_robot_data("turtlebot-demo-01", state)

    connector.publish_robot_pose.assert_called_once()
    connector.publish_robot_odometry.assert_called_once()
    kv = connector.publish_robot_key_values.call_args.kwargs
    assert kv["online_status"] is True
    assert kv["operational_state"] == "moving"
    assert kv["current_waypoint"] == "station_1"
    assert kv["mission_status"] == "Mission"


def test_fake_backend_does_not_require_ros2() -> None:
    config = TurtlebotConnectorConfig(
        connector_type="turtlebot",
        connector_config={"backend": "fake"},
        fleet=[
            {
                "robot_id": "turtlebot-demo-01",
                "waypoints": [
                    {"name": "home", "x": 0.0, "y": 0.0, "yaw": 0.0},
                    {"name": "station_1", "x": 1.0, "y": 0.0, "yaw": 0.0},
                    {"name": "station_2", "x": -1.0, "y": 0.0, "yaw": 3.14},
                    {"name": "charger", "x": 0.0, "y": -1.0, "yaw": -1.57},
                ],
            }
        ],
    )

    connector = TurtlebotConnector(config)

    assert config.connector_config.backend == TurtlebotBackendType.FAKE
    assert isinstance(connector._backends["turtlebot-demo-01"], FakeTurtlebotSimulator)


def test_ros2_backend_requires_ros2_when_selected(monkeypatch: pytest.MonkeyPatch) -> None:
    from turtlebot_connector.src.backends import ros2_gazebo

    def fake_import_module(name: str):
        if name == "rclpy":
            raise ImportError("rclpy missing in unit test")
        raise AssertionError(f"unexpected import: {name}")

    monkeypatch.setattr(ros2_gazebo.importlib, "import_module", fake_import_module)

    config = TurtlebotConnectorConfig(
        connector_type="turtlebot",
        connector_config={"backend": "ros2_gazebo"},
        fleet=[
            {
                "robot_id": "turtlebot-demo-01",
                "waypoints": [
                    {"name": "home", "x": 0.0, "y": 0.0, "yaw": 0.0},
                    {"name": "station_1", "x": 1.0, "y": 0.0, "yaw": 0.0},
                    {"name": "station_2", "x": -1.0, "y": 0.0, "yaw": 3.14},
                    {"name": "charger", "x": 0.0, "y": -1.0, "yaw": -1.57},
                ],
            }
        ],
    )

    with pytest.raises(Ros2UnavailableError):
        TurtlebotConnector(config)
