# SPDX-FileCopyrightText: 2026 Deliverance Enterprises
#
# SPDX-License-Identifier: MIT

"""ROS 2 / Gazebo backend for driving TurtleBot through Nav2.

All ROS imports are deliberately optional and local to this module so the
default fake backend can run on machines without ROS 2 installed.
"""

from __future__ import annotations

import importlib
import io
import math
import threading
import time
from typing import Any

from turtlebot_connector.src.backends.base import (
    NoActiveTaskError,
    OperationalState,
    TaskState,
    TurtlebotPose,
    TurtlebotState,
    TurtlebotTask,
    UnknownWaypointError,
)
from turtlebot_connector.src.config.models import (
    Ros2GazeboConfig,
    TurtlebotConfig,
    TurtlebotRobotConfig,
)


class Ros2UnavailableError(RuntimeError):
    """Raised when ROS 2 dependencies are missing for the ROS backend."""


def quaternion_to_yaw(x: float, y: float, z: float, w: float) -> float:
    """Convert a quaternion orientation to planar yaw."""

    siny_cosp = 2.0 * (w * z + x * y)
    cosy_cosp = 1.0 - 2.0 * (y * y + z * z)
    return math.atan2(siny_cosp, cosy_cosp)


def yaw_to_quaternion(yaw: float) -> tuple[float, float, float, float]:
    """Return a planar quaternion tuple x, y, z, w for ``yaw``."""

    half_yaw = yaw / 2.0
    return 0.0, 0.0, math.sin(half_yaw), math.cos(half_yaw)


