# SPDX-FileCopyrightText: 2026 Deliverance Enterprises
#
# SPDX-License-Identifier: MIT

"""InOrbit FleetConnector implementation for TurtleBot backends."""

from __future__ import annotations

import io
import math
import time
from typing_extensions import override

from inorbit_connector.commands import CommandFailure, CommandResultCode, parse_custom_command_args
from inorbit_connector.connector import FleetConnector
from inorbit_connector.models import MapConfigTemp
from inorbit_edge.robot import (
    COMMAND_CUSTOM_COMMAND,
    COMMAND_INITIAL_POSE,
    COMMAND_NAV_GOAL,
)
from inorbit_edge.inorbit_pb2 import Nav2DPathMessage, Nav2DWaypointFrame

from turtlebot_connector import __version__ as connector_version
from turtlebot_connector.src.backends.base import (
    NoActiveTaskError,
    OperationalState,
    TaskState,
    TurtlebotBackend,
    TurtlebotState,
    TurtlebotTask,
    UnknownWaypointError,
)
from turtlebot_connector.src.backends.ros2_gazebo import (
    Ros2GazeboTurtlebotClient,
    Ros2UnavailableError,
)
from turtlebot_connector.src.backends.ros2_camera import Ros2ImageTopicCamera
from turtlebot_connector.src.commands import CancelTaskCommand, CustomScripts, DispatchCommand, GoToCommand
from turtlebot_connector.src.config.models import TurtlebotBackendType, TurtlebotConnectorConfig, TurtlebotRobotConfig
from turtlebot_connector.src.simulator import FakeTurtlebotSimulator


