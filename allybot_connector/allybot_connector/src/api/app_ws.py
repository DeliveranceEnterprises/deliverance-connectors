# SPDX-FileCopyrightText: 2026 Deliverance Enterprises
#
# SPDX-License-Identifier: MIT

"""App WebSocket client for the Ally Fleet real-time position stream."""

import asyncio
import json
import logging
import time

import aiohttp

from .models import AllybotRobotState, quaternion_to_yaw

logger = logging.getLogger(__name__)

_PING_INTERVAL_S = 20.0
_MAX_BACKOFF_S = 60.0


class AllybotAppWebSocket:
    """Connects to the Ally Fleet App WebSocket and dispatches position updates.

    A single connection delivers ``device_position`` messages for all robots
    registered on the account.  Each message is matched to a robot state by
    the ``msg.serial`` field (= ``fleet_robot_id`` in the connector config).

    The connection is maintained automatically: on disconnect, an exponential
    back-off retry loop re-establishes it until ``stop()`` is called.
    """

    def __init__(
        self,
        base_url: str,
        openid: str,
        token: str,
        robot_states: dict[str, AllybotRobotState],
        fleet_serial_to_robot_id: dict[str, str],
    ) -> None:
        # Build the WebSocket URL from the HTTP base URL.
        ws_base = (
            base_url.rstrip("/")
            .replace("https://", "wss://")
            .replace("http://", "ws://")
        )
        self._ws_url = f"{ws_base}/fleetapi/websocketapp/{openid}/{token}"
        self._robot_states = robot_states
        self._fleet_serial_to_robot_id = fleet_serial_to_robot_id
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="allybot-app-ws")

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    # ------------------------------------------------------------------
    # Connection loop with exponential backoff
    # ------------------------------------------------------------------

    async def _run(self) -> None:
        backoff = 1.0
        while not self._stop_event.is_set():
            try:
                await self._connect_once()
                backoff = 1.0
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("App WS error: %s — reconnecting in %.0fs", exc, backoff)
                self._mark_all_disconnected()
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=backoff)
            except TimeoutError:
                pass
            backoff = min(backoff * 2, _MAX_BACKOFF_S)

    async def _connect_once(self) -> None:
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(self._ws_url) as ws:
                logger.info("App WS connected: %s", self._ws_url)
                ping_task = asyncio.create_task(self._ping_loop(ws))
                try:
                    async for msg in ws:
                        if self._stop_event.is_set():
                            break
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            self._dispatch(msg.data)
                        elif msg.type in (
                            aiohttp.WSMsgType.ERROR,
                            aiohttp.WSMsgType.CLOSED,
                        ):
                            logger.warning("App WS closed: %s", msg)
                            break
                finally:
                    ping_task.cancel()
                    self._mark_all_disconnected()

    async def _ping_loop(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        while True:
            await asyncio.sleep(_PING_INTERVAL_S)
            await ws.send_json({"type": "ping", "language": "en_US"})

    # ------------------------------------------------------------------
    # Message dispatch
    # ------------------------------------------------------------------

    def _dispatch(self, raw: str) -> None:
        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            return
        match body.get("type"):
            case "device_position":
                self._on_device_position(body)
            case "devicestasktatus":
                self._on_task_status(body)
            case "devicestatus":
                self._on_device_status(body)
            case "pong":
                pass  # keepalive acknowledgement

    def _on_device_position(self, body: dict) -> None:
        msg_str = body.get("msg", "")
        try:
            msg = json.loads(msg_str)
        except (json.JSONDecodeError, TypeError):
            return

        serial = msg.get("serial", "")
        robot_id = self._fleet_serial_to_robot_id.get(serial)
        if not robot_id:
            return

        state = self._robot_states.get(robot_id)
        if not state:
            return

        pos = msg.get("position") or {}
        ori = msg.get("orientation") or {}

        try:
            state.x = float(pos["x"])
            state.y = float(pos["y"])
            state.yaw = quaternion_to_yaw(
                float(ori.get("x", 0)),
                float(ori.get("y", 0)),
                float(ori.get("z", 0)),
                float(ori.get("w", 1)),
            )
            state.speed = float(msg.get("speed", 0))
        except (KeyError, TypeError, ValueError) as exc:
            logger.debug("Could not parse device_position: %s", exc)
            return

        state.ws_connected = True
        state.last_ws_message = time.time()

    def _on_task_status(self, body: dict) -> None:
        """Handle devicestasktatus — real-time task progress (~1 Hz while task active)."""
        robot_serial = body.get("robotid", "")
        robot_id = self._fleet_serial_to_robot_id.get(robot_serial)
        if not robot_id:
            return
        state = self._robot_states.get(robot_id)
        if not state:
            return

        state.task_id = body.get("taskId")
        state.task_name = body.get("name")
        state.task_status_code = body.get("taskStatus")

        percent = body.get("percent")
        if percent is not None:
            try:
                state.task_percentage = float(percent)
            except (TypeError, ValueError):
                pass

        # Parse inner msg for startTime
        msg_str = body.get("msg", "")
        try:
            inner = json.loads(msg_str)
            if state.task_start_ts is None and inner.get("startTime"):
                state.task_start_ts = int(inner["startTime"])
        except (json.JSONDecodeError, TypeError, ValueError):
            pass

    def _on_device_status(self, body: dict) -> None:
        """Handle devicestatus — full device snapshot including battery and work_status (~1 Hz)."""
        data = body.get("data") or {}
        device_id = data.get("id", "")
        robot_id = self._fleet_serial_to_robot_id.get(device_id)
        if not robot_id:
            return
        state = self._robot_states.get(robot_id)
        if not state:
            return

        battery = data.get("battery")
        if battery is not None:
            try:
                state.battery = int(battery)
            except (TypeError, ValueError):
                pass

        fresh = data.get("freshWater")
        if fresh is not None:
            try:
                state.fresh_water = float(fresh)
            except (TypeError, ValueError):
                pass

        sewage = data.get("sewageWater")
        if sewage is not None:
            try:
                state.sewage_water = float(sewage)
            except (TypeError, ValueError):
                pass

        state.work_status = data.get("work_status")
        have_task = data.get("haveTaskRunning")
        if have_task is not None:
            state.have_task_running = bool(have_task)

        # Clear task fields when no task is running
        if not state.have_task_running and data.get("clean") is None:
            state.task_id = None
            state.task_name = None
            state.task_percentage = None
            state.task_status_code = None
            state.task_start_ts = None

    def _mark_all_disconnected(self) -> None:
        for state in self._robot_states.values():
            state.ws_connected = False