class Ros2GazeboTurtlebotClient:
    """TurtleBot backend that sends waypoint goals to Nav2."""

    def __init__(
        self,
        robot_config: TurtlebotRobotConfig,
        connector_config: TurtlebotConfig,
    ) -> None:
        self._imports = self._load_ros_imports()

        self.robot_id = robot_config.robot_id
        self.name = robot_config.name
        self.provider_name = connector_config.provider_name
        self.online = robot_config.online
        self.battery = robot_config.initial_battery
        self.speed = 0.0
        self.operational_state = (
            OperationalState.IDLE if robot_config.online else OperationalState.ERROR
        )
        self.pose = TurtlebotPose(
            x=robot_config.initial_pose.x,
            y=robot_config.initial_pose.y,
            yaw=robot_config.initial_pose.yaw,
        )
        self.waypoints = {waypoint.name: waypoint for waypoint in robot_config.waypoints}
        self.ros2_config: Ros2GazeboConfig = connector_config.ros2
        self.current_task: TurtlebotTask | None = None
        self.last_task: TurtlebotTask | None = None
        self._goal_handle: Any | None = None
        self._lock = threading.Lock()
        self._closed = False

        rclpy = self._imports["rclpy"]
        if not rclpy.ok():
            rclpy.init(args=None)

        node_name = f"turtlebot_connector_{self.robot_id.replace('-', '_')}"
        self._node = rclpy.create_node(node_name)
        if self.ros2_config.use_sim_time:
            parameter = self._imports["Parameter"](
                "use_sim_time",
                self._imports["Parameter"].Type.BOOL,
                True,
            )
            self._node.set_parameters([parameter])
        self._executor = self._imports["MultiThreadedExecutor"]()
        self._executor.add_node(self._node)
        self._executor_thread = threading.Thread(
            target=self._executor.spin,
            name=f"{node_name}_executor",
            daemon=True,
        )
        self._executor_thread.start()

        if self.ros2_config.pose_source == "amcl":
            pose_topic = self.ros2_config.amcl_pose_topic
            pose_type = self._imports["PoseWithCovarianceStamped"]
            callback = self._amcl_pose_callback
        else:
            pose_topic = self.ros2_config.odom_topic
            pose_type = self._imports["Odometry"]
            callback = self._odom_callback

        self._pose_subscription = self._node.create_subscription(
            pose_type,
            pose_topic,
            callback,
            10,
        )
        self._nav_action_client = self._imports["ActionClient"](
            self._node,
            self._imports["NavigateToPose"],
            self.ros2_config.nav2_action_name,
        )

        self._latest_map: Any | None = None
        # slam_toolbox publishes /map with transient-local durability; use a
        # matching QoS so the subscriber receives the last map even if it
        # connects after the first publish.
        _qos = rclpy.qos.QoSProfile(
            depth=1,
            durability=rclpy.qos.DurabilityPolicy.TRANSIENT_LOCAL,
            reliability=rclpy.qos.ReliabilityPolicy.RELIABLE,
        )
        self._map_subscription = self._node.create_subscription(
            self._imports["OccupancyGrid"],
            "/map",
            self._map_callback,
            _qos,
        )

    def dispatch_to(self, waypoint: str, task_id: str = "", label: str = "") -> TurtlebotTask:
        """Send a NavigateToPose goal for a configured waypoint."""

        if waypoint not in self.waypoints:
            raise UnknownWaypointError(f"Unknown waypoint: {waypoint}")

        if not self._nav_action_client.wait_for_server(timeout_sec=2.0):
            self._mark_error()
            raise RuntimeError(
                f"Nav2 action server '{self.ros2_config.nav2_action_name}' is not available"
            )

        now_ms = int(time.time() * 1000)
        task = TurtlebotTask(
            task_id=task_id or f"{self.robot_id}-{waypoint}-{now_ms}",
            label=label or f"Go to {waypoint}",
            waypoint=waypoint,
            state=TaskState.EXECUTING,
            start_ts=now_ms,
        )

        with self._lock:
            self.current_task = task
            self.last_task = task
            self.operational_state = OperationalState.MOVING
            self.speed = 0.0

        goal_msg = self._build_nav2_goal(waypoint)
        future = self._nav_action_client.send_goal_async(goal_msg)
        future.add_done_callback(self._goal_response_callback)
        return task

    def cancel_task(self, task_id: str = "") -> TurtlebotTask:
        """Cancel the active Nav2 goal."""

        with self._lock:
            if self.current_task is None:
                raise NoActiveTaskError("No active task to cancel")
            if task_id and task_id != self.current_task.task_id:
                raise NoActiveTaskError(f"Active task is {self.current_task.task_id}, not {task_id}")
            task = self.current_task

        if self._goal_handle is not None:
            self._goal_handle.cancel_goal_async()

        with self._lock:
            task.state = TaskState.CANCELED
            task.completed_percent = 0.0
            task.end_ts = int(time.time() * 1000)
            self.current_task = None
            self.operational_state = OperationalState.IDLE if self.online else OperationalState.ERROR
            self.speed = 0.0

        return task

    def step(self, delta_seconds: float) -> TurtlebotState:
        """Return latest ROS state; ROS callbacks advance asynchronously."""

        _ = delta_seconds
        return self.snapshot()

    def snapshot(self) -> TurtlebotState:
        """Return the current ROS-backed state."""

        with self._lock:
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

    def close(self) -> None:
        """Release ROS resources."""

        if self._closed:
            return
        self._closed = True
        self._executor.shutdown()
        self._executor_thread.join(timeout=2.0)
        self._node.destroy_node()

    def _build_nav2_goal(self, waypoint_name: str) -> Any:
        waypoint = self.waypoints[waypoint_name]
        goal_msg = self._imports["NavigateToPose"].Goal()
        goal_msg.pose.header.frame_id = self.ros2_config.map_frame
        goal_msg.pose.header.stamp = self._node.get_clock().now().to_msg()
        goal_msg.pose.pose.position.x = waypoint.x
        goal_msg.pose.pose.position.y = waypoint.y
        goal_msg.pose.pose.position.z = 0.0
        qx, qy, qz, qw = yaw_to_quaternion(waypoint.yaw)
        goal_msg.pose.pose.orientation.x = qx
        goal_msg.pose.pose.orientation.y = qy
        goal_msg.pose.pose.orientation.z = qz
        goal_msg.pose.pose.orientation.w = qw
        return goal_msg

    def _goal_response_callback(self, future: Any) -> None:
        goal_handle = future.result()
        if not goal_handle.accepted:
            self._mark_error()
            return

        self._goal_handle = goal_handle
        result_future = goal_handle.get_result_async()
        result_future.add_done_callback(self._goal_result_callback)

    def _goal_result_callback(self, future: Any) -> None:
        result = future.result()
        status = result.status
        goal_status = self._imports["GoalStatus"]

        with self._lock:
            task = self.current_task
            if task is None:
                return
            task.end_ts = int(time.time() * 1000)

            if status == goal_status.STATUS_SUCCEEDED:
                task.state = TaskState.COMPLETED
                task.completed_percent = 1.0
                self.operational_state = OperationalState.IDLE
            elif status == goal_status.STATUS_CANCELED:
                task.state = TaskState.CANCELED
                task.completed_percent = 0.0
                self.operational_state = OperationalState.IDLE
            else:
                task.state = TaskState.ERROR
                task.completed_percent = 0.0
                self.operational_state = OperationalState.ERROR

            self.current_task = None
            self.speed = 0.0

    def _map_callback(self, msg: Any) -> None:
        with self._lock:
            self._latest_map = msg

    def get_latest_map(self) -> Any | None:
        """Return the latest OccupancyGrid message received on /map, or None."""
        with self._lock:
            return self._latest_map

    def _odom_callback(self, msg: Any) -> None:
        pose = msg.pose.pose
        twist = msg.twist.twist
        self._update_pose_from_ros_pose(pose)
        with self._lock:
            self.speed = float(twist.linear.x)

    def _amcl_pose_callback(self, msg: Any) -> None:
        self._update_pose_from_ros_pose(msg.pose.pose)

    def _update_pose_from_ros_pose(self, pose: Any) -> None:
        orientation = pose.orientation
        yaw = quaternion_to_yaw(
            float(orientation.x),
            float(orientation.y),
            float(orientation.z),
            float(orientation.w),
        )
        with self._lock:
            self.pose = TurtlebotPose(
                x=float(pose.position.x),
                y=float(pose.position.y),
                yaw=yaw,
            )

    def _mark_error(self) -> None:
        with self._lock:
            if self.current_task is not None:
                self.current_task.state = TaskState.ERROR
                self.current_task.end_ts = int(time.time() * 1000)
                self.current_task.completed_percent = 0.0
                self.current_task = None
            self.operational_state = OperationalState.ERROR
            self.speed = 0.0

    def _load_ros_imports(self) -> dict[str, Any]:
        try:
            rclpy = importlib.import_module("rclpy")
            action_module = importlib.import_module("rclpy.action")
            executors_module = importlib.import_module("rclpy.executors")
            nav2_module = importlib.import_module("nav2_msgs.action")
            action_msgs_module = importlib.import_module("action_msgs.msg")
            nav_msgs_module = importlib.import_module("nav_msgs.msg")
            geometry_msgs_module = importlib.import_module("geometry_msgs.msg")
            parameter_module = importlib.import_module("rclpy.parameter")
        except ImportError as exc:
            raise Ros2UnavailableError(
                "backend=ros2_gazebo requires ROS 2 Python packages: rclpy, "
                "nav2_msgs, action_msgs, nav_msgs, and geometry_msgs. "
                "Use backend=fake on machines without ROS 2."
            ) from exc

        return {
            "rclpy": rclpy,
            "ActionClient": action_module.ActionClient,
            "MultiThreadedExecutor": executors_module.MultiThreadedExecutor,
            "NavigateToPose": nav2_module.NavigateToPose,
            "GoalStatus": action_msgs_module.GoalStatus,
            "Odometry": nav_msgs_module.Odometry,
            "OccupancyGrid": nav_msgs_module.OccupancyGrid,
            "PoseWithCovarianceStamped": geometry_msgs_module.PoseWithCovarianceStamped,
            "Parameter": parameter_module.Parameter,
        }
