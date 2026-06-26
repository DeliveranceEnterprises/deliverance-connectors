# SPDX-FileCopyrightText: 2026 Deliverance Enterprises
#
# SPDX-License-Identifier: MIT

"""AutoXing Cloud Fleet Connector for InOrbit."""

import json
import time
from typing import override

from inorbit_connector.commands import CommandFailure, CommandResultCode, parse_custom_command_args
from inorbit_connector.connector import FleetConnector
from inorbit_connector.models import MapConfigTemp
from inorbit_edge.robot import COMMAND_CUSTOM_COMMAND

from autoxing_cloud_connector import __version__ as connector_version
from autoxing_cloud_connector.src.api.client import AutoxingAPIClient
from autoxing_cloud_connector.src.api.data_poller import DataPoller
from autoxing_cloud_connector.src.api.models import RobotState
from autoxing_cloud_connector.src.commands import (
    CancelTaskCommand,
    CustomScripts,
    ExecuteTaskCommand,
    NavigateToPoiCommand,
)
from autoxing_cloud_connector.src.config.models import AutoxingFleetConnectorConfig, AutoxingRobotConfig


class AutoxingCloudConnector(FleetConnector):
    """InOrbit Fleet Connector for the AutoXing Cloud Platform.

    Polls the AutoXing REST API for robot state (pose, battery, status flags) and
    dispatches navigation/task commands. No WebSocket — pure REST polling.
    """

    def __init__(self, config: AutoxingFleetConnectorConfig) -> None:
        super().__init__(config, publish_connector_system_stats=True)

        self._robot_id_to_fleet_id: dict[str, str] = {
            r.robot_id: r.fleet_robot_id for r in config.fleet
        }
        self._robot_configs: dict[str, AutoxingRobotConfig] = {
            r.robot_id: r for r in config.fleet
        }
        self._fleet_id_to_robot_id: dict[str, str] = {
            r.fleet_robot_id: r.robot_id for r in config.fleet
        }
        self._robot_states: dict[str, RobotState] = {
            r.robot_id: RobotState() for r in config.fleet
        }
        self._area_names: dict[str, str] = {}  # areaId → name cache

        self._api_client: AutoxingAPIClient | None = None
        self._data_poller: DataPoller | None = None

    @property
    def _autoxing_cfg(self):
        return self.config.connector_config

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @override
    async def _connect(self) -> None:
        cfg = self._autoxing_cfg
        self._api_client = AutoxingAPIClient(
            base_url=cfg.base_url,
            login_name=cfg.login_name,
            password=cfg.password,
            business_id=cfg.business_id,
            login_appcode=cfg.login_appcode,
            api_appcode=cfg.api_appcode,
            verify_ssl=cfg.verify_ssl,
            timeout=cfg.request_timeout,
        )
        await self._api_client.login()

        # Pre-cache area names
        await self._refresh_area_names()

        self._data_poller = DataPoller(
            client=self._api_client,
            robot_states=self._robot_states,
            robot_id_to_fleet_id=self._robot_id_to_fleet_id,
            fleet_id_to_robot_id=self._fleet_id_to_robot_id,
            update_freq=self.config.update_freq,
        )
        # Pre-populate state before the InOrbit session connects so the SDK
        # never publishes a (0, 0) pose artefact on startup.
        await self._data_poller.poll_once()
        self._data_poller.start()
        self._logger.info("Connected to AutoXing Cloud at %s", cfg.base_url)

    @override
    async def _disconnect(self) -> None:
        if self._data_poller:
            await self._data_poller.stop()
        if self._api_client:
            await self._api_client.close()

    async def _refresh_area_names(self) -> None:
        areas = await self._api_client.get_area_list()
        for area in areas:
            if area.get("id") and area.get("name"):
                self._area_names[area["id"]] = area["name"]

    # ------------------------------------------------------------------
    # Execution loop
    # ------------------------------------------------------------------

    def _instrument_robot_session_if_needed(self, robot_id: str) -> None:
        if robot_id in getattr(self, "_instrumented_sessions", set()):
            return
        if not hasattr(self, "_instrumented_sessions"):
            self._instrumented_sessions: set[str] = set()
        session = self._get_robot_session(robot_id)
        robot_cfg = self._robot_configs.get(robot_id)
        if robot_cfg and robot_cfg.name and session.robot_name != robot_cfg.name:
            session.robot_name = robot_cfg.name
            session._send_robot_status(online=True)
            self._logger.info(
                "Set display name '%s' for robot '%s'", robot_cfg.name, robot_id
            )
        self._instrumented_sessions.add(robot_id)

    @override
    async def _execution_loop(self) -> None:
        for robot_id in self.robot_ids:
            self._instrument_robot_session_if_needed(robot_id)
            self._publish_robot_data(robot_id, self._robot_states[robot_id])

    def _publish_robot_data(self, robot_id: str, state: RobotState) -> None:
        if not state.has_data:
            return
        if state.x is not None and state.y is not None and state.yaw is not None:
            self.publish_robot_pose(
                robot_id,
                x=state.x,
                y=state.y,
                yaw=state.yaw,
                frame_id=state.area_id or "map",
            )
        if state.speed is not None:
            self.publish_robot_odometry(robot_id, linear_speed=state.speed)

        kv: dict = {
            "connector_version": connector_version,
            "online_status": state.online,
            "api_connected": state.api_connected,
        }

        if state.battery is not None:
            kv["battery"] = state.battery / 100.0
            kv["battery_percent"] = int(state.battery)
        if state.is_charging is not None:
            kv["is_charging"] = state.is_charging
        if state.is_go_home is not None:
            kv["is_go_home"] = state.is_go_home
        if state.is_emergency_stop is not None:
            kv["is_emergency_stop"] = state.is_emergency_stop
        if state.is_manual_mode is not None:
            kv["is_manual_mode"] = state.is_manual_mode
        if state.is_remote_mode is not None:
            kv["is_remote_mode"] = state.is_remote_mode
        if state.has_obstruction is not None:
            kv["has_obstruction"] = state.has_obstruction
        if state.loc_quality is not None:
            kv["loc_quality"] = state.loc_quality
        if state.errors:
            kv["errors"] = json.dumps(state.errors)
        if state.area_id:
            kv["current_area_id"] = state.area_id
            area_name = self._area_names.get(state.area_id) or state.area_name
            if area_name:
                kv["current_area_name"] = area_name
        if state.task_id:
            kv["task_id"] = state.task_id
        if state.task_is_finish is not None:
            kv["task_is_finish"] = state.task_is_finish
        if state.task_is_cancel is not None:
            kv["task_is_cancel"] = state.task_is_cancel

        kv["mission_status"] = self._compute_mission_status(state)

        if state.task_id and state._task_ready:
            kv["mission_tracking"] = self._build_mission_report(state)

        self.publish_robot_key_values(robot_id, **kv)

        # Publish the terminal mission_tracking exactly once, then stop
        # republishing it. InOrbit only finalises a mission into kpis/objects
        # once it stops receiving updates — a mission re-sent every cycle never
        # "settles", so the LAST task of a burst would otherwise stay unindexed
        # until the next task starts. Clearing here lets it settle immediately.
        if state.task_id and (state.task_is_finish or state.task_is_cancel):
            state.task_id = None
            state.task_name = None
            state.task_start_ts = None

    _MISSION_STATE: dict[str, str] = {
        "executing": "Executing",
        "completed": "Completed",
        "canceled": "Canceled",
    }

    def _compute_mission_status(self, state: RobotState) -> str:
        if not state.api_connected:
            return "Error"
        if state.is_emergency_stop:
            return "Error"
        if state.is_manual_mode:
            return "Manual"
        if state.task_id and not state.task_is_finish and not state.task_is_cancel:
            return "Mission"
        if state.is_charging or state.is_go_home:
            return "Charging"
        return "Idle"

    def _build_mission_report(self, state: RobotState) -> dict:
        finished = bool(state.task_is_finish)
        canceled = bool(state.task_is_cancel)
        in_progress = not finished and not canceled
        if canceled:
            mission_state = "Canceled"
        elif finished:
            mission_state = "Completed"
        else:
            mission_state = "Executing"

        start_ts = state.task_start_ts or int(time.time() * 1000)
        mission_id = f"{state.task_id}_{start_ts}" if state.task_id else None
        # Execution metrics from taskObj ride along in mission_tracking.data;
        # InOrbit prefixes them with "data_" in kpis/objects, where the
        # Deliverance mapper rebuilds them into the tasks.report.
        data: dict = {"group": "Delivery"}
        if state.task_mileage is not None:
            data["mileage"] = state.task_mileage
        if state.task_total_dis is not None:
            data["total_distance"] = state.task_total_dis
        if state.task_duration is not None:
            data["duration_s"] = state.task_duration
        if state.task_type is not None:
            data["task_type"] = state.task_type
        if state.task_id:
            data["autoxing_task_id"] = state.task_id
        # Route fields from task detail (GET /task/v1.1/{taskId})
        if state.task_target_name:
            data["target_name"] = state.task_target_name
        if state.task_target_x is not None:
            data["target_x"] = state.task_target_x
        if state.task_target_y is not None:
            data["target_y"] = state.task_target_y
        if state.task_back_name:
            data["back_name"] = state.task_back_name
        if state.task_back_x is not None:
            data["back_x"] = state.task_back_x
        if state.task_back_y is not None:
            data["back_y"] = state.task_back_y
        if state.task_origin_x is not None:
            data["origin_x"] = state.task_origin_x
        if state.task_origin_y is not None:
            data["origin_y"] = state.task_origin_y
        if state.task_area_id:
            data["area_id"] = state.task_area_id
        if state.task_building_id:
            data["building_id"] = state.task_building_id
        report: dict = {
            "missionId": mission_id,
            "inProgress": in_progress,
            "state": mission_state,
            "label": state.task_target_name or state.task_name or state.task_id,
            "startTs": start_ts,
            "data": data,
            "status": "OK",
            "tasks": [{"taskId": "0", "label": state.task_name or "Task"}],
            "completedPercent": 1.0 if finished else 0.0,
        }
        if in_progress:
            report["currentTaskId"] = "0"
        else:
            report["endTs"] = int(time.time() * 1000)
        return report

    # ------------------------------------------------------------------
    # Map fetching
    # ------------------------------------------------------------------

    @override
    async def fetch_robot_map(self, robot_id: str, frame_id: str) -> MapConfigTemp | None:
        if self._api_client is None:
            return None
        robot_cfg = self._robot_configs.get(robot_id)
        area_map_cfg = (robot_cfg.area_map_config.get(frame_id) or {}) if robot_cfg else {}

        image_bytes = await self._api_client.get_map_image(frame_id)
        if not image_bytes:
            return None
        try:
            return MapConfigTemp(
                image=image_bytes,
                map_id=frame_id,
                map_label=self._area_names.get(frame_id, frame_id),
                origin_x=float(area_map_cfg.get("origin_x", 0.0)),
                origin_y=float(area_map_cfg.get("origin_y", 0.0)),
                resolution=float(area_map_cfg.get("resolution", 0.05)),
            )
        except Exception as exc:
            self._logger.error("Map fetch failed for robot %s area %s: %s", robot_id, frame_id, exc)
            return None

    # ------------------------------------------------------------------
    # Online check
    # ------------------------------------------------------------------

    @override
    def _is_fleet_robot_online(self, robot_id: str) -> bool:
        state = self._robot_states.get(robot_id)
        return state.online if state else False

    # ------------------------------------------------------------------
    # Command handler
    # ------------------------------------------------------------------

    @override
    async def _inorbit_robot_command_handler(
        self, robot_id: str, command_name: str, args: list, options: dict
    ) -> None:
        if command_name != COMMAND_CUSTOM_COMMAND:
            return

        if self._api_client is None:
            raise CommandFailure(
                execution_status_details="API client not connected",
                stderr="Connector is not yet connected to the AutoXing API",
            )

        result_fn = options["result_function"]
        script_name, script_args = parse_custom_command_args(args)
        fleet_id = self._robot_id_to_fleet_id[robot_id]
        state = self._robot_states[robot_id]

        match script_name:
            case CustomScripts.NAVIGATE_TO_POI:
                cmd = NavigateToPoiCommand.model_validate(script_args)
                poi = await self._api_client._get(f"/map/v1.1/poi/{cmd.poi_id}")
                if not poi:
                    raise CommandFailure(
                        execution_status_details=f"POI {cmd.poi_id} not found",
                        stderr=f"Could not fetch POI {cmd.poi_id}",
                    )
                coords = poi.get("coordinate") or [0, 0]
                area_id = poi.get("areaId") or state.area_id or ""
                task_payload = {
                    "name": f"Navigate to {poi.get('name', cmd.poi_id)}",
                    "robotId": fleet_id,
                    "taskType": cmd.task_type,
                    "runType": cmd.run_type,
                    "taskPts": [{
                        "areaId": area_id,
                        "x": coords[0],
                        "y": coords[1],
                        "yaw": poi.get("yaw", 0),
                        "type": poi.get("type", -1),
                        "stopRadius": 1.0,
                        "ext": {"name": poi.get("name", cmd.poi_id), "id": cmd.poi_id},
                    }],
                }
                task_id = await self._api_client.create_task(task_payload)
                if not task_id:
                    raise CommandFailure(
                        execution_status_details="Task creation returned no ID",
                        stderr="AutoXing API did not return a task ID",
                    )
                await self._api_client.execute_task(task_id)
                state.task_id = task_id
                state.task_name = task_payload["name"]
                state.task_is_finish = False
                state.task_is_cancel = False
                state.task_start_ts = int(time.time() * 1000)

            case CustomScripts.GO_HOME:
                task_payload = {
                    "name": "Return to charger",
                    "robotId": fleet_id,
                    "taskType": 1,   # Return to charging station
                    "runType": 25,   # Charging station
                    "taskPts": [],
                }
                task_id = await self._api_client.create_task(task_payload)
                if not task_id:
                    raise CommandFailure(
                        execution_status_details="Task creation returned no ID",
                        stderr="AutoXing API did not return a task ID for go_home",
                    )
                await self._api_client.execute_task(task_id)
                state.task_id = task_id
                state.task_name = "Return to charger"
                state.task_is_finish = False
                state.task_is_cancel = False
                state.task_start_ts = int(time.time() * 1000)

            case CustomScripts.CANCEL_TASK:
                cmd = CancelTaskCommand.model_validate(script_args)
                task_id = cmd.task_id or state.task_id
                if not task_id:
                    raise CommandFailure(
                        execution_status_details="No active task to cancel",
                        stderr="No task_id provided and no current task in state",
                    )
                await self._api_client.cancel_task(task_id)
                state.task_is_cancel = True

            case CustomScripts.EXECUTE_TASK:
                cmd = ExecuteTaskCommand.model_validate(script_args)
                await self._api_client.execute_task(cmd.task_id)
                state.task_id = cmd.task_id
                state.task_is_finish = False
                state.task_is_cancel = False
                state.task_start_ts = int(time.time() * 1000)

            case _:
                raise CommandFailure(
                    execution_status_details=f"Unknown command: {script_name}",
                    stderr=f"Command '{script_name}' is not supported",
                )

        result_fn(CommandResultCode.SUCCESS)
