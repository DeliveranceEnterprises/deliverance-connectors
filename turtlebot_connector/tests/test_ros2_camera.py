# SPDX-FileCopyrightText: 2026 Deliverance Enterprises
#
# SPDX-License-Identifier: MIT

"""Pure conversion tests for the ROS 2 image camera adapter."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from turtlebot_connector.src.backends.ros2_camera import Ros2ImageTopicCamera


def test_ros2_image_camera_converts_rgb8_to_jpg() -> None:
    camera = Ros2ImageTopicCamera(
        topic="/camera/image_raw",
        camera_id="camera",
        rate=5.0,
        scaling=1.0,
        quality=60,
        node_name="test_camera",
        use_sim_time=True,
    )

    pixels = np.array(
        [
            [[255, 0, 0], [0, 255, 0]],
            [[0, 0, 255], [255, 255, 255]],
        ],
        dtype=np.uint8,
    )
    msg = SimpleNamespace(
        height=2,
        width=2,
        encoding="rgb8",
        step=6,
        data=pixels.tobytes(),
    )

    jpg, width, height = camera._convert_image_to_jpg(msg)

    assert jpg.startswith(b"\xff\xd8")
    assert width == 2
    assert height == 2


def test_ros2_image_camera_rejects_unknown_encoding() -> None:
    camera = Ros2ImageTopicCamera(
        topic="/camera/image_raw",
        camera_id="camera",
        rate=5.0,
        scaling=1.0,
        quality=60,
        node_name="test_camera",
        use_sim_time=True,
    )
    msg = SimpleNamespace(height=1, width=1, encoding="unsupported", step=1, data=b"\x00")

    try:
        camera._convert_image_to_jpg(msg)
    except ValueError as exc:
        assert "Unsupported ROS image encoding" in str(exc)
    else:
        raise AssertionError("Expected unsupported encoding to raise ValueError")
