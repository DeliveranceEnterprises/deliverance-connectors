# SPDX-FileCopyrightText: 2026 Deliverance Enterprises
#
# SPDX-License-Identifier: MIT

"""Tests for allybot_connector.src.api.client."""

from __future__ import annotations

import asyncio
import base64

import pytest
from pytest_httpx import HTTPXMock

from allybot_connector.src.api.client import AllybotAPIClient

BASE_URL = "http://192.168.1.50:28080"
ROBOT_ID = "6d70603da0cb3d00ba104a191770170b"


@pytest.fixture()
async def client(httpx_mock: HTTPXMock):
    """Client with mobile login pre-mocked."""
    httpx_mock.add_response(
        url=f"{BASE_URL}/fleetapi/account/login",
        json={
            "code": 890,
            "message": "success",
            "data": {"token": "mobile-tok", "openid": "user-openid"},
        },
    )
    # REST login — returns no token in body (unknown location case)
    httpx_mock.add_response(
        url=f"{BASE_URL}/user/login",
        json={"code": 890, "message": "success", "data": {"userId": "u1"}},
    )
    c = AllybotAPIClient(
        base_url=BASE_URL,
        username="admin",
        password="secret",
        verify_ssl=False,
    )
    await c.login()
    yield c
    await c.close()


async def test_mobile_login_sets_token_and_openid(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url=f"{BASE_URL}/fleetapi/account/login",
        json={
            "code": 890,
            "message": "success",
            "data": {"token": "tok123", "openid": "oid456"},
        },
    )
    httpx_mock.add_response(
        url=f"{BASE_URL}/user/login",
        json={"code": 890, "message": "success", "data": {}},
    )
    c = AllybotAPIClient(base_url=BASE_URL, username="u", password="p", verify_ssl=False)
    await c.login()
    assert c.mobile_token == "tok123"
    assert c.openid == "oid456"
    await c.close()


async def test_mobile_login_sends_base64_password(httpx_mock: HTTPXMock) -> None:
    """The mobile login must base64-encode the password."""
    httpx_mock.add_response(
        url=f"{BASE_URL}/fleetapi/account/login",
        json={
            "code": 890,
            "message": "success",
            "data": {"token": "t", "openid": "o"},
        },
    )
    httpx_mock.add_response(
        url=f"{BASE_URL}/user/login",
        json={"code": 890, "message": "success", "data": {}},
    )
    c = AllybotAPIClient(base_url=BASE_URL, username="u", password="secret", verify_ssl=False)
    await c.login()

    # Inspect the captured request body
    login_requests = [r for r in httpx_mock.get_requests() if "account/login" in str(r.url)]
    assert login_requests, "No request to /fleetapi/account/login was captured"
    body = login_requests[0].content.decode()
    expected_b64 = base64.b64encode(b"secret").decode()
    assert f"password={expected_b64}" in body
    await c.close()


async def test_rest_login_extracts_token_from_header(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url=f"{BASE_URL}/fleetapi/account/login",
        json={
            "code": 890,
            "message": "success",
            "data": {"token": "t", "openid": "o"},
        },
    )
    httpx_mock.add_response(
        url=f"{BASE_URL}/user/login",
        headers={"x-token": "jwt-from-header"},
        json={"code": 890, "message": "success", "data": {}},
    )
    c = AllybotAPIClient(base_url=BASE_URL, username="u", password="p", verify_ssl=False)
    await c.login()
    assert c._x_token == "jwt-from-header"
    await c.close()


async def test_rest_login_failure_does_not_raise(httpx_mock: HTTPXMock) -> None:
    """REST login failure is non-fatal — only mobile login is required."""
    httpx_mock.add_response(
        url=f"{BASE_URL}/fleetapi/account/login",
        json={
            "code": 890,
            "message": "success",
            "data": {"token": "t", "openid": "o"},
        },
    )
    httpx_mock.add_response(url=f"{BASE_URL}/user/login", status_code=500)
    c = AllybotAPIClient(base_url=BASE_URL, username="u", password="p", verify_ssl=False)
    await c.login()  # must not raise
    assert c._x_token is None
    await c.close()


async def test_get_active_map_returns_mapinfo(client: AllybotAPIClient, httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url=f"{BASE_URL}/fleetapi/device/usemap",
        json={
            "code": 200,
            "message": "SUCCESS",
            "data": {
                "mapinfo": {
                    "id": "map-uuid",
                    "name": "DELIVERANCE",
                    "original": {"x": -6.55, "y": -3.24, "z": 0},
                    "resolution": 0.05,
                },
                "image_url": f"{BASE_URL}/resource/map/20250704/map.png",
                "robot_name": "202352CNW002D0156",
            },
        },
    )
    data = await client.get_active_map(ROBOT_ID)
    assert data["mapinfo"]["id"] == "map-uuid"
    assert data["mapinfo"]["resolution"] == 0.05


