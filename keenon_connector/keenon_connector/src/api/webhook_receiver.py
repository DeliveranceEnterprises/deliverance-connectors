# SPDX-FileCopyrightText: 2026 Deliverance Enterprises
#
# SPDX-License-Identifier: MIT

"""aiohttp-based webhook receiver for Keenon push callbacks."""

import logging
import math

from aiohttp import web

from .models import RobotState

logger = logging.getLogger(__name__)

# Map Keenon's string onlineType values to the int codes used in RobotState.
_ONLINE_TYPE_STR_MAP: dict[str, int] = {
    "2G": 3,
    "4G": 4,
    "Wi-Fi": 2,
    "unknown": 5,
}


class KeenonWebhookReceiver:
    """Receives Keenon push callbacks and updates RobotState caches in place.

    Keenon POSTs JSON to the configured URL whenever robot state changes.
    The receiver updates the shared ``robot_states`` dict (keyed by InOrbit
    robot ID) so the connector's execution loop always sees fresh data.

    Configure the webhook URL in the Keenon platform to point at:
        http://<host>:<port>/webhook
    """

    def __init__(
        self,
        host: str,
        port: int,
        robot_states: dict[str, RobotState],
        fleet_sn_to_robot_id: dict[str, str],
    ) -> None:
        self._host = host
        self._port = port
        self._robot_states = robot_states
        self._fleet_sn_to_robot_id = fleet_sn_to_robot_id
        self._app = web.Application()
        self._app.router.add_post("/webhook", self._handle)
        self._runner: web.AppRunner | None = None

    async def start(self) -> None:
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self._host, self._port)
        await site.start()
        logger.info("Keenon webhook receiver listening on %s:%d", self._host, self._port)

    async def stop(self) -> None:
        if self._runner:
            await self._runner.cleanup()
            self._runner = None

    # ------------------------------------------------------------------
    # Routing
    # ------------------------------------------------------------------

    async def _handle(self, request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except Exception:
            return web.Response(status=400, text="Invalid JSON")

        biz_type: str = body.get("bizType", "")
        logger.debug("Webhook: bizType=%s", biz_type)

        try:
            match biz_type:
                case "RobotOnlineStatus":
                    self._on_online_status(body.get("data") or {})
                case "RobotOnlineType":
                    self._on_online_type(body.get("data") or {})
                case "RobotPowerInfo":
                    self._on_power_info(body.get("data") or {})
                case "RobotWorkState":
                    self._on_work_state(body.get("data") or {})
                case "RobotPositionType":
                    self._on_position(body.get("data") or {}, body)
                case "RobotTaskState":
                    self._on_task_state(body)
                case "CleanRobotStatus":
                    self._on_clean_status(body)
        except Exception as exc:
            logger.warning("Error processing webhook %s: %s", biz_type, exc)

        return web.Response(status=200)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _state_for_sn(self, robot_sn: str) -> RobotState | None:
        robot_id = self._fleet_sn_to_robot_id.get(robot_sn)
        if robot_id:
            return self._robot_states.get(robot_id)
        logger.debug("Unknown robotSn in webhook: %s", robot_sn)
        return None

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _on_online_status(self, data: dict) -> None:
        state = self._state_for_sn(data.get("robotSn", ""))
        if state:
            state.online_status = data.get("onlineStatus")

    def _on_online_type(self, data: dict) -> None:
        state = self._state_for_sn(data.get("robotSn", ""))
        if state:
            raw = data.get("onlineType", "")
            state.online_type = _ONLINE_TYPE_STR_MAP.get(raw, 5)

    def _on_power_info(self, data: dict) -> None:
        state = self._state_for_sn(data.get("robotSn", ""))
        if state:
            power = data.get("power") or {}
            if (lvl := power.get("batteryLevel")) is not None:
                state.battery = lvl
            if (cs := power.get("chargeStatus")) is not None:
                state.charge_status = cs

    def _on_work_state(self, data: dict) -> None:
        state = self._state_for_sn(data.get("robotSn", ""))
        if state:
            if (rs := data.get("robotState")) is not None:
                state.robot_state = rs
            if (cbc := data.get("canBeCalled")) is not None:
                state.can_be_called = cbc

    def _on_position(self, data: dict, raw_body: dict) -> None:
        # robotSn may appear at top level or inside data depending on firmware.
        sn = raw_body.get("robotSn") or data.get("robotSn", "")
        state = self._state_for_sn(sn)
        if not state:
            return
        pos = data.get("robotPos") or {}
        try:
            state.x = float(pos.get("x", 0))
            state.y = float(pos.get("y", 0))
            state.yaw = math.radians(float(pos.get("rotation", 0)))
        except (TypeError, ValueError) as exc:
            logger.debug("Could not parse position data: %s", exc)

    def _on_task_state(self, body: dict) -> None:
        sn = body.get("robotSn", "")
        state = self._state_for_sn(sn)
        if state:
            state.task_no = body.get("taskNo")
            state.task_status = body.get("taskState")

    def _on_clean_status(self, body: dict) -> None:
        # Keenon wraps the payload in 'data' for some webhook versions.
        payload = body.get("data") or body
        sn = payload.get("robotSn", "")
        state = self._state_for_sn(sn)
        if not state:
            return
        state.clean_main_state = payload.get("mainState")
        state.clean_sub_state = payload.get("subState")
        gs = payload.get("globalState") or {}
        state.clean_faulting = gs.get("faulting")
        state.clean_scram = gs.get("scram")
        ch = payload.get("childState") or {}
        state.clean_navigating = ch.get("navigating")
        hw = payload.get("hardwareState") or {}
        state.clean_bilge_tank = hw.get("bilgeTankState")
        state.clean_water_tank = hw.get("cleanWaterTank")
        state.robot_type = "clean"
