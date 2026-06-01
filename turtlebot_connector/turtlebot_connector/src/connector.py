# SPDX-FileCopyrightText: 2026 Deliverance Enterprises
#
# SPDX-License-Identifier: MIT

"""InOrbit FleetConnector implementation for TurtleBot backends."""

from __future__ import annotations

import io
from types import MethodType
import time
from typing_extensions import override

from inorbit_connector.commands import CommandFailure, CommandResultCode, parse_custom_command_args
from inorbit_connector.connector import FleetConnector
from inorbit_connector.models import MapConfigTemp
from inorbit_edge.robot import COMMAND_CUSTOM_COMMAND

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
from turtlebot_connector.src.config.models import TurtlebotBackendType, TurtlebotConnectorConfig
from turtlebot_connector.src.simulator import FakeTurtlebotSimulator


class TurtlebotConnector(FleetConnector):
    """Demo Edge connector that publishes fake TurtleBot telemetry."""

    def __init__(self, config: TurtlebotConnectorConfig) -> None:
        super().__init__(config, publish_connector_system_stats=True)
        self._backends: dict[str, TurtlebotBackend] = {}
        self._registered_ros_cameras: set[str] = set()
        self._instrumented_sessions: set[str] = set()
        for robot in config.fleet:
            self._backends[robot.robot_id] = self._build_backend(robot)
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
        original_handle_in_cmd = getattr(session, "_handle_in_cmd", None)
        if original_handle_in_cmd is None:
            return

        def instrumented_handle_in_cmd(session_self, msg):
            try:
                decoded = msg.decode("utf-8")
            except Exception:
                decoded = repr(msg)
            self._logger.info(
                "RobotSession in_cmd for robot '%s': %s",
                robot_id,
                decoded,
            )
            return original_handle_in_cmd(msg)

        session._handle_in_cmd = MethodType(instrumented_handle_in_cmd, session)
        self._instrumented_sessions.add(robot_id)
        self._logger.info(
            "Installed RobotSession in_cmd instrumentation for robot '%s'",
            robot_id,
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

        kv: dict = {
            "connector_version": connector_version,
            "provider": state.provider_name,
            "robot_name": state.name,
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
        if command_name != COMMAND_CUSTOM_COMMAND:
            return

        backend = self._backends.get(robot_id)
        if backend is None:
            raise CommandFailure(
                execution_status_details=f"Unknown robot: {robot_id}",
                stderr=f"Robot '{robot_id}' is not configured",
            )

        result_fn = options["result_function"]
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