async def test_get_robot_info_skipped_without_x_token(
    client: AllybotAPIClient,
) -> None:
    """get_robot_info returns None when REST auth is unavailable."""
    client._x_token = None
    result = await client.get_robot_info(ROBOT_ID)
    assert result is None


async def test_get_robot_info_returns_data(
    client: AllybotAPIClient, httpx_mock: HTTPXMock
) -> None:
    client._x_token = "jwt-tok"
    httpx_mock.add_response(
        url=f"{BASE_URL}/robot/singleRobotInfo?robotId={ROBOT_ID}",
        json={
            "code": 619,
            "message": "success",
            "data": {
                "robotId": ROBOT_ID,
                "robotName": "Cleaner-1",
                "aliveStatus": 2,
            },
        },
    )
    info = await client.get_robot_info(ROBOT_ID)
    assert info["robotName"] == "Cleaner-1"
    assert info["aliveStatus"] == 2


# ---------------------------------------------------------------------------
# Session lost ("LOGGED IN SOMEWHERE ELSE"): commands log in again and retry once
# ---------------------------------------------------------------------------


_real_sleep = asyncio.sleep


async def _instant_sleep(_delay: float, *_a, **_k) -> None:
    await _real_sleep(0)


def _mock_logins(httpx_mock: HTTPXMock, token: str) -> None:
    httpx_mock.add_response(
        url=f"{BASE_URL}/fleetapi/account/login",
        json={"code": 890, "message": "success", "data": {"token": token, "openid": "oid"}},
    )
    httpx_mock.add_response(
        url=f"{BASE_URL}/user/login",
        json={"code": 890, "message": "success", "data": {}},
    )


def _mock_mobile_login(httpx_mock: HTTPXMock, token: str) -> None:
    httpx_mock.add_response(
        url=f"{BASE_URL}/fleetapi/account/login",
        json={"code": 890, "message": "success", "data": {"token": token, "openid": "oid"}},
    )


