# SPDX-FileCopyrightText: 2026 Deliverance Enterprises
#
# SPDX-License-Identifier: MIT

"""Tests for TurtleBot connector configuration models."""

from __future__ import annotations

import copy

import pytest

from turtlebot_connector.src.config.models import CONNECTOR_TYPE, TurtlebotConnectorConfig


_BASE_CONFIG = {
    "connector_type": CONNECTOR_TYPE,
    "update_freq": 1.0,
    "connector_config": {"provider_name": "fake_turtlebot"},
    "fleet": [
        {
            "robot_id": "turtlebot-demo-01",
            "name": "TurtleBot Demo 01",
            "initial_battery": 0.8,
            "initial_pose": {"x": 0.0, "y": 0.0, "yaw": 0.0},
            "waypoints": [
                {"name": "home", "x": 0.0, "y": 0.0, "yaw": 0.0},
                {"name": "station_1", "x": 1.0, "y": 0.0, "yaw": 0.0},
                {"name": "station_2", "x": -1.0, "y": 0.0, "yaw": 3.14},
                {"name": "charger", "x": 0.0, "y": -1.0, "yaw": -1.57},
            ],
        }
    ],
}


def test_valid_config_loads() -> None:
    config = TurtlebotConnectorConfig(**_BASE_CONFIG)
    assert config.connector_type == CONNECTOR_TYPE
    assert config.fleet[0].robot_id == "turtlebot-demo-01"
    assert config.fleet[0].waypoints[1].name == "station_1"
    assert config.connector_config.backend == "fake"


def test_ros2_gazebo_config_loads() -> None:
    data = copy.deepcopy(_BASE_CONFIG)
    data["connector_config"] = {
        "provider_name": "ros2_turtlebot",
        "backend": "ros2_gazebo",
        "ros2": {
            "enabled": True,
            "pose_source": "amcl",
            "odom_topic": "/odom",
            "amcl_pose_topic": "/amcl_pose",
            "nav2_action_name": "/navigate_to_pose",
            "cmd_vel_topic": "/cmd_vel",
            "map_frame": "map",
            "odom_frame": "odom",
            "base_frame": "base_link",
            "use_sim_time": True,
            "camera_enabled": True,
            "camera_id": "camera",
            "camera_topic": "/camera/image_raw",
        },
    }

    config = TurtlebotConnectorConfig(**data)

    assert config.connector_config.backend == "ros2_gazebo"
    assert config.connector_config.ros2.enabled is True
    assert config.connector_config.ros2.pose_source == "amcl"
    assert config.connector_config.ros2.camera_enabled is True
    assert config.connector_config.ros2.camera_topic == "/camera/image_raw"


def test_wrong_connector_type_raises() -> None:
    data = copy.deepcopy(_BASE_CONFIG)
    data["connector_type"] = "wrong"
    with pytest.raises(ValueError, match="Expected connector_type"):
        TurtlebotConnectorConfig(**data)


def test_duplicate_robot_ids_raise() -> None:
    data = copy.deepcopy(_BASE_CONFIG)
    data["fleet"].append(copy.deepcopy(data["fleet"][0]))
    with pytest.raises(ValueError, match="Robot ids must be unique"):
        TurtlebotConnectorConfig(**data)


def test_duplicate_waypoint_names_raise() -> None:
    data = copy.deepcopy(_BASE_CONFIG)
    data["fleet"][0]["waypoints"].append({"name": "home", "x": 2.0, "y": 2.0, "yaw": 0.0})
    with pytest.raises(ValueError, match="waypoint names must be unique"):
        TurtlebotConnectorConfig(**data)


def test_missing_required_waypoint_raises() -> None:
    data = copy.deepcopy(_BASE_CONFIG)
    data["fleet"][0]["waypoints"] = [
        waypoint for waypoint in data["fleet"][0]["waypoints"] if waypoint["name"] != "charger"
    ]
    with pytest.raises(ValueError, match="missing required waypoints: charger"):
        TurtlebotConnectorConfig(**data)
