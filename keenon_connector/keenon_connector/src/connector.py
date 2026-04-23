# SPDX-FileCopyrightText: 2026 Deliverance Enterprises
#
# SPDX-License-Identifier: MIT

"""Main KeenonConnector implementation."""

import json
import logging
import time
from typing import override

from inorbit_connector.commands import CommandFailure, CommandResultCode, parse_custom_command_args
from inorbit_connector.connector import FleetConnector
from inorbit_connector.models import MapConfigTemp
from inorbit_edge.robot import COMMAND_CUSTOM_COMMAND

from keenon_connector import __version__ as connector_version
from keenon_connector.src.api.client import KeenonAPIClient
from keenon_connector.src.api.data_poller import DataPoller
from keenon_connector.src.api.models import (
    CLEAN_MAIN_STATE_MAP,
    CLEAN_SUB_STATE_MAP,
    KEENON_MAP_RESOLUTION,
    ONLINE_TYPE_MAP,
    ROBOT_STATE_MAP,
    TANK_STATE_MAP,
    TASK_STATUS_MAP,
    WATER_TANK_STATE_MAP,
    RobotState,
    keenon_map_origin,
    png_dimensions,
)
from keenon_connector.src.api.webhook_receiver import KeenonWebhookReceiver
from keenon_connector.src.commands import (
    CabinControlCommand,
    CallToPointCommand,
    CancelTaskCommand,
    CleanTemporaryTaskCommand,
    CustomScripts,
)
from keenon_connector.src.config.models import KeenonConnectorConfig, KeenonRobotConfig

logger = logging.getLogger(__name__)