async def test_start_task_relogs_in_and_retries_when_session_was_killed(
    httpx_mock: HTTPXMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(asyncio, "sleep", _instant_sleep)  # start_task waits 2 s for the path plan
    _mock_logins(httpx_mock, "old-token")
    c = AllybotAPIClient(base_url=BASE_URL, username="u", password="p", verify_ssl=False)
    await c.login()

    httpx_mock.add_response(
        url=f"{BASE_URL}/fleetapi/task/plan/reachable?robotId={ROBOT_ID}&taskId=t1&planId=",
        json={"code": 200, "message": "success"},
        is_reusable=True,
    )
    # 1st dispatch: the cloud says another login killed our session.
    httpx_mock.add_response(
        url=f"{BASE_URL}/fleetapi/clean/default/start",
        json={"code": 200, "message": "LOGGED IN SOMEWHERE ELSE", "data": None},
    )
    c._last_login_at -= 61  # the minimum interval between logins has passed
    _mock_mobile_login(httpx_mock, "new-token")  # the re-login (mobile only)
    # 2nd dispatch, with the fresh session: accepted.
    httpx_mock.add_response(
        url=f"{BASE_URL}/fleetapi/clean/default/start",
        json={"code": 200, "message": "success", "data": True},
    )
    await c.start_task(ROBOT_ID, "t1")

    assert c.mobile_token == "new-token"
    await c.close()


async def test_start_task_does_not_retry_on_other_rejections(
    httpx_mock: HTTPXMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(asyncio, "sleep", _instant_sleep)
    _mock_logins(httpx_mock, "tok")
    c = AllybotAPIClient(base_url=BASE_URL, username="u", password="p", verify_ssl=False)
    await c.login()
    httpx_mock.add_response(
        url=f"{BASE_URL}/fleetapi/task/plan/reachable?robotId={ROBOT_ID}&taskId=t1&planId=",
        json={"code": 200, "message": "success"},
    )
    httpx_mock.add_response(
        url=f"{BASE_URL}/fleetapi/clean/default/start",
        json={"code": 200, "message": "Failed to start from the charging pile", "data": 1149},
    )
    with pytest.raises(ValueError, match="rejected by robot"):
        await c.start_task(ROBOT_ID, "t1")
    assert c.mobile_token == "tok"  # no re-login for an unrelated rejection
    await c.close()


def test_is_session_lost_detects_message_and_code() -> None:
    from allybot_connector.src.api.client import _is_session_lost

    assert _is_session_lost("LOGGED IN SOMEWHERE ELSE")
    assert _is_session_lost("anything", 505)
    assert not _is_session_lost("Failed to start from the charging pile", 1149)
    assert not _is_session_lost(None)


# ---------------------------------------------------------------------------
# Minimum interval between logins (shared by WebSocket reconnects and commands)
# ---------------------------------------------------------------------------


def _session_lost_on_pause(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url=f"{BASE_URL}/fleetapi/device/taskaction?openid=oid&token=tok&id={ROBOT_ID}&type=1",
        json={"code": 505, "message": "LOGGED IN SOMEWHERE ELSE", "data": None},
    )


async def test_a_command_does_not_log_in_again_within_the_minimum_interval(
    httpx_mock: HTTPXMock,
) -> None:
    """Another process logged in right after us: logging in again now would start a login storm."""
    from allybot_connector.src.api.client import AllybotSessionExpired

    _mock_logins(httpx_mock, "tok")
    c = AllybotAPIClient(base_url=BASE_URL, username="u", password="p", verify_ssl=False)
    await c.login()
    _session_lost_on_pause(httpx_mock)
    with pytest.raises(AllybotSessionExpired, match="less than 60s ago"):
        await c.task_action(ROBOT_ID, 1)
    assert c.mobile_token == "tok"  # no login was sent (an unexpected request fails the test)
    await c.close()


async def test_a_command_retries_with_the_token_of_a_newer_login_without_logging_in(
    httpx_mock: HTTPXMock,
) -> None:
    """The WebSocket logged in while the command was in flight: its token is reused, no extra login."""
    _mock_logins(httpx_mock, "tok")
    c = AllybotAPIClient(base_url=BASE_URL, username="u", password="p", verify_ssl=False)
    await c.login()

    def pause_response(request):
        import httpx

        if "token=tok&" in str(request.url):
            c.mobile_token = "newer-tok"  # a reconnect logged in meanwhile
            return httpx.Response(200, json={"code": 505, "message": "LOGGED IN SOMEWHERE ELSE"})
        return httpx.Response(200, json={"code": 200, "message": "success", "data": True})

    httpx_mock.add_callback(pause_response, is_reusable=True)
    await c.task_action(ROBOT_ID, 1)
    assert c.mobile_token == "newer-tok"
    await c.close()


async def test_refresh_session_waits_for_the_rest_of_the_minimum_interval(
    httpx_mock: HTTPXMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    waits: list[float] = []

    async def record_sleep(delay: float, *_a, **_k) -> None:
        waits.append(delay)

    _mock_logins(httpx_mock, "tok")
    c = AllybotAPIClient(
        base_url=BASE_URL, username="u", password="p", verify_ssl=False, min_relogin_s=60
    )
    await c.login()
    c._last_login_at -= 20  # the last login was 20 s ago
    _mock_mobile_login(httpx_mock, "fresh")
    monkeypatch.setattr(asyncio, "sleep", record_sleep)
    assert await c.refresh_session() == ("oid", "fresh")
    assert len(waits) == 1 and 39 <= waits[0] <= 40
    await c.close()


async def test_refresh_session_does_not_wait_once_the_interval_has_passed(
    httpx_mock: HTTPXMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    waits: list[float] = []

    async def record_sleep(delay: float, *_a, **_k) -> None:
        waits.append(delay)

    _mock_logins(httpx_mock, "tok")
    c = AllybotAPIClient(base_url=BASE_URL, username="u", password="p", verify_ssl=False)
    await c.login()
    c._last_login_at -= 61
    _mock_mobile_login(httpx_mock, "fresh")
    monkeypatch.setattr(asyncio, "sleep", record_sleep)
    assert await c.refresh_session() == ("oid", "fresh")
    assert waits == []
    await c.close()


async def test_a_failed_login_also_counts_for_the_minimum_interval(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url=f"{BASE_URL}/fleetapi/account/login",
        json={"code": 507, "message": "CANNOT FIND USER", "data": None},
    )
    c = AllybotAPIClient(base_url=BASE_URL, username="u", password="p", verify_ssl=False)
    with pytest.raises(ValueError):
        await c.refresh_session()
    assert c._relogin_wait_s() > 59
    await c.close()


# ---------------------------------------------------------------------------
# device/status (emergency stop), polled without ever logging in
# ---------------------------------------------------------------------------


async def test_get_device_status_returns_the_chassis_status(
    client: AllybotAPIClient, httpx_mock: HTTPXMock
) -> None:
    httpx_mock.add_response(
        url=f"{BASE_URL}/fleetapi/device/status",
        json={
            "code": 200,
            "message": "success",
            "data": {"chassisStatus": {"emergencyStop": False, "emergencyStopManual": True}},
        },
    )
    data = await client.get_device_status(ROBOT_ID)
    assert data == {"chassisStatus": {"emergencyStop": False, "emergencyStopManual": True}}
    body = httpx_mock.get_requests()[-1].content.decode()
    assert f"id={ROBOT_ID}" in body and f"robotId={ROBOT_ID}" in body


async def test_get_device_status_with_a_lost_session_returns_none_and_does_not_log_in(
    client: AllybotAPIClient, httpx_mock: HTTPXMock
) -> None:
    httpx_mock.add_response(
        url=f"{BASE_URL}/fleetapi/device/status",
        json={"code": 505, "message": "LOGGED IN SOMEWHERE ELSE", "data": None},
    )
    assert await client.get_device_status(ROBOT_ID) is None
    assert client.mobile_token == "mobile-tok"  # no login (an unexpected request fails the test)
