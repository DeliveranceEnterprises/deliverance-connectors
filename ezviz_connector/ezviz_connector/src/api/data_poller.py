"""Background polling tasks that keep CameraState caches up to date."""

import asyncio
import logging
import time

from .client import EzvizAPIClient
from .models import CameraState

logger = logging.getLogger(__name__)


def _to_int(value) -> int | None:
    """Ezviz mixes ints, strings, and missing values. Normalise to int|None."""
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class DataPoller:
    """One asyncio task per camera, refreshing CameraState on a fixed cadence."""

    def __init__(
        self,
        client: EzvizAPIClient,
        states: dict[str, CameraState],
        robot_id_to_serial: dict[str, str],
        update_freq: float,
    ) -> None:
        self._client = client
        self._states = states
        self._robot_id_to_serial = robot_id_to_serial
        self._interval = 1.0 / max(update_freq, 0.1)
        self._stop_event = asyncio.Event()
        self._tasks: list[asyncio.Task] = []

    def start(self) -> None:
        for robot_id in self._robot_id_to_serial:
            task = asyncio.create_task(
                self._poll_one(robot_id), name=f"ezviz-poll-{robot_id}"
            )
            self._tasks.append(task)

    async def stop(self) -> None:
        self._stop_event.set()
        if self._tasks:
            _, pending = await asyncio.wait(self._tasks, timeout=2.0)
            for t in pending:
                t.cancel()

    async def _poll_one(self, robot_id: str) -> None:
        serial = self._robot_id_to_serial[robot_id]
        state = self._states[robot_id]

        while not self._stop_event.is_set():
            try:
                raw = await self._client.get_device_infos(serial)
                self._apply(state, raw)
                state.api_connected = True
            except Exception as exc:  # noqa: BLE001
                state.api_connected = False
                logger.warning("[%s/%s] poll failed: %s", robot_id, serial, exc)

            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self._interval)
            except asyncio.TimeoutError:
                pass

    def _apply(self, state: CameraState, raw: dict) -> None:
        state.online = _to_int(raw.get("status")) == 1
        state.name = raw.get("name") or raw.get("deviceName") or state.name
        state.category = raw.get("category") or state.category
        state.subcategory = raw.get("subcategory") or state.subcategory
        state.firmware = raw.get("version") or state.firmware
        state.battery_percent = _to_int(raw.get("battery_level"))
        state.signal_percent = _to_int(raw.get("signal"))
        motion = raw.get("Motion_Trigger")
        state.motion_triggered = bool(motion) if motion is not None else state.motion_triggered
        state.last_motion_ts = _to_int(raw.get("last_alarm_time")) or state.last_motion_ts
        secs = raw.get("Seconds_Last_Trigger")
        if isinstance(secs, (int, float)):
            state.seconds_since_last_motion = float(secs)
        # Stash anything else interesting for debugging.
        state.extra = {
            "polled_at": int(time.time() * 1000),
            "raw_status": raw.get("status"),
        }