class TurtlebotConnector(FleetConnector):
    """Demo Edge connector that publishes fake TurtleBot telemetry."""

    def __init__(self, config: TurtlebotConnectorConfig) -> None:
        super().__init__(config, publish_connector_system_stats=True)
        self._backends: dict[str, TurtlebotBackend] = {}
        self._robot_configs: dict[str, TurtlebotRobotConfig] = {}
        self._registered_ros_cameras: set[str] = set()
        self._instrumented_sessions: set[str] = set()
        # Track the last Open Teleop goal we sent so consecutive clicks
        # accumulate instead of fighting Nav2 in-flight.
        # robot_id -> (timestamp_monotonic, x, y, yaw)
        self._open_teleop_last_goal: dict[str, tuple[float, float, float, float]] = {}
        for robot in config.fleet:
            self._backends[robot.robot_id] = self._build_backend(robot)
            self._robot_configs[robot.robot_id] = robot
        self._last_tick = time.monotonic()

    def _build_backend(self, robot) -> TurtlebotBackend:
        backend = self.config.connector_config.backend
        if backend == TurtlebotBackendType.FAKE:
            return FakeTurtlebotSimulator(robot, self.config.connector_config)
        if backend == TurtlebotBackendType.ROS2_GAZEBO:
            try:
                return Ros2GazeboTurtlebotClient(robot, self.config.connector_config)
            except Ros2UnavailableError:
                raise
            except Exception as exc:
                raise RuntimeError(
                    f"Failed to initialize ROS 2 backend for robot {robot.robot_id}: {exc}"
                ) from exc
        raise ValueError(f"Unsupported TurtleBot backend: {backend}")

    @override
    async def _connect(self) -> None:
        self._last_tick = time.monotonic()
        self._logger.info(
            "Connected TurtleBot fleet using backend=%s",
            self.config.connector_config.backend.value,
        )

    @override
    async def _disconnect(self) -> None:
        for backend in self._backends.values():
            backend.close()
        self._logger.info("Disconnected TurtleBot fleet")

    @override
    async def _execution_loop(self) -> None:
        now = time.monotonic()
        delta_seconds = now - self._last_tick
        self._last_tick = now

        for robot_id, backend in self._backends.items():
            self._instrument_robot_session_if_needed(robot_id)
            self._register_ros_camera_if_needed(robot_id)
            state = backend.step(delta_seconds)
            self._publish_robot_data(robot_id, state)

    def _instrument_robot_session_if_needed(self, robot_id: str) -> None:
        if robot_id in self._instrumented_sessions:
            return

        session = self._get_robot_session(robot_id)
        # Subscribe to the InOrbit "Precision Teleop" topic and route it through
        # our own handler, since the Edge SDK does not expose a callback for it.
        # Topic shape: r/<robot_id>/ros/nav/goal_path
        # Payload:     Nav2DPathMessage protobuf — last waypoint is the target,
        #              expressed in frame=ROBOT (i.e. relative to the robot).
        nav_topic = session._get_robot_subtopic(subtopic="ros/nav/goal_path")

        def on_goal_path(client, userdata, msg):
            try:
                self._handle_precision_teleop_path(robot_id, msg.payload)
            except Exception as exc:
                self._logger.error(
                    "Failed to handle precision teleop path for robot '%s': %s",
                    robot_id,
                    exc,
                )

        session.client.message_callback_add(nav_topic, on_goal_path)
        session.client.subscribe(nav_topic)
        self._logger.info(
            "Subscribed to precision-teleop topic '%s' for robot '%s'",
            nav_topic,
            robot_id,
        )

        # InOrbit "Open Teleop" d-pad. Payload is "seq|ts|N" where N encodes
        # the direction:  0 = forward,  2 = backward,  1 = left,  -1 = right.
        step_topic = session._get_robot_subtopic(subtopic="ros/teleop/step")

        def on_teleop_step(client, userdata, msg):
            try:
                self._handle_open_teleop_step(robot_id, msg.payload)
            except Exception as exc:
                self._logger.error(
                    "Failed to handle open teleop step for robot '%s': %s",
                    robot_id,
                    exc,
                )

        session.client.message_callback_add(step_topic, on_teleop_step)
        session.client.subscribe(step_topic)
        self._logger.info(
            "Subscribed to open-teleop topic '%s' for robot '%s'",
            step_topic,
            robot_id,
        )

        self._instrumented_sessions.add(robot_id)

    def _handle_open_teleop_step(self, robot_id: str, payload: bytes) -> None:
        """Decode an InOrbit Open Teleop d-pad step and forward it as a
        relative NavigateToPose goal.

        Payload format: "seq|ts|N" where N is:
            0  forward     2  backward
            1  left turn  -1  right turn
        """

        backend = self._backends.get(robot_id)
        if backend is None:
            self._logger.warning(
                "Received open teleop step for unknown robot '%s'", robot_id
            )
            return

        try:
            text = payload.decode("utf-8")
            parts = text.split("|")
            direction = int(parts[2])
        except (UnicodeDecodeError, IndexError, ValueError) as exc:
            self._logger.error(
                "Could not parse open teleop step %r for robot '%s': %s",
                payload,
                robot_id,
                exc,
            )
            return

        ros2_cfg = self.config.connector_config.ros2
        linear_step = float(ros2_cfg.open_teleop_linear_step_m)
        angular_step = float(ros2_cfg.open_teleop_angular_step_rad)

        if direction == 0:
            dx, dy, dtheta = linear_step, 0.0, 0.0
            label = "Open Teleop Forward"
        elif direction == 2:
            dx, dy, dtheta = -linear_step, 0.0, 0.0
            label = "Open Teleop Backward"
        elif direction == 1:
            dx, dy, dtheta = 0.0, 0.0, angular_step
            label = "Open Teleop Left"
        elif direction == -1:
            dx, dy, dtheta = 0.0, 0.0, -angular_step
            label = "Open Teleop Right"
        else:
            self._logger.warning(
                "Unknown open teleop direction %d for robot '%s'", direction, robot_id
            )
            return

        # Chain consecutive clicks: use the previous goal as base whenever it
        # is recent OR the robot is still executing a task (Nav2 hasn't
        # finished the previous goal). This makes rapid taps accumulate
        # instead of fighting Nav2 in-flight.
        chain_window_s = 10.0
        last = self._open_teleop_last_goal.get(robot_id)
        now = time.monotonic()
        state = backend.snapshot()
        still_executing = state.current_task is not None
        if last is not None and (still_executing or (now - last[0]) < chain_window_s):
            base_x, base_y, base_yaw = last[1], last[2], last[3]
        else:
            base_x, base_y, base_yaw = state.pose.x, state.pose.y, state.pose.yaw

        cos_yaw = math.cos(base_yaw)
        sin_yaw = math.sin(base_yaw)
        map_x = base_x + cos_yaw * dx - sin_yaw * dy
        map_y = base_y + sin_yaw * dx + cos_yaw * dy
        map_yaw = math.atan2(
            math.sin(base_yaw + dtheta),
            math.cos(base_yaw + dtheta),
        )

        self._open_teleop_last_goal[robot_id] = (now, map_x, map_y, map_yaw)

        self._logger.info(
            "Open teleop %s for robot '%s' -> map pose=(%.3f, %.3f, %.3f rad)",
            label,
            robot_id,
            map_x,
            map_y,
            map_yaw,
        )

        try:
            backend.dispatch_to_pose(map_x, map_y, map_yaw, label=label)
        except RuntimeError as exc:
            self._logger.error(
                "Open teleop dispatch failed for robot '%s': %s", robot_id, exc
            )

    def _handle_precision_teleop_path(self, robot_id: str, payload: bytes) -> None:
        """Parse a Nav2DPathMessage from InOrbit Precision Teleop and forward
        the final pose to the backend as a NavigateToPose goal."""

        backend = self._backends.get(robot_id)
        if backend is None:
            self._logger.warning(
                "Received precision teleop path for unknown robot '%s'", robot_id
            )
            return

        msg = Nav2DPathMessage()
        try:
            msg.ParseFromString(payload)
        except Exception as exc:
            self._logger.error(
                "Could not parse Nav2DPathMessage for robot '%s': %s",
                robot_id,
                exc,
            )
            return

        if not msg.waypoints:
            self._logger.info(
                "Precision teleop path with no waypoints for robot '%s'", robot_id
            )
            return

        target = msg.waypoints[-1]
        dx = float(target.x)
        dy = float(target.y)
        dtheta = float(target.theta)
        frame = target.frame or msg.frame

        if frame == Nav2DWaypointFrame.ROBOT:
            state = backend.snapshot()
            cos_yaw = math.cos(state.pose.yaw)
            sin_yaw = math.sin(state.pose.yaw)
            map_x = state.pose.x + cos_yaw * dx - sin_yaw * dy
            map_y = state.pose.y + sin_yaw * dx + cos_yaw * dy
            map_yaw = state.pose.yaw + dtheta
        elif frame == Nav2DWaypointFrame.MAP:
            map_x, map_y, map_yaw = dx, dy, dtheta
        else:
            self._logger.warning(
                "Precision teleop path uses unsupported frame=%s for robot '%s'",
                frame,
                robot_id,
            )
            return

        # Normalize yaw to (-pi, pi]
        map_yaw = math.atan2(math.sin(map_yaw), math.cos(map_yaw))

        self._logger.info(
            "Precision teleop for robot '%s': delta=(%.3f, %.3f, %.3f rad) frame=%s "
            "-> map pose=(%.3f, %.3f, %.3f rad)",
            robot_id,
            dx,
            dy,
            dtheta,
            frame,
            map_x,
            map_y,
            map_yaw,
        )

        try:
            backend.dispatch_to_pose(map_x, map_y, map_yaw, label="Precision Teleop")
        except RuntimeError as exc:
            self._logger.error(
                "Precision teleop dispatch failed for robot '%s': %s", robot_id, exc
            )

    def _register_ros_camera_if_needed(self, robot_id: str) -> None:
        ros2_config = self.config.connector_config.ros2
        if (
            self.config.connector_config.backend != TurtlebotBackendType.ROS2_GAZEBO
            or not ros2_config.camera_enabled
            or robot_id in self._registered_ros_cameras
        ):
            return

        camera = Ros2ImageTopicCamera(
            topic=ros2_config.camera_topic,
            camera_id=ros2_config.camera_id,
            rate=ros2_config.camera_rate_hz,
            scaling=ros2_config.camera_scaling,
            quality=ros2_config.camera_quality,
            node_name=f"turtlebot_connector_camera_{robot_id.replace('-', '_')}",
            use_sim_time=ros2_config.use_sim_time,
        )
        session = self._get_robot_session(robot_id)
        session.register_camera(ros2_config.camera_id, camera)

        original_publish_camera_frame = session.publish_camera_frame
        _frame_count = [0]

        def instrumented_publish_camera_frame(camera_id, image, width, height, ts):
            _frame_count[0] += 1
            if _frame_count[0] == 1 or _frame_count[0] % 100 == 0:
                self._logger.info(
                    "MQTT publish_camera_frame robot='%s' camera_id='%s' w=%d h=%d bytes=%d count=%d",
                    robot_id,
                    camera_id,
                    width,
                    height,
                    len(image) if image else 0,
                    _frame_count[0],
                )
            return original_publish_camera_frame(camera_id, image, width, height, ts)

        session.publish_camera_frame = instrumented_publish_camera_frame

        self._registered_ros_cameras.add(robot_id)
        self._logger.info(
            "Registered ROS camera '%s' for robot '%s' from topic '%s'",
            ros2_config.camera_id,
            robot_id,
            ros2_config.camera_topic,
        )

    def _publish_robot_data(self, robot_id: str, state: TurtlebotState) -> None:
        self.publish_robot_pose(
            robot_id,
            x=state.pose.x,
            y=state.pose.y,
            yaw=state.pose.yaw,
            frame_id="map",
        )
        self.publish_robot_odometry(robot_id, linear_speed=state.speed)

        robot_cfg = self._robot_configs.get(robot_id)
        kv: dict = {
            "connector_version": connector_version,
            "provider": state.provider_name,
            "robot_name": state.name,
            "robot_model": robot_cfg.robot_model if robot_cfg else "TurtleBot3 Waffle Pi",
            "online_status": state.online,
            "operational_state": state.operational_state.value,
            "battery": state.battery,
            "battery_percent": int(state.battery * 100),
            "current_task": state.current_task.task_id if state.current_task else "",
            "current_waypoint": state.current_task.waypoint if state.current_task else "",
            "mission_status": self._compute_mission_status(state),
        }

        task = state.current_task or state.last_task
        if task:
            kv["task_id"] = task.task_id
            kv["task_label"] = task.label
            kv["task_state"] = task.state.value
            kv["task_completed_percent"] = task.completed_percent
            kv["mission_tracking"] = self._build_mission_report(task)

        cleaning = self.config.connector_config.cleaning_demo
        if cleaning.enabled:
            kv["clean_water_tank"] = cleaning.clean_water_tank
            kv["dirty_water_tank"] = cleaning.dirty_water_tank
            kv["detergent_tank"] = cleaning.detergent_tank
            kv["cleaning_mode"] = cleaning.cleaning_mode
            kv["brush_status"] = cleaning.brush_status
            kv["vacuum_status"] = cleaning.vacuum_status
            kv["clean_faulting"] = cleaning.clean_faulting
            kv["clean_emergency_stop"] = cleaning.clean_emergency_stop
            kv["cleaned_area_m2"] = cleaning.cleaned_area_m2

        self.publish_robot_key_values(robot_id, **kv)

    def _compute_mission_status(self, state: TurtlebotState) -> str:
        if not state.online or state.operational_state == OperationalState.ERROR:
            return "Error"
        if state.current_task:
            return "Mission"
        if state.operational_state == OperationalState.CHARGING:
            return "Charging"
        return "Idle"

    def _build_mission_report(self, task: TurtlebotTask) -> dict:
        in_progress = task.state == TaskState.EXECUTING
        mission_state = {
            TaskState.EXECUTING: "Executing",
            TaskState.COMPLETED: "Completed",
            TaskState.CANCELED: "Canceled",
            TaskState.ERROR: "Aborted",
        }[task.state]
        report: dict = {
            "missionId": task.task_id,
            "inProgress": in_progress,
            "state": mission_state,
            "label": task.label,
            "startTs": task.start_ts,
            "data": {"waypoint": task.waypoint},
            "status": "OK",
            "tasks": [{"taskId": "0", "label": task.label}],
            "completedPercent": task.completed_percent,
        }
        if in_progress:
            report["currentTaskId"] = "0"
        elif task.end_ts is not None:
            report["endTs"] = task.end_ts
        return report

    @override
    async def fetch_robot_map(
        self, robot_id: str, frame_id: str
    ) -> MapConfigTemp | None:
        backend = self._backends.get(robot_id)
        if not isinstance(backend, Ros2GazeboTurtlebotClient):
            return None

        grid = backend.get_latest_map()
        if grid is None:
            self._logger.info("No /map message received yet for robot '%s'", robot_id)
            return None

        try:
            from PIL import Image

            info = grid.info
            width = info.width
            height = info.height
            data = grid.data

            # OccupancyGrid: -1=unknown, 0=free, 100=occupied
            # Greyscale: free=255 (white), occupied=0 (black), unknown=205 (grey)
            pixels = bytearray(height * width)
            for i, v in enumerate(data):
                if v == 0:
                    pixels[i] = 255
                elif v == 100:
                    pixels[i] = 0
                else:
                    pixels[i] = 205

            img = Image.frombytes("L", (width, height), bytes(pixels))
            # ROS origin is bottom-left; PNG origin is top-left
            img = img.transpose(Image.FLIP_TOP_BOTTOM)

            buf = io.BytesIO()
            img.save(buf, format="PNG")
            image_bytes = buf.getvalue()

            origin = info.origin.position
            return MapConfigTemp(
                image=image_bytes,
                map_id=frame_id,
                map_label="turtlebot_office_map",
                origin_x=float(origin.x),
                origin_y=float(origin.y),
                resolution=float(info.resolution),
            )
        except Exception as exc:
            self._logger.error("Failed to convert /map to PNG for robot '%s': %s", robot_id, exc)
            return None

    @override
    def _is_fleet_robot_online(self, robot_id: str) -> bool:
        backend = self._backends.get(robot_id)
        return backend.online if backend else False

    @override
    async def _inorbit_robot_command_handler(
        self, robot_id: str, command_name: str, args: list, options: dict
    ) -> None:
        backend = self._backends.get(robot_id)
        if backend is None:
            raise CommandFailure(
                execution_status_details=f"Unknown robot: {robot_id}",
                stderr=f"Robot '{robot_id}' is not configured",
            )

        result_fn = options["result_function"]

        # InOrbit "Waypoint Teleop" — operator drops a pin on the map. The SDK
        # passes args = [{"x": "...", "y": "...", "theta": "..."}].
        if command_name == COMMAND_NAV_GOAL:
            self._logger.info("Received navGoal for robot '%s': %s", robot_id, args)
            try:
                pose = args[0]
                x = float(pose["x"])
                y = float(pose["y"])
                yaw = float(pose["theta"])
                backend.dispatch_to_pose(x, y, yaw, label="Waypoint Teleop")
            except (KeyError, ValueError, TypeError, IndexError) as exc:
                raise CommandFailure(
                    execution_status_details=f"Bad navGoal payload: {exc}",
                    stderr=str(exc),
                ) from exc
            except RuntimeError as exc:
                raise CommandFailure(
                    execution_status_details=str(exc),
                    stderr=str(exc),
                ) from exc
            result_fn(CommandResultCode.SUCCESS)
            return

        # InOrbit "Relocalize" — operator drags the avatar on the map. Same
        # payload shape as navGoal.
        if command_name == COMMAND_INITIAL_POSE:
            self._logger.info("Received initialPose for robot '%s': %s", robot_id, args)
            try:
                pose = args[0]
                x = float(pose["x"])
                y = float(pose["y"])
                yaw = float(pose["theta"])
                backend.relocalize(x, y, yaw)
            except (KeyError, ValueError, TypeError, IndexError) as exc:
                raise CommandFailure(
                    execution_status_details=f"Bad initialPose payload: {exc}",
                    stderr=str(exc),
                ) from exc
            result_fn(CommandResultCode.SUCCESS)
            return

        if command_name != COMMAND_CUSTOM_COMMAND:
            # Log unhandled command names so we can confirm whether the
            # InOrbit "Open Teleop" d-pad reaches us at all.
            self._logger.info(
                "Unhandled InOrbit command for robot '%s': name=%s args=%s",
                robot_id,
                command_name,
                args,
            )
            return

        script_name, script_args = parse_custom_command_args(args)

        try:
            match script_name:
                case CustomScripts.GO_TO:
                    cmd = GoToCommand.model_validate(script_args)
                    backend.dispatch_to(cmd.waypoint, task_id=cmd.task_id)
                case CustomScripts.DISPATCH:
                    cmd = DispatchCommand.model_validate(script_args)
                    backend.dispatch_to(cmd.waypoint, task_id=cmd.task_id, label=cmd.label)
                case CustomScripts.CANCEL_TASK:
                    cmd = CancelTaskCommand.model_validate(script_args)
                    backend.cancel_task(cmd.task_id)
                case _:
                    raise CommandFailure(
                        execution_status_details=f"Unknown command: {script_name}",
                        stderr=f"Command '{script_name}' is not supported",
                    )
        except UnknownWaypointError as exc:
            raise CommandFailure(
                execution_status_details=str(exc),
                stderr=str(exc),
            ) from exc
        except NoActiveTaskError as exc:
            raise CommandFailure(
                execution_status_details=str(exc),
                stderr=str(exc),
            ) from exc
        except RuntimeError as exc:
            raise CommandFailure(
                execution_status_details=str(exc),
                stderr=str(exc),
            ) from exc

        result_fn(CommandResultCode.SUCCESS)
