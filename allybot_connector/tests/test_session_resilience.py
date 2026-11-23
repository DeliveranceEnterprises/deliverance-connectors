# SPDX-FileCopyrightText: 2026 Deliverance Enterprises
#
# SPDX-License-Identifier: MIT

"""Session handling of the App WebSocket.

The Ally Fleet cloud keeps ONE session per account and checks the token only when the
WebSocket opens: an open WebSocket keeps delivering after another login invalidates the
token, but a new one opened with an invalidated token is not: measured live on
2026-11-21 it was accepted and closed by the server after about 0.5 s. A connection
accepted and left silent is handled as well, in case the server does that. These tests run the real WebSocket client against a
local server that imitates all of that, and check that the client logs in again before every
reconnect, replaces a mute connection, does NOT log in needlessly for a robot that is simply
off, and never logs the token.
"""

from __future__ import annotations

import asyncio
import json
import logging
from types import SimpleNamespace

import pytest
from aiohttp import WSMsgType, web
from pytest_httpx import HTTPXMock

from allybot_connector.src.api import app_ws as app_ws_module
from allybot_connector.src.api.app_ws import AllybotAppWebSocket, _next_delay
from allybot_connector.src.api.client import AllybotAPIClient
from allybot_connector.src.api.models import AllybotRobotState
from allybot_connector.src.connector import AllybotConnector

# The suite-wide conftest replaces asyncio.sleep with a no-delay stub; these tests need real
# time (silence, back-off), so they put the real one back. Captured at import, before any stub.
_REAL_SLEEP = asyncio.sleep

SERIAL = "SERIAL1"
ROBOT_ID = "robot-1"
LOGGER_NAME = "allybot_connector.src.api.app_ws"


@pytest.fixture(autouse=True)
def _real_time_and_short_timers(monkeypatch):
    monkeypatch.setattr(asyncio, "sleep", _REAL_SLEEP)
    monkeypatch.setattr(app_ws_module, "_PING_INTERVAL_S", 0.05)
    monkeypatch.setattr(app_ws_module, "_SILENCE_TIMEOUT_S", 0.4)
    monkeypatch.setattr(app_ws_module, "_RECONNECT_DELAY_S", 0.05)
    monkeypatch.setattr(app_ws_module, "_MAX_BACKOFF_S", 0.2)
    monkeypatch.setattr(app_ws_module, "_STABLE_CONNECTION_S", 0.3)
    monkeypatch.setattr(app_ws_module, "_MIN_SILENT_BACKOFF_S", 0.05)
    monkeypatch.setattr(app_ws_module, "_MAX_SILENT_BACKOFF_S", 0.2)


class FakeCloud:
    """Local stand-in for the Ally Fleet App WebSocket. What each token does is set in ``modes``:

    The keepalive frame the real server sends back to each ping has type ``ping`` (the API
    doc says ``pong``; measured live), so the fake does the same.

    - ``data``: delivers a devicestatus frame, then answers pings (a live token)
    - ``close_after_data``: delivers a frame and closes (a dropped connection)
    - ``close_at_once``: accepts and closes right away (a dead token, as seen live)
    - ``silent``: accepts the connection and never says anything, not even a keepalive
      (a dead token, if the server ever leaves it open)
    - ``pongs_only``: answers pings but delivers no data (a robot that is switched off)
    - ``otherlogin``: sends an ``otherlogin`` frame, then behaves like ``data``
    - ``reject``: refuses the handshake with a 401, whose error text carries the URL
    """

    def __init__(self) -> None:
        self.tokens: list[str] = []
        self.modes: dict[str, str] = {}
        self.port = 0
        self._runner: web.AppRunner | None = None

    async def _handler(self, request: web.Request) -> web.WebSocketResponse:
        token = request.match_info["token"]
        self.tokens.append(token)
        mode = self.modes.get(token, "data")
        if mode == "reject":
            return web.Response(status=401)
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        if mode == "close_at_once":
            await ws.close()
            return ws
        if mode == "silent":
            async for _ in ws:
                pass
            return ws
        if mode == "otherlogin":
            await ws.send_json({"type": "otherlogin", "msg": "secret-detail-of-the-frame"})
        if mode != "pongs_only":
            await ws.send_json({"type": "devicestatus", "data": {"id": SERIAL, "battery": 80}})
        if mode == "close_after_data":
            await ws.close()
            return ws
        async for msg in ws:
            if msg.type == WSMsgType.TEXT and json.loads(msg.data).get("type") == "ping":
                await ws.send_json({"type": "ping"})
        return ws

    async def start(self) -> None:
        app = web.Application()
        app.router.add_get("/fleetapi/websocketapp/{openid}/{token}", self._handler)
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "127.0.0.1", 0)
        await site.start()
        self.port = self._runner.addresses[0][1]

    async def stop(self) -> None:
        if self._runner:
            await self._runner.cleanup()


