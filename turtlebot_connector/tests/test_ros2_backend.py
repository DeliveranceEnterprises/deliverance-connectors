# SPDX-FileCopyrightText: 2026 Deliverance Enterprises
#
# SPDX-License-Identifier: MIT

"""Pure logic tests for the ROS 2 / Gazebo backend helpers."""

from __future__ import annotations

import math

import pytest

from turtlebot_connector.src.backends.ros2_gazebo import quaternion_to_yaw, yaw_to_quaternion


def test_yaw_quaternion_round_trip() -> None:
    yaw = math.radians(90)
    qx, qy, qz, qw = yaw_to_quaternion(yaw)

    assert qx == pytest.approx(0.0)
    assert qy == pytest.approx(0.0)
    assert quaternion_to_yaw(qx, qy, qz, qw) == pytest.approx(yaw)


def test_quaternion_to_yaw_negative() -> None:
    qx, qy, qz, qw = yaw_to_quaternion(math.radians(-45))
    assert quaternion_to_yaw(qx, qy, qz, qw) == pytest.approx(math.radians(-45))
