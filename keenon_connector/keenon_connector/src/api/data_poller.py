# SPDX-FileCopyrightText: 2026 Deliverance Enterprises
#
# SPDX-License-Identifier: MIT

"""Background polling tasks that keep RobotState caches up to date."""

import asyncio
import logging
import time

from .client import KeenonAPIClient
from .models import RobotState, TERMINAL_TASK_STATUSES, detect_robot_type, parse_coordinate

logger = logging.getLogger(__name__)

# How often to refresh static metadata (robot model, app version).
METADATA_POLL_INTERVAL_S = 60.0


class DataPoller:
    """Polls the Keenon Cloud API and maintains a per-robot RobotState cache.

    One asyncio Task is created per robot. Each task:
    - Refreshes metadata (robot list) every 60 s.
    - Refreshes real-time data (status, location, cleaning state) at update_freq.
    - Polls active task status until the task reaches a terminal state.
    """

    def __init__(
        self,
        client: KeenonAPIClient,
        robot_states: dict[str, RobotState],
        fleet_id_to_store: dict[str, str],
        robot_id_to_fleet_id: dict[str, str],
        update_freq: float,
    ) -> None:
        self._client = client
        self._robot_states = robot_states
        self._fleet_id_to_store = fleet_id_to_store
        self._robot_id_to_fleet_id = robot_id_to_fleet_id
        self._interval = 1.0 / max(update_freq, 0.1)
        self._stop_event = asyncio.Event()
        self._tasks: list[asyncio.Task] = []

    def start(self) -> None:
        for robot_id in self._robot_id_to_fleet_id:
            task = asyncio.create_task(
                self._poll_robot(robot_id), name=f"keenon-poll-{robot_id}"
            )
            self._tasks.append(task)

    async def stop(self) -> None:
        self._stop_event.set()
        if self._tasks:
            _, pending = await asyncio.wait(self._tasks, timeout=2.0)
            for t in pending:
                t.cancel()

    # ------------------------------------------------------------------
    # Per-robot polling loop
    # ------------------------------------------------------------------

    async def _poll_robot(self, robot_id: str) -> None:
        fleet_id = self._robot_id_to_fleet_id[robot_id]
        store_id = self._fleet_id_to_store[fleet_id]
        state = self._robot_states[robot_id]
        last_metadata = 0.0

        while not self._stop_event.is_set():
            now = time.monotonic()

            if now - last_metadata >= METADATA_POLL_INTERVAL_S:
                await self._refresh_metadata(robot_id, fleet_id, store_id, state)
                last_metadata = time.monotonic()

            await self._refresh_realtime(robot_id, fleet_id, state)

            try:
                await asyncio.wait_for(
                    self._stop_event.wait(), timeout=self._interval
                )
            except TimeoutError:
                pass

    # ------------------------------------------------------------------
    # Metadata (slow)
    # ------------------------------------------------------------------

    async def _refresh_metadata(
        self,
        robot_id: str,
        fleet_id: str,
        store_id: str,
        state: RobotState,
    ) -> None:
        try:
            robots = await self._client.get_robot_list(store_id)
            for r in robots:
                if r.get("robotId") == fleet_id:
                    state.robot_model = r.get("robotModel")
                    state.app_version = r.get("appVersion")
                    if state.robot_type is None:
                        state.robot_type = detect_robot_type(state.robot_model)
                    break
        except Exception as exc:
            logger.warning("Metadata refresh failed for %s: %s", robot_id, exc)

    # ------------------------------------------------------------------
    # Real-time data (fast)
    # ------------------------------------------------------------------

    async def _refresh_realtime(
        self,
        robot_id: str,
        fleet_id: str,
        state: RobotState,
    ) -> None:
        try:
            await self._update_status(fleet_id, state)
            await self._update_location(fleet_id, state)
            if state.robot_type == "clean":
                await self._update_clean_status(fleet_id, state)
            if state.task_no:
                await self._update_task_status(state)
            state.api_connected = True
            state.last_update = time.time()
        except Exception as exc:
            logger.error("Real-time refresh failed for %s: %s", robot_id, exc)
            state.api_connected = False

    async def _update_status(self, fleet_id: str, state: RobotState) -> None:
        status_list = await self._client.get_robot_status(fleet_id)
        if not status_list:
            return
        s = status_list[0]
        state.battery = s.get("power")
        state.charge_status = s.get("chargeStatus")
        online = s.get("onlineStatus")
        if isinstance(online, bool):
            state.online_status = online
        state.can_be_called = s.get("canBeCalled")
        state.scene_code = s.get("sceneCode")
        state.scene_name = s.get("sceneName")

    async def _update_location(self, fleet_id: str, state: RobotState) -> None:
        loc = await self._client.get_robot_location(fleet_id)
        if not loc:
            return
        coord = loc.get("coordinate", "")
        if coord:
            parsed = parse_coordinate(coord)
            if parsed:
                state.x, state.y, state.yaw = parsed
        state.floor = str(loc.get("floor", ""))
        state.building = loc.get("building", "")
        state.elevator_status = loc.get("takeElevatorStatus")

    async def _update_clean_status(self, fleet_id: str, state: RobotState) -> None:
        cs = await self._client.get_clean_robot_status(fleet_id)
        if not cs:
            return
        state.clean_main_state = cs.get("mainState")
        state.clean_sub_state = cs.get("subState")
        gs = cs.get("globalState") or {}
        state.clean_faulting = gs.get("faulting")
        state.clean_scram = gs.get("scram")
        ch = cs.get("childState") or {}
        state.clean_navigating = ch.get("navigating")
        hw = cs.get("hardwareState") or {}
        state.clean_bilge_tank = hw.get("bilgeTankState")
        state.clean_water_tank = hw.get("cleanWaterTank")

    async def _update_task_status(self, state: RobotState) -> None:
        task_data = await self._client.get_task_status(state.task_no)
        if not task_data:
            return
        state.task_status = task_data.get("taskStatus")
        # task_no is intentionally kept after reaching a terminal status so the
        # connector can publish the final mission_tracking state.  It is cleared
        # when the next task is dispatched.
