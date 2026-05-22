# SPDX-FileCopyrightText: 2026 Deliverance Enterprises
#
# SPDX-License-Identifier: MIT

"""Shared test fixtures for the TurtleBot demo connector."""

from __future__ import annotations

import pytest

from turtlebot_connector.src.config.models import TurtlebotConfig, TurtlebotRobotConfig


@pytest.fixture
def robot_config() -> TurtlebotRobotConfig:
    return TurtlebotRobotConfig(
        robot_id="turtlebot-demo-01",
        name="TurtleBot Demo 01",
        initial_battery=0.9,
        initial_pose={"x": 0.0, "y": 0.0, "yaw": 0.0},
        waypoints=[
            {"name": "home", "x": 0.0, "y": 0.0, "yaw": 0.0},
            {"name": "station_1", "x": 1.0, "y": 0.0, "yaw": 0.0},
            {"name": "station_2", "x": -1.0, "y": 0.0, "yaw": 3.14},
            {"name": "charger", "x": 0.0, "y": -1.0, "yaw": -1.57},
        ],
    )


@pytest.fixture
def connector_config() -> TurtlebotConfig:
    return TurtlebotConfig(
        provider_name="fake_turtlebot",
        movement_speed_mps=0.5,
        battery_drain_per_second=0.0,
    )
