# SPDX-FileCopyrightText: 2026 Deliverance Enterprises
#
# SPDX-License-Identifier: MIT

"""Main AllybotConnector implementation."""

import asyncio
import logging
import time
from typing import override

from inorbit_connector.connector import FleetConnector
from inorbit_connector.models import MapConfigTemp

from allybot_connector import __version__ as connector_version
from allybot_connector.src.api.app_ws import AllybotAppWebSocket
from allybot_connector.src.api.client import AllybotAPIClient
from allybot_connector.src.api.models import ALIVE_STATUS_MAP, AllybotRobotState
from allybot_connector.src.config.models import AllybotConnectorConfig, AllybotRobotConfig

logger = logging.getLogger(__name__)

# How long without a WS message before declaring the robot unreachable.
_WS_TIMEOUT_S = 60.0
# How often to refresh robot metadata and map info via REST.
_METADATA_POLL_INTERVAL_S = 60.0


class AllybotConnector(FleetConnector):
    """InOrbit Fleet Connector for the Ally Fleet Robot API.

    Provides real-time robot position via the App WebSocket and periodic
    metadata (robot info, map details) via REST polling.

    This connector is monitoring-only — the Ally Fleet API does not expose
    control endpoints.
    """

    def __init__(self, config: AllybotConnectorConfig) -> None:
        super().__init__(config, publish_connector_system_stats=True)

        self._robot_id_to_fleet_id: dict[str, str] = {
            r.robot_id: r.fleet_robot_id for r in config.fleet
        }
        self._robot_configs: dict[str, AllybotRobotConfig] = {
            r.robot_id: r for r in config.fleet
        }
        self._fleet_serial_to_robot_id: dict[str, str] = {
            r.fleet_robot_id: r.robot_id for r in config.fleet
        }
        self._robot_states: dict[str, AllybotRobotState] = {
            r.robot_id: AllybotRobotState() for r in config.fleet
        }

        self._api_client: AllybotAPIClient | None = None
        self._app_ws: AllybotAppWebSocket | None = None
        self._metadata_task: asyncio.Task | None = None

    @property
    def _allybot_cfg(self):
        return self.config.connector_config

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @override
    async def _connect(self) -> None:
        cfg = self._allybot_cfg
        self._api_client = AllybotAPIClient(
            base_url=cfg.base_url,
            username=cfg.username,
            password=cfg.password,
            verify_ssl=cfg.verify_ssl,
            timeout=cfg.request_timeout,
        )
        await self._api_client.login()

        if not self._api_client.mobile_token or not self._api_client.openid:
            raise RuntimeError("Mobile login did not return a usable token — cannot connect App WS")

        self._app_ws = AllybotAppWebSocket(
            base_url=cfg.base_url,
            openid=self._api_client.openid,
            token=self._api_client.mobile_token,
            robot_states=self._robot_states,
            fleet_serial_to_robot_id=self._fleet_serial_to_robot_id,
        )
        self._app_ws.start()

        # Seed metadata immediately, then refresh on a background task.
        await self._refresh_all_metadata()
        self._metadata_task = asyncio.create_task(
            self._metadata_loop(), name="allybot-meta"
        )

        self._logger.info("Connected to Allybot fleet at %s", cfg.base_url)

    @override
    async def _disconnect(self) -> None:
        if self._metadata_task:
            self._metadata_task.cancel()
            try:
                await self._metadata_task
            except asyncio.CancelledError:
                pass
        if self._app_ws:
            await self._app_ws.stop()
        if self._api_client:
            await self._api_client.close()

    # ------------------------------------------------------------------
    # Metadata polling loop
    # ------------------------------------------------------------------

    async def _metadata_loop(self) -> None:
        while True:
            await asyncio.sleep(_METADATA_POLL_INTERVAL_S)
            await self._refresh_all_metadata()

    async def _refresh_all_metadata(self) -> None:
        for robot_id, fleet_id in self._robot_id_to_fleet_id.items():
            state = self._robot_states[robot_id]
            await self._refresh_robot_info(robot_id, fleet_id, state)
            await self._refresh_map_info(fleet_id, state)
            state.last_update = time.time()

    async def _refresh_robot_info(
        self, robot_id: str, fleet_id: str, state: AllybotRobotState
    ) -> None:
        info = await self._api_client.get_robot_info(fleet_id)
        if info:
            state.robot_name = info.get("robotName")
            state.alive_status = info.get("aliveStatus")

    async def _refresh_map_info(self, fleet_id: str, state: AllybotRobotState) -> None:
        data = await self._api_client.get_active_map(fleet_id)
        if not data:
            return
        mapinfo = data.get("mapinfo") or {}
        state.active_map_id = mapinfo.get("id")
        state.map_name = mapinfo.get("name")
        state.map_image_url = data.get("image_url")
        origin = mapinfo.get("original") or {}
        state.map_origin_x = origin.get("x", 0.0)
        state.map_origin_y = origin.get("y", 0.0)
        state.map_resolution = mapinfo.get("resolution", 0.05)

    # ------------------------------------------------------------------
    # Execution loop
    # ------------------------------------------------------------------

    @override
    async def _execution_loop(self) -> None:
        for robot_id in self.robot_ids:
            self._publish_robot_data(robot_id, self._robot_states[robot_id])

    def _publish_robot_data(self, robot_id: str, state: AllybotRobotState) -> None:
        if state.x is not None and state.y is not None and state.yaw is not None:
            self.publish_robot_pose(
                robot_id,
                x=state.x,
                y=state.y,
                yaw=state.yaw,
                frame_id=state.active_map_id or "map",
            )
            if state.speed is not None:
                self.publish_robot_odometry(robot_id, linear_speed=state.speed)

        kv: dict = {
            "connector_version": connector_version,
            "ws_connected": state.ws_connected,
        }

        if state.speed is not None:
            kv["speed"] = state.speed
        if state.robot_name:
            kv["robot_name"] = state.robot_name
        if state.map_name:
            kv["map_name"] = state.map_name
        if state.alive_status is not None:
            kv["online_status"] = state.alive_status in (1, 2)
            kv["alive_status"] = ALIVE_STATUS_MAP.get(state.alive_status, str(state.alive_status))

        self.publish_robot_key_values(robot_id, **kv)

    # ------------------------------------------------------------------
    # Map fetching
    # ------------------------------------------------------------------

    @override
    async def fetch_robot_map(
        self, robot_id: str, frame_id: str
    ) -> MapConfigTemp | None:
        state = self._robot_states.get(robot_id)
        if not state or not state.map_image_url or self._api_client is None:
            return None
        try:
            image_bytes = await self._api_client.fetch_map_image(state.map_image_url)
            if not image_bytes:
                return None
            return MapConfigTemp(
                image=image_bytes,
                map_id=frame_id,
                map_label=state.map_name or frame_id,
                origin_x=state.map_origin_x or 0.0,
                origin_y=state.map_origin_y or 0.0,
                resolution=state.map_resolution or 0.05,
            )
        except Exception as exc:
            self._logger.error("Map fetch failed for robot %s: %s", robot_id, exc)
            return None

    # ------------------------------------------------------------------
    # Online check
    # ------------------------------------------------------------------

    @override
    def _is_fleet_robot_online(self, robot_id: str) -> bool:
        state = self._robot_states.get(robot_id)
        if not state:
            return False
        # Consider online if WS connected AND a message arrived recently.
        return state.ws_connected and (
            time.time() - state.last_ws_message < _WS_TIMEOUT_S
        )

    # ------------------------------------------------------------------
    # Command handler (no-op — monitoring only)
    # ------------------------------------------------------------------

    @override
    async def _inorbit_robot_command_handler(
        self, robot_id: str, command_name: str, args: list, options: dict
    ) -> None:
        # No commands supported — log and ignore.
        self._logger.debug(
            "Ignoring command '%s' for robot '%s' (monitoring-only connector)",
            command_name,
            robot_id,
        )