class KeenonConnector(FleetConnector):
    """InOrbit Fleet Connector for the Keenon Cloud API.

    Manages a fleet of Keenon robots (T-series food delivery, W-series hotel,
    C-series cleaning) by polling the Keenon REST API and optionally receiving
    real-time push callbacks via a built-in webhook server.
    """

    def __init__(self, config: KeenonConnectorConfig) -> None:
        super().__init__(config, publish_connector_system_stats=True)

        self._robot_id_to_fleet_id: dict[str, str] = {
            r.robot_id: r.fleet_robot_id for r in config.fleet
        }
        self._robot_configs: dict[str, KeenonRobotConfig] = {
            r.robot_id: r for r in config.fleet
        }
        self._fleet_sn_to_robot_id: dict[str, str] = {
            r.fleet_robot_id: r.robot_id for r in config.fleet
        }
        self._robot_states: dict[str, RobotState] = {
            r.robot_id: RobotState() for r in config.fleet
        }

        self._api_client: KeenonAPIClient | None = None
        self._data_poller: DataPoller | None = None
        self._webhook_receiver: KeenonWebhookReceiver | None = None

    @property
    def _keenon_cfg(self):
        return self.config.connector_config

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @override
    async def _connect(self) -> None:
        cfg = self._keenon_cfg
        self._api_client = KeenonAPIClient(
            api_domain=cfg.api_domain,
            client_id=cfg.client_id,
            client_secret=cfg.client_secret,
            verify_ssl=cfg.verify_ssl,
            timeout=cfg.request_timeout,
        )

        self._data_poller = DataPoller(
            client=self._api_client,
            robot_states=self._robot_states,
            fleet_id_to_store={
                r.fleet_robot_id: r.store_id for r in self.config.fleet
            },
            robot_id_to_fleet_id=self._robot_id_to_fleet_id,
            update_freq=self.config.update_freq,
        )
        self._data_poller.start()

        if cfg.webhook_port is not None:
            self._webhook_receiver = KeenonWebhookReceiver(
                host=cfg.webhook_host,
                port=cfg.webhook_port,
                robot_states=self._robot_states,
                fleet_sn_to_robot_id=self._fleet_sn_to_robot_id,
            )
            await self._webhook_receiver.start()

        self._logger.info("Connected to Keenon API: %s", cfg.api_domain)

    @override
    async def _disconnect(self) -> None:
        if self._data_poller:
            await self._data_poller.stop()
        if self._webhook_receiver:
            await self._webhook_receiver.stop()
        if self._api_client:
            await self._api_client.close()

    # ------------------------------------------------------------------
    # Execution loop — publish cached state to InOrbit
    # ------------------------------------------------------------------

    @override
    async def _execution_loop(self) -> None:
        for robot_id in self.robot_ids:
            self._publish_robot_data(robot_id, self._robot_states[robot_id])

    def _publish_robot_data(self, robot_id: str, state: RobotState) -> None:
        if state.x is not None and state.y is not None and state.yaw is not None:
            if state.scene_code:
                # Full path: publish_robot_pose handles map fetching.
                self.publish_robot_pose(
                    robot_id,
                    x=state.x,
                    y=state.y,
                    yaw=state.yaw,
                    frame_id=state.scene_code,
                )
            else:
                # No scene assigned yet — publish pose directly to avoid the
                # map-fetch loop that publish_robot_pose would trigger.
                self._get_robot_session(robot_id).publish_pose(
                    state.x, state.y, state.yaw
                )

        kv: dict = {"connector_version": connector_version}

        if state.battery is not None:
            kv["battery"] = state.battery / 100.0
            kv["battery_percent"] = state.battery / 100.0
        if state.online_status is not None:
            kv["online_status"] = state.online_status
        if state.charge_status is not None:
            kv["charge_status"] = "charging" if state.charge_status == 1 else "discharging"
        if state.can_be_called is not None:
            kv["can_be_called"] = state.can_be_called
        if state.robot_state is not None:
            kv["robot_state"] = ROBOT_STATE_MAP.get(state.robot_state, str(state.robot_state))
        if state.scene_name:
            kv["current_scene"] = state.scene_name
        if state.task_no:
            kv["task_no"] = state.task_no
        if state.task_status is not None:
            kv["task_status"] = TASK_STATUS_MAP.get(state.task_status, str(state.task_status))
        if state.task_no:
            kv["mission_tracking"] = self._build_mission_report(state)
        kv["mission_status"] = self._compute_mission_status(state)
        if state.robot_model:
            kv["robot_model"] = state.robot_model
        if state.app_version:
            kv["app_version"] = state.app_version
        if state.online_type is not None:
            kv["online_type"] = ONLINE_TYPE_MAP.get(state.online_type, str(state.online_type))
        if state.elevator_status is not None:
            kv["elevator_status"] = state.elevator_status == 1
        kv["api_connected"] = state.api_connected

        if state.robot_type == "clean":
            if state.clean_main_state is not None:
                kv["clean_main_state"] = CLEAN_MAIN_STATE_MAP.get(
                    state.clean_main_state, str(state.clean_main_state)
                )
            if state.clean_sub_state is not None:
                kv["clean_sub_state"] = CLEAN_SUB_STATE_MAP.get(
                    state.clean_sub_state, str(state.clean_sub_state)
                )
            if state.clean_faulting is not None:
                kv["clean_faulting"] = state.clean_faulting
            if state.clean_scram is not None:
                kv["clean_emergency_stop"] = state.clean_scram
            if state.clean_navigating is not None:
                kv["clean_navigating"] = state.clean_navigating
            if state.clean_bilge_tank is not None:
                kv["clean_bilge_tank"] = TANK_STATE_MAP.get(
                    state.clean_bilge_tank, str(state.clean_bilge_tank)
                )
            if state.clean_water_tank is not None:
                kv["clean_water_tank"] = WATER_TANK_STATE_MAP.get(
                    state.clean_water_tank, str(state.clean_water_tank)
                )

        self.publish_robot_key_values(robot_id, **kv)

    # task_status int → mode string for the Modes & Tags widget
    _MODE_FROM_TASK_STATUS: dict[int, str] = {
        1: "Mission",   # queued
        2: "Mission",   # calling
        3: "Mission",   # in_progress
        4: "Idle",      # completed
        5: "Idle",      # cancelled
        6: "Mission",   # target_reached
        7: "Mission",   # waiting
        0: "Error",     # failed
    }

    def _compute_mission_status(self, state: "RobotState") -> str:
        """Return the mode string published as the mission_status key-value.

        InOrbit reads this value (via the account-level mission_status
        DataSourceDefinition) to display the current mode in the Modes widget.
        """
        if not state.api_connected:
            return "Error"
        if state.charge_status == 1:
            return "Charging"
        if state.task_no and state.task_status is not None:
            return self._MODE_FROM_TASK_STATUS.get(state.task_status, "Mission")
        return "Idle"

    # Keenon task_status (int) → InOrbit mission state string
    _MISSION_STATE: dict[int, str] = {
        1: "Executing",   # queued
        2: "Executing",   # calling
        3: "Executing",   # in_progress
        4: "Completed",   # completed
        5: "Canceled",    # cancelled
        6: "Executing",   # target_reached (still active)
        7: "Executing",   # waiting
    }

    def _build_mission_report(self, state: "RobotState") -> dict:
        mission_state = self._MISSION_STATE.get(state.task_status or 0, "Executing")
        in_progress = mission_state == "Executing"
        report: dict = {
            "missionId": state.task_no,
            "inProgress": in_progress,
            "state": mission_state,
            "label": f"Keenon task {state.task_no}",
            "startTs": state.task_start_ts or int(time.time() * 1000),
            "data": {},
            "status": "Error" if mission_state in ("Aborted",) else "OK",
            "tasks": [{"taskId": "0", "label": "Delivery"}],
            "completedPercent": 1.0 if mission_state == "Completed" else 0.0,
        }
        if in_progress:
            report["currentTaskId"] = "0"
        else:
            report["endTs"] = int(time.time() * 1000)
        return report

    # ------------------------------------------------------------------
    # Command handling
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
                stderr="Connector is not yet connected to the Keenon API",
            )

        result_fn = options["result_function"]
        script_name, script_args = parse_custom_command_args(args)
        fleet_id = self._robot_id_to_fleet_id[robot_id]
        robot_cfg = self._robot_configs[robot_id]
        state = self._robot_states[robot_id]

        match script_name:
            case CustomScripts.CALL_TO_POINT:
                cmd = CallToPointCommand.model_validate(script_args)
                robot_type = state.robot_type if state.robot_type in ("food", "hotel") else None
                task_no = await self._api_client.call_to_point(
                    uuid=cmd.point_uuid,
                    point_id=cmd.point_id,
                    store_id=robot_cfg.store_id,
                    robot_id=fleet_id,
                    scene_code=cmd.scene_code,
                    robot_type=robot_type,
                )
                state.task_no = task_no
                state.task_status = 1  # queued
                state.task_start_ts = int(time.time() * 1000)

            case CustomScripts.RETURN_TO_ORIGIN:
                task_no = await self._api_client.return_to_origin(
                    store_id=robot_cfg.store_id,
                    robot_id=fleet_id,
                )
                state.task_no = task_no
                state.task_status = 1
                state.task_start_ts = int(time.time() * 1000)

            case CustomScripts.CANCEL_TASK:
                cmd = CancelTaskCommand.model_validate(script_args)
                await self._api_client.cancel_task(task_no=cmd.task_no)
                state.task_status = 5  # cancelled

            case CustomScripts.CLEAN_RECHARGE:
                await self._api_client.clean_recharge(robot_sn=fleet_id)

            case CustomScripts.CLEAN_FINISH:
                await self._api_client.clean_finish(robot_sn=fleet_id)

            case CustomScripts.CLEAN_PAUSE:
                await self._api_client.clean_pause(robot_sn=fleet_id)

            case CustomScripts.CLEAN_TEMPORARY_TASK:
                cmd = CleanTemporaryTaskCommand.model_validate(script_args)
                area_ids = json.loads(cmd.area_id_list)
                await self._api_client.clean_temporary_task(
                    robot_sn=fleet_id,
                    area_id_list=area_ids,
                    clean_model_id=cmd.clean_model_id,
                    clean_times=cmd.clean_times,
                    back_point_id=cmd.back_point_id,
                )

            case CustomScripts.OPEN_CABIN:
                cmd = CabinControlCommand.model_validate(script_args)
                await self._api_client.control_cabin(
                    store_id=robot_cfg.store_id,
                    robot_sn=fleet_id,
                    cabin=cmd.cabin,
                    ctrl_type="1",
                )

            case CustomScripts.CLOSE_CABIN:
                cmd = CabinControlCommand.model_validate(script_args)
                await self._api_client.control_cabin(
                    store_id=robot_cfg.store_id,
                    robot_sn=fleet_id,
                    cabin=cmd.cabin,
                    ctrl_type="0",
                )

            case _:
                raise CommandFailure(
                    execution_status_details=f"Unknown command: {script_name}",
                    stderr=f"Command '{script_name}' is not supported",
                )

        result_fn(CommandResultCode.SUCCESS)

    # ------------------------------------------------------------------
    # Map fetching
    # ------------------------------------------------------------------

    @override
    async def fetch_robot_map(
        self, robot_id: str, frame_id: str
    ) -> MapConfigTemp | None:
        state = self._robot_states.get(robot_id)
        if not state or not state.floor or self._api_client is None:
            return None
        try:
            image_bytes = await self._api_client.get_map(
                scene_code=frame_id,
                floor_info=state.floor,
                building_info=state.building or "",
            )
            if not image_bytes:
                return None
            width, height = png_dimensions(image_bytes)
            origin_x, origin_y = keenon_map_origin(width, height)
            return MapConfigTemp(
                image=image_bytes,
                map_id=frame_id,
                map_label=state.scene_name or frame_id,
                origin_x=origin_x,
                origin_y=origin_y,
                resolution=KEENON_MAP_RESOLUTION,
            )
        except Exception as exc:
            if "610403" in str(exc):
                self._logger.warning(
                    "Map endpoint returned 610403 (no permission) — "
                    "contact your Keenon administrator to grant map access."
                )
            else:
                self._logger.warning("Map fetch failed for robot %s: %s", robot_id, exc)
            return None

    # ------------------------------------------------------------------
    # Online check
    # ------------------------------------------------------------------

    @override
    def _is_fleet_robot_online(self, robot_id: str) -> bool:
        state = self._robot_states.get(robot_id)
        return state.api_connected if state else False
