# SPDX-FileCopyrightText: 2026 Deliverance Enterprises
#
# SPDX-License-Identifier: MIT

"""App WebSocket client for the Ally Fleet real-time position stream."""

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable

import aiohttp

from .models import AllybotRobotState, normalize_work_status, quaternion_to_yaw

logger = logging.getLogger(__name__)

_PING_INTERVAL_S = 20.0
# On a live connection a keepalive frame arrives about every 20 s even when the robot sends
# nothing (robot switched off). The API doc says its type is "pong"; measured live it is
# "ping", so both count. A connection that delivers no frame at all for
# this long is dead, even if the socket still looks open.
_KEEPALIVE_TYPES = frozenset({"ping", "pong"})
_SILENCE_TIMEOUT_S = 3 * _PING_INTERVAL_S
# Wait before reconnecting after a healthy connection ends, and the first step of the back-off.
_RECONNECT_DELAY_S = 1.0
_MAX_BACKOFF_S = 60.0
# A connection that lived at least this long counts as healthy: the next reconnect
# starts its back-off from the beginning instead of continuing to grow.
_STABLE_CONNECTION_S = 30.0
# A connection that never delivered a single frame is retried on a slower schedule: every
# retry costs a login, and a login invalidates the other sessions of the account.
_MIN_SILENT_BACKOFF_S = 30.0
_MAX_SILENT_BACKOFF_S = 600.0

# How a connection attempt ended.
_CLOSED = "closed"  # the server (or the network) closed it
_SILENT = "silent"  # it stayed open but nothing arrived for _SILENCE_TIMEOUT_S
_ERROR = "error"  # it could not be opened, or the login before it failed


def _next_delay(
    outcome: str,
    lasted_s: float,
    got_data: bool,
    backoff: float,
    silent_backoff: float,
) -> tuple[float, float, float]:
    """How long to wait before the next attempt, and the two back-offs to carry forward.

    Returns ``(delay, backoff, silent_backoff)``. ``backoff`` grows with consecutive
    failures (1, 2, 4 ... 60 s); ``silent_backoff`` does the same, slower, for a
    connection that stayed open but never delivered anything. A healthy connection
    (it delivered data, or lived long enough) resets them, so one network blip is
    retried after a second, while a connection that keeps dying right away or
    staying mute does not turn into a login every second.
    """
    if outcome == _SILENT and not got_data:
        return silent_backoff, backoff, min(silent_backoff * 2, _MAX_SILENT_BACKOFF_S)
    if got_data or lasted_s >= _STABLE_CONNECTION_S:
        return _RECONNECT_DELAY_S, 2 * _RECONNECT_DELAY_S, _MIN_SILENT_BACKOFF_S
    return backoff, min(backoff * 2, _MAX_BACKOFF_S), silent_backoff


def _whole_minutes(value: object) -> int | None:
    """A non-negative whole number of minutes from a WS field, or None when it is missing or not a number."""
    if value is None or isinstance(value, bool):
        return None
    try:
        minutes = int(float(value))
    except (TypeError, ValueError):
        return None
    return minutes if minutes >= 0 else None