@pytest.fixture()
async def cloud():
    c = FakeCloud()
    await c.start()
    yield c
    await c.stop()


class Relogin:
    """Stands in for ``AllybotAPIClient.refresh_session``: hands out the given tokens in order."""

    def __init__(self, *tokens: str, fail_first: bool = False) -> None:
        self._tokens = list(tokens)
        self._fail_first = fail_first
        self.calls = 0

    async def __call__(self) -> tuple[str, str]:
        self.calls += 1
        if self._fail_first and self.calls == 1:
            raise ValueError("login rejected (simulated)")
        return "oid", self._tokens.pop(0)


def _ws(
    cloud: FakeCloud, token: str, relogin=None
) -> tuple[AllybotAppWebSocket, AllybotRobotState]:
    state = AllybotRobotState()
    ws = AllybotAppWebSocket(
        base_url=f"http://127.0.0.1:{cloud.port}",
        openid="oid",
        token=token,
        robot_states={ROBOT_ID: state},
        fleet_serial_to_robot_id={SERIAL: ROBOT_ID},
        relogin=relogin,
    )
    return ws, state


async def _until(condition, timeout: float = 5.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not condition():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("condition not met in time")
        await _REAL_SLEEP(0.01)


# ---------------------------------------------------------------------------
# Reconnecting
# ---------------------------------------------------------------------------


async def test_reconnect_logs_in_again_to_get_a_fresh_token(cloud: FakeCloud) -> None:
    cloud.modes["T1"] = "close_after_data"
    relogin = Relogin("T2")
    ws, state = _ws(cloud, "T1", relogin)
    ws.start()
    try:
        await _until(lambda: cloud.tokens == ["T1", "T2"])
        await _until(lambda: state.battery == 80)
    finally:
        await ws.stop()
    assert relogin.calls == 1  # exactly one login, for the reconnect; none for the first connection


async def test_first_connection_uses_the_given_token_and_does_not_log_in(cloud: FakeCloud) -> None:
    relogin = Relogin("UNUSED")
    ws, state = _ws(cloud, "T1", relogin)
    ws.start()
    try:
        await _until(lambda: state.battery == 80)
        await _REAL_SLEEP(0.3)  # several ping rounds on a healthy connection
    finally:
        await ws.stop()
    assert cloud.tokens == ["T1"]
    assert relogin.calls == 0


async def test_without_a_relogin_callable_the_old_token_is_reused(cloud: FakeCloud) -> None:
    """Back-compat: callers that pass no ``relogin`` keep the previous behaviour."""
    cloud.modes["T1"] = "close_after_data"
    ws, _ = _ws(cloud, "T1", relogin=None)
    ws.start()
    try:
        await _until(lambda: cloud.tokens[:2] == ["T1", "T1"])
    finally:
        await ws.stop()


async def test_a_failed_login_is_retried_not_fatal(cloud: FakeCloud) -> None:
    cloud.modes["T1"] = "close_after_data"
    relogin = Relogin("T2", fail_first=True)
    ws, state = _ws(cloud, "T1", relogin)
    ws.start()
    try:
        await _until(lambda: cloud.tokens == ["T1", "T2"])
        await _until(lambda: state.battery == 80)
    finally:
        await ws.stop()
    assert relogin.calls == 2  # the first login failed, the retry worked


# ---------------------------------------------------------------------------
# Mute connections
# ---------------------------------------------------------------------------


async def test_a_mute_connection_is_replaced_by_one_with_a_fresh_token(cloud: FakeCloud) -> None:
    """A WebSocket that is accepted but never delivers anything is replaced."""
    cloud.modes["DEAD"] = "silent"
    relogin = Relogin("T2")
    ws, state = _ws(cloud, "DEAD", relogin)
    ws.start()
    try:
        await _until(lambda: cloud.tokens == ["DEAD", "T2"])
        await _until(lambda: state.battery == 80)
    finally:
        await ws.stop()
    assert relogin.calls == 1


async def test_a_robot_that_is_off_does_not_cause_logins(cloud: FakeCloud) -> None:
    """No robot data, but the keepalive frames prove the connection is alive: no reconnect, no login.

    A login invalidates the other sessions of the account, so a false 'silent' verdict would
    mean kicking the other connector every minute for nothing.
    """
    cloud.modes["T1"] = "pongs_only"
    relogin = Relogin("UNUSED")
    ws, _ = _ws(cloud, "T1", relogin)
    ws.start()
    try:
        await _REAL_SLEEP(1.2)  # three times the silence timeout
    finally:
        await ws.stop()
    assert cloud.tokens == ["T1"]
    assert relogin.calls == 0


# ---------------------------------------------------------------------------
# otherlogin and logs
# ---------------------------------------------------------------------------


async def test_otherlogin_frame_is_logged_and_the_connection_stays_open(
    cloud: FakeCloud, caplog: pytest.LogCaptureFixture
) -> None:
    cloud.modes["T1"] = "otherlogin"
    relogin = Relogin("UNUSED")
    ws, state = _ws(cloud, "T1", relogin)
    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        ws.start()
        try:
            await _until(lambda: state.battery == 80)
            await _REAL_SLEEP(0.2)
        finally:
            await ws.stop()
    assert "another login took over" in caplog.text
    assert "secret-detail-of-the-frame" not in caplog.text  # the frame itself is not logged
    assert cloud.tokens == ["T1"] and relogin.calls == 0


async def test_the_token_never_reaches_the_log(
    cloud: FakeCloud, caplog: pytest.LogCaptureFixture
) -> None:
    cloud.modes["SECRET-TOKEN-ONE"] = "close_after_data"
    relogin = Relogin("SECRET-TOKEN-TWO")
    ws, state = _ws(cloud, "SECRET-TOKEN-ONE", relogin)
    with caplog.at_level(logging.DEBUG, logger=LOGGER_NAME):
        ws.start()
        try:
            await _until(lambda: cloud.tokens == ["SECRET-TOKEN-ONE", "SECRET-TOKEN-TWO"])
            await _until(lambda: state.battery == 80)
        finally:
            await ws.stop()
    assert "SECRET-TOKEN" not in caplog.text
    assert "websocketapp/oid/***" in caplog.text


# ---------------------------------------------------------------------------
# Back-off policy (pure)
# ---------------------------------------------------------------------------


def test_a_healthy_connection_that_ends_is_retried_quickly_and_resets_the_back_offs() -> None:
    delay, backoff, silent = _next_delay(
        "closed", lasted_s=3600, got_data=True, backoff=32, silent_backoff=300
    )
    assert delay == app_ws_module._RECONNECT_DELAY_S
    assert backoff == 2 * app_ws_module._RECONNECT_DELAY_S
    assert silent == app_ws_module._MIN_SILENT_BACKOFF_S


def test_connections_that_keep_dying_at_once_wait_longer_each_time_up_to_the_cap() -> None:
    backoff, silent = app_ws_module._RECONNECT_DELAY_S, app_ws_module._MIN_SILENT_BACKOFF_S
    delays = []
    for _ in range(6):
        delay, backoff, silent = _next_delay(
            "closed", lasted_s=0.0, got_data=False, backoff=backoff, silent_backoff=silent
        )
        delays.append(delay)
    assert delays == sorted(delays)  # never shorter than the one before
    assert delays[-1] == app_ws_module._MAX_BACKOFF_S  # and capped


def test_a_connection_that_stays_mute_from_the_start_is_retried_on_the_slow_schedule() -> None:
    silent = app_ws_module._MIN_SILENT_BACKOFF_S
    delays = []
    for _ in range(6):
        delay, _, silent = _next_delay(
            "silent", lasted_s=60.0, got_data=False, backoff=1.0, silent_backoff=silent
        )
        delays.append(delay)
    assert delays[0] == app_ws_module._MIN_SILENT_BACKOFF_S
    assert delays == sorted(delays)
    assert delays[-1] == app_ws_module._MAX_SILENT_BACKOFF_S


def test_a_connection_that_delivered_data_and_then_went_mute_is_retried_quickly() -> None:
    """Data was flowing, so the token was fine: this is a network drop, not a dead token."""
    delay, _, silent = _next_delay(
        "silent", lasted_s=500, got_data=True, backoff=8, silent_backoff=300
    )
    assert delay == app_ws_module._RECONNECT_DELAY_S
    assert silent == app_ws_module._MIN_SILENT_BACKOFF_S


# ---------------------------------------------------------------------------
# Wiring: client and connector
# ---------------------------------------------------------------------------

BASE_URL = "http://192.168.1.50:28080"


async def test_refresh_session_does_only_the_mobile_login_and_returns_the_new_token(
    httpx_mock: HTTPXMock,
) -> None:
    """Only /fleetapi/account/login is mocked: a call to /user/login (the web-console login) would fail the test."""
    httpx_mock.add_response(
        url=f"{BASE_URL}/fleetapi/account/login",
        json={
            "code": 890,
            "message": "success",
            "data": {"token": "fresh-tok", "openid": "user-openid"},
        },
    )
    client = AllybotAPIClient(
        base_url=BASE_URL, username="admin", password="secret", verify_ssl=False
    )
    client.mobile_token = "old-tok"
    try:
        assert await client.refresh_session() == ("user-openid", "fresh-tok")
        assert (
            client.mobile_token == "fresh-tok" and client.openid == "user-openid"
        )  # commands use the new one too
    finally:
        await client.close()


async def test_refresh_session_fails_loudly_when_the_login_gives_no_token(
    httpx_mock: HTTPXMock,
) -> None:
    httpx_mock.add_response(
        url=f"{BASE_URL}/fleetapi/account/login",
        json={"code": 507, "message": "CANNOT FIND USER", "data": None},
    )
    client = AllybotAPIClient(
        base_url=BASE_URL, username="admin", password="secret", verify_ssl=False
    )
    try:
        with pytest.raises(ValueError):
            await client.refresh_session()
    finally:
        await client.close()


async def test_connector_builds_its_websocket_with_the_clients_refresh_session() -> None:
    connector = AllybotConnector.__new__(AllybotConnector)
    connector._robot_states = {ROBOT_ID: AllybotRobotState()}
    connector._fleet_serial_to_robot_id = {SERIAL: ROBOT_ID}
    connector.config = SimpleNamespace(connector_config=SimpleNamespace(base_url=BASE_URL))
    client = AllybotAPIClient(
        base_url=BASE_URL, username="admin", password="secret", verify_ssl=False
    )
    client.openid, client.mobile_token = "oid", "tok"
    connector._api_client = client
    try:
        ws = connector._build_app_ws()
        assert ws._relogin == client.refresh_session
        assert ws._openid == "oid" and ws._token == "tok"
    finally:
        await client.close()


async def test_a_rejected_handshake_does_not_leak_the_token_through_the_error_text(
    cloud: FakeCloud, caplog: pytest.LogCaptureFixture
) -> None:
    """aiohttp's handshake error carries the full URL, token included; the log must not."""
    cloud.modes["SECRET-BAD"] = "reject"
    relogin = Relogin("GOOD")
    ws, state = _ws(cloud, "SECRET-BAD", relogin)
    with caplog.at_level(logging.DEBUG, logger=LOGGER_NAME):
        ws.start()
        try:
            await _until(lambda: state.battery == 80)  # rejected, then a fresh login works
        finally:
            await ws.stop()
    assert "App WS error" in caplog.text
    assert "SECRET-BAD" not in caplog.text


async def test_a_dead_token_that_the_server_closes_at_once_is_recovered_with_a_fresh_login(
    cloud: FakeCloud,
) -> None:
    """What the real cloud did with an invalidated token: accept, then close in ~1 s."""
    cloud.modes["DEAD"] = "close_at_once"
    relogin = Relogin("T2")
    ws, state = _ws(cloud, "DEAD", relogin)
    ws.start()
    try:
        await _until(lambda: cloud.tokens == ["DEAD", "T2"])
        await _until(lambda: state.battery == 80)
    finally:
        await ws.stop()
    assert relogin.calls == 1


async def _run_one_connection(cloud: FakeCloud, token: str) -> tuple[str, float, bool]:
    ws, _ = _ws(cloud, token)
    task = asyncio.create_task(ws._connect_once())
    await _REAL_SLEEP(0.3)  # several keepalives (a ping every 0.05 s)
    ws._stop_event.set()
    return await asyncio.wait_for(task, 2)


async def test_keepalive_frames_do_not_count_as_robot_data(cloud: FakeCloud) -> None:
    """The real server's keepalive has type 'ping' (the doc says 'pong'): neither is robot data."""
    cloud.modes["T1"] = "pongs_only"
    _, _, got_data = await _run_one_connection(cloud, "T1")
    assert got_data is False


async def test_a_devicestatus_frame_counts_as_robot_data(cloud: FakeCloud) -> None:
    cloud.modes["T1"] = "data"
    _, _, got_data = await _run_one_connection(cloud, "T1")
    assert got_data is True
