# SPDX-FileCopyrightText: 2026 Deliverance Enterprises
#
# SPDX-License-Identifier: MIT

"""Background polling loop for AutoXing robot state."""

import asyncio
import logging
import time

from .client import AutoxingAPIClient
from .models import RobotState

logger = logging.getLogger(__name__)


class DataPoller:
    """Polls the AutoXing API for robot state and updates shared RobotState objects.

    Runs as a background asyncio task. Each poll cycle fetches the online robot list
    (for online/task flags) and per-robot state (for pose, battery, flags).
    """

    def __init__(
        self,
        client: AutoxingAPIClient,
        robot_states: dict[str, RobotState],
        robot_id_to_fleet_id: dict[str, str],
        fleet_id_to_robot_id: dict[str, str],
        update_freq: float = 1.0,
    ) -> None:
        self._client = client
        self._robot_states = robot_states
        self._robot_id_to_fleet_id = robot_id_to_fleet_id
        self._fleet_id_to_robot_id = fleet_id_to_robot_id
        self._poll_interval = 1.0 / update_freq if update_freq > 0 else 1.0
        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()

    def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="autoxing-poller")

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _run(self) -> None:
        while not self._stop_event.is_set():
            start = time.monotonic()
            try:
                await self._poll_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Poll cycle error: %s", exc)
            elapsed = time.monotonic() - start
            wait = max(0.0, self._poll_interval - elapsed)
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=wait)
            except TimeoutError:
                pass

    async def _poll_once(self) -> None:
        # Fetch list for online/isTask flags
        robot_list = await self._client.get_robot_list()
        fleet_online: dict[str, dict] = {r["robotId"]: r for r in robot_list if "robotId" in r}

        for robot_id, fleet_id in self._robot_id_to_fleet_id.items():
            state = self._robot_states[robot_id]
            list_entry = fleet_online.get(fleet_id)

            if list_entry:
                state.online = bool(list_entry.get("isOnLine", False))
                state.is_task = bool(list_entry.get("isTask", False))
            else:
                state.online = False

            # Per-robot detailed state
            raw = await self._client.get_robot_state(fleet_id)
            if raw:
                self._apply_state(state, raw)
                state.api_connected = True
            else:
                state.api_connected = False

            state.last_update = time.time()

    def _apply_state(self, state: RobotState, raw: dict) -> None:
        x = raw.get("x")
        y = raw.get("y")
        yaw_deg = raw.get("yaw")

        if x is not None:
            state.x = float(x)
        if y is not None:
            state.y = float(y)
        if yaw_deg is not None:
            # API docs say degrees but real values are radians — use directly.
            state.yaw = float(yaw_deg)

        speed = raw.get("speed")
        if speed is not None:
            state.speed = float(speed)

        area_id = raw.get("areaId")
        if area_id:
            state.area_id = area_id

        battery = raw.get("battery")
        if battery is not None:
            state.battery = int(battery)

        state.is_charging = raw.get("isCharging")
        state.is_go_home = raw.get("isGoHome")
        state.is_emergency_stop = raw.get("isEmergencyStop")
        state.is_manual_mode = raw.get("isManualMode")
        state.is_remote_mode = raw.get("isRemoteMode")
        state.has_obstruction = raw.get("hasObstruction")

        loc_quality = raw.get("locQuality")
        if loc_quality is not None:
            state.loc_quality = int(loc_quality)

        errors = raw.get("errors")
        if isinstance(errors, list):
            state.errors = errors

        task_obj = raw.get("taskObj") or {}
        task_id = task_obj.get("taskId")
        if task_id and task_id != state.task_id:
            # New task started
            state.task_id = task_id
            state.task_start_ts = int(time.time() * 1000)
            state.task_is_finish = False
            state.task_is_cancel = False
        elif task_id:
            state.task_is_finish = task_obj.get("isFinish", False)
            state.task_is_cancel = task_obj.get("isCancel", False)
        elif not task_id and state.task_id:
            # Task cleared by robot
            state.task_is_finish = True
            # Keep task_id so connector can publish final mission_tracking