class AllybotAppWebSocket:
    """Connects to the Ally Fleet App WebSocket and dispatches position updates.

    A single connection delivers ``device_position`` messages for all robots
    registered on the account.  Each message is matched to a robot state by
    the ``msg.serial`` field (= ``fleet_robot_id`` in the connector config).

    The connection is maintained automatically until ``stop()`` is called. The cloud
    keeps ONE session per account and validates the token only when the WebSocket
    opens: an open WebSocket keeps delivering after another login invalidates the
    token, but one opened with an invalidated token is accepted and stays silent.
    So when a ``relogin`` callable is given, it is awaited before EVERY reconnect to
    get a live token, and a connection that stays silent is dropped and replaced.
    The first connection uses the token the caller already obtained.
    """

    def __init__(
        self,
        base_url: str,
        openid: str,
        token: str,
        robot_states: dict[str, AllybotRobotState],
        fleet_serial_to_robot_id: dict[str, str],
        relogin: Callable[[], Awaitable[tuple[str, str]]] | None = None,
    ) -> None:
        # Build the WebSocket base URL from the HTTP base URL.
        self._ws_base = (
            base_url.rstrip("/")
            .replace("https://", "wss://")
            .replace("http://", "ws://")
        )
        self._openid = openid
        self._token = token
        self._relogin = relogin
        self._robot_states = robot_states
        self._fleet_serial_to_robot_id = fleet_serial_to_robot_id
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task | None = None

    @property
    def _ws_url(self) -> str:
        return f"{self._ws_base}/fleetapi/websocketapp/{self._openid}/{self._token}"

    def _scrub(self, error: BaseException) -> str:
        """An error's text with the session token removed, safe to log."""
        text = str(error)
        return text.replace(self._token, "***") if self._token else text

    @property
    def _loggable_url(self) -> str:
        """The URL for logs: the token is a session secret and must not reach a log file."""
        return f"{self._ws_base}/fleetapi/websocketapp/{self._openid}/***"

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
        backoff = _RECONNECT_DELAY_S
        silent_backoff = _MIN_SILENT_BACKOFF_S
        first = True
        while not self._stop_event.is_set():
            outcome, lasted_s, got_data, error = _ERROR, 0.0, False, None
            try:
                if not first and self._relogin is not None:
                    # Every reconnect starts from a live token: the previous one may
                    # have been invalidated by another login (phone app, another connector).
                    self._openid, self._token = await self._relogin()
                    logger.info("App WS: logged in again to reconnect with a fresh token")
                first = False
                outcome, lasted_s, got_data = await self._connect_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                error = exc
                self._mark_all_disconnected()
            delay, backoff, silent_backoff = _next_delay(
                outcome, lasted_s, got_data, backoff, silent_backoff
            )
            if error is not None:
                # aiohttp puts the full URL, token included, in its handshake errors.
                logger.warning("App WS error: %s; reconnecting in %.0fs", self._scrub(error), delay)
            else:
                logger.info(
                    "App WS %s after %.0fs; reconnecting in %.0fs", outcome, lasted_s, delay
                )
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=delay)
            except TimeoutError:
                pass

    async def _connect_once(self) -> tuple[str, float, bool]:
        """Run one connection until it ends. Returns ``(outcome, seconds_it_lasted, got_data)``.

        ``got_data`` is True when at least one frame other than a keepalive arrived: a token
        the server rejects (or has invalidated) never gets one, a live one gets ~1 Hz while the
        robot is online.
        """
        started = time.monotonic()
        outcome = _CLOSED
        got_data = False
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(self._ws_url) as ws:
                logger.info("App WS connected: %s", self._loggable_url)
                ping_task = asyncio.create_task(self._ping_loop(ws))
                try:
                    while not self._stop_event.is_set():
                        try:
                            msg = await ws.receive(timeout=_SILENCE_TIMEOUT_S)
                        except TimeoutError:
                            logger.warning(
                                "App WS silent for %.0fs (not even a keepalive): dropping it",
                                _SILENCE_TIMEOUT_S,
                            )
                            outcome = _SILENT
                            break
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            kind = self._dispatch(msg.data)
                            if kind is not None and kind not in _KEEPALIVE_TYPES:
                                got_data = True
                        elif msg.type != aiohttp.WSMsgType.BINARY:
                            logger.warning("App WS closed: %s", msg)
                            break
                finally:
                    ping_task.cancel()
                    self._mark_all_disconnected()
        return outcome, time.monotonic() - started, got_data

    async def _ping_loop(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        while True:
            await asyncio.sleep(_PING_INTERVAL_S)
            await ws.send_json({"type": "ping", "language": "en_US"})

    # ------------------------------------------------------------------
    # Message dispatch
    # ------------------------------------------------------------------

    def _dispatch(self, raw: str) -> str | None:
        """Handle one frame. Returns its ``type`` (None when it is not valid JSON)."""
        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            return None
        kind = body.get("type") if isinstance(body, dict) else None
        match kind:
            case "device_position":
                self._on_device_position(body)
            case "devicestasktatus":
                self._on_task_status(body)
            case "devicestatus":
                self._on_device_status(body)
            case "otherlogin":
                # Another login (phone app, another connector, a script) took the account's
                # REST session. This WebSocket keeps delivering. The line is a timestamped
                # record of when it happens, to find out who it is; the frame itself is not logged.
                logger.info(
                    "App WS: another login took over the account session "
                    "(this WebSocket stays open)"
                )
            case "ping" | "pong":
                pass  # keepalive
        return kind

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

        # Cleaned area so far (outer field, m²) - part of the partial report.
        area = body.get("area")
        if area is not None:
            try:
                state.cleaned_area = float(area)
            except (TypeError, ValueError):
                pass

        # Parse inner msg for startTime and total plan area (workingScope).
        msg_str = body.get("msg", "")
        try:
            inner = json.loads(msg_str)
            if state.task_start_ts is None and inner.get("startTime"):
                state.task_start_ts = int(inner["startTime"])
            scope = inner.get("workingScope")
            if scope is not None:
                state.plan_area = float(scope)
        except (json.JSONDecodeError, TypeError, ValueError):
            inner = {}

        # Time estimate, in whole minutes. Read apart from the block above so a bad value here cannot cost the area, and the other way round.
        estimate = _whole_minutes(inner.get("totalTime"))
        if estimate is not None:
            state.task_estimate_min = estimate
            if state.task_estimate_start_min is None:
                state.task_estimate_start_min = estimate

        state.ws_connected = True
        state.last_ws_message = time.time()

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

        state.work_status = normalize_work_status(data.get("work_status"))

        # Cleaning mode + area from the data.clean sub-object (null when idle).
        clean = data.get("clean") or {}
        if clean.get("task_mode"):
            state.task_mode = clean["task_mode"]
        if state.cleaned_area is None and clean.get("area") is not None:
            try:
                state.cleaned_area = float(clean["area"])
            except (TypeError, ValueError):
                pass

        have_task = data.get("haveTaskRunning")
        if have_task is not None:
            prev = state.have_task_running
            state.have_task_running = bool(have_task)
            if state.have_task_running and not prev:
                # A new run begins (or the connector restarted mid-run). Drop the
                # previous run's start/end and counters so this run gets its OWN
                # startTs, hence its own missionId. Before this, task_start_ts was
                # copied from the robot once and never reset, so every later run
                # was published under the first run's missionId and InOrbit (and
                # the platform, which keys tasks by start time) merged them all.
                state.task_start_ts = None
                state.task_end_ts = None
                state.run_seen_at = time.monotonic()
                state.task_estimate_start_min = None
                state.task_estimate_min = None
                state.task_percentage = None
                state.cleaned_area = None
                state.plan_area = None
            # Task just finished — mark complete so the connector can publish
            # a final mission_tracking entry before clearing state next cycle.
            if prev and not state.have_task_running:
                state.task_status_code = None  # signals natural completion
                state.task_end_ts = int(time.time() * 1000)

        # Found live: ws_connected used to be set ONLY in
        # _on_device_position, so a docked/charging robot (which stops
        # reporting position -- data.location is false while docked, only
        # devicestatus keeps arriving) never marked itself connected. InOrbit
        # then raised a permanent false "WS Connected: error" incident even
        # though the WebSocket was fine and real telemetry (battery,
        # work_status) was flowing the whole time. Any real message proves
        # the connection is alive, not just a position fix.
        state.ws_connected = True
        state.last_ws_message = time.time()

    def _mark_all_disconnected(self) -> None:
        for state in self._robot_states.values():
            state.ws_connected = False
