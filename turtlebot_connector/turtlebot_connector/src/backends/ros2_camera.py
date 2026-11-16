# SPDX-FileCopyrightText: 2026 Deliverance Enterprises
#
# SPDX-License-Identifier: MIT

"""ROS 2 image topic camera adapter for InOrbit Edge SDK streaming."""

from __future__ import annotations

import importlib
import logging
import threading
import time
from typing import Any

from inorbit_edge.video import Camera, convert_frame

from turtlebot_connector.src.backends.ros2_gazebo import Ros2UnavailableError


class Ros2ImageTopicCamera(Camera):
    """InOrbit camera adapter backed by a ROS 2 ``sensor_msgs/Image`` topic."""

    def __init__(
        self,
        *,
        topic: str,
        camera_id: str,
        rate: float,
        scaling: float,
        quality: int,
        node_name: str,
        use_sim_time: bool,
    ) -> None:
        self.topic = topic
        self.camera_id = camera_id
        self.rate = rate
        self.scaling = scaling
        self.quality = quality
        self.node_name = node_name
        self.use_sim_time = use_sim_time

        self._logger = logging.getLogger(__name__)
        self._lock = threading.Lock()
        self._latest_frame: tuple[bytes, int, int, float] | None = None
        self._imports: dict[str, Any] | None = None
        self._node: Any | None = None
        self._executor: Any | None = None
        self._executor_thread: threading.Thread | None = None
        self._frames_received = 0

    def open(self) -> None:
        """Subscribe to the ROS image topic."""

        if self._node is not None:
            return

        self._logger.info(
            "Opening ROS camera adapter '%s' on topic '%s'",
            self.camera_id,
            self.topic,
        )

        self._imports = self._load_ros_imports()
        rclpy = self._imports["rclpy"]
        if not rclpy.ok():
            rclpy.init(args=None)

        self._node = rclpy.create_node(self.node_name)
        if self.use_sim_time:
            parameter = self._imports["Parameter"](
                "use_sim_time",
                self._imports["Parameter"].Type.BOOL,
                True,
            )
            self._node.set_parameters([parameter])

        self._node.create_subscription(
            self._imports["Image"],
            self.topic,
            self._image_callback,
            10,
        )
        self._executor = self._imports["MultiThreadedExecutor"]()
        self._executor.add_node(self._node)
        self._executor_thread = threading.Thread(
            target=self._executor.spin,
            name=f"{self.node_name}_executor",
            daemon=True,
        )
        self._executor_thread.start()

    def close(self) -> None:
        """Release ROS resources."""

        self._logger.info(
            "Closing ROS camera adapter '%s' after receiving %d frame(s)",
            self.camera_id,
            self._frames_received,
        )

        if self._executor is not None:
            self._executor.shutdown()
        if self._executor_thread is not None:
            self._executor_thread.join(timeout=2.0)
        if self._node is not None:
            self._node.destroy_node()

        self._executor = None
        self._executor_thread = None
        self._node = None

    def get_frame_jpg(self) -> tuple[bytes | None, int, int, float]:
        """Return the latest ROS image encoded as JPEG."""

        with self._lock:
            if self._latest_frame is None:
                return None, 0, 0, time.time() * 1000
            return self._latest_frame

    def _image_callback(self, msg: Any) -> None:
        try:
            jpg, width, height = self._convert_image_to_jpg(msg)
        except (ValueError, RuntimeError):
            return

        self._frames_received += 1
        if self._frames_received == 1:
            self._logger.info(
                "Received first ROS camera frame for '%s' from topic '%s' (%dx%d, encoding=%s)",
                self.camera_id,
                self.topic,
                int(msg.width),
                int(msg.height),
                msg.encoding,
            )

        with self._lock:
            self._latest_frame = (jpg, width, height, time.time() * 1000)

    def _convert_image_to_jpg(self, msg: Any) -> tuple[bytes, int, int]:
        cv2 = self._imports["cv2"] if self._imports else importlib.import_module("cv2")
        np = self._imports["numpy"] if self._imports else importlib.import_module("numpy")

        height = int(msg.height)
        width = int(msg.width)
        encoding = str(msg.encoding).lower()
        step = int(msg.step)
        data = bytes(msg.data)

        if height <= 0 or width <= 0:
            raise ValueError("Invalid image dimensions")

        if encoding in {"rgb8", "bgr8"}:
            channels = 3
        elif encoding in {"rgba8", "bgra8"}:
            channels = 4
        elif encoding in {"mono8", "8uc1"}:
            channels = 1
        else:
            raise ValueError(f"Unsupported ROS image encoding: {msg.encoding}")

        expected_row_bytes = width * channels
        if step < expected_row_bytes:
            raise RuntimeError("ROS image step is smaller than expected row width")

        array = np.frombuffer(data, dtype=np.uint8).reshape((height, step))
        array = array[:, :expected_row_bytes]

        if channels == 1:
            frame = array.reshape((height, width))
            frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
        else:
            frame = array.reshape((height, width, channels))
            if encoding == "rgb8":
                frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
            elif encoding == "rgba8":
                frame = cv2.cvtColor(frame, cv2.COLOR_RGBA2BGR)
            elif encoding == "bgra8":
                frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)

        jpg, scaled_width, scaled_height = convert_frame(
            frame,
            width,
            height,
            self.scaling,
            self.quality,
        )
        return jpg, scaled_width, scaled_height

    def _load_ros_imports(self) -> dict[str, Any]:
        try:
            rclpy = importlib.import_module("rclpy")
            executors_module = importlib.import_module("rclpy.executors")
            parameter_module = importlib.import_module("rclpy.parameter")
            sensor_msgs_module = importlib.import_module("sensor_msgs.msg")
            cv2 = importlib.import_module("cv2")
            numpy = importlib.import_module("numpy")
        except ImportError as exc:
            raise Ros2UnavailableError(
                "ROS camera streaming requires rclpy, sensor_msgs, opencv-python, and numpy."
            ) from exc

        return {
            "rclpy": rclpy,
            "MultiThreadedExecutor": executors_module.MultiThreadedExecutor,
            "Parameter": parameter_module.Parameter,
            "Image": sensor_msgs_module.Image,
            "cv2": cv2,
            "numpy": numpy,
        }
