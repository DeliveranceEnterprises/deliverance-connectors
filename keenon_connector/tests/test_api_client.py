# SPDX-FileCopyrightText: 2026 Deliverance Enterprises
#
# SPDX-License-Identifier: MIT

"""Tests for keenon_connector.src.api.client."""

from __future__ import annotations

import asyncio

import httpx
import pytest
from pytest_httpx import HTTPXMock

from keenon_connector.src.api.client import (
    KeenonAPIClient,
    KeenonAPIError,
    KeenonAuthError,
    KeenonRateLimitError,
)

BASE_URL = "https://es.robotkeenon.com"

TOKEN_RESPONSE = {
    "access_token": "test-token-abc",
    "token_type": "bearer",
    "expires_in": 7200,
    "scope": "all",
}

SUCCESS_WRAPPER = {"code": 610000, "msg": "Request successful", "data": {}}


@pytest.fixture()
async def client(httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        url=f"{BASE_URL}/api/open/oauth/token",
        json=TOKEN_RESPONSE,
    )
    c = KeenonAPIClient(
        api_domain=BASE_URL,
        client_id="cid",
        client_secret="csec",
    )
    yield c
    await c.close()


async def test_token_acquired_on_first_request(
    client: KeenonAPIClient, httpx_mock: HTTPXMock
) -> None:
    httpx_mock.add_response(
        url=f"{BASE_URL}/api/open/data/v1/store/robot/list?storeId=S1",
        json={"code": 610000, "msg": "ok", "data": []},
    )
    robots = await client.get_robot_list("S1")
    assert robots == []


async def test_get_robot_list_returns_list(
    client: KeenonAPIClient, httpx_mock: HTTPXMock
) -> None:
    robots_payload = [
        {
            "robotId": "AA:BB:CC:DD:EE:FF",
            "robotName": "Test Robot",
            "onlineStatus": 1,
            "power": 85,
            "robotModel": "T2",
            "appVersion": "v1.4.4",
            "onlineType": 2,
        }
    ]
    httpx_mock.add_response(
        url=f"{BASE_URL}/api/open/data/v1/store/robot/list?storeId=S1",
        json={"code": 610000, "msg": "ok", "data": robots_payload},
    )
    robots = await client.get_robot_list("S1")
    assert len(robots) == 1
    assert robots[0]["robotId"] == "AA:BB:CC:DD:EE:FF"


async def test_get_robot_status_extracts_list(
    client: KeenonAPIClient, httpx_mock: HTTPXMock
) -> None:
    status_payload = {
        "list": [
            {
                "robotId": "AA:BB:CC:DD:EE:FF",
                "onlineStatus": True,
                "canBeCalled": True,
                "chargeStatus": -1,
                "power": 85,
                "sceneCode": "abc123",
                "sceneName": "Floor 1",
            }
        ]
    }
    httpx_mock.add_response(
        url=f"{BASE_URL}/api/open/scene/v1/robot/status?robotId=AA%3ABB%3ACC%3ADD%3AEE%3AFF",
        json={"code": 610000, "msg": "ok", "data": status_payload},
    )
    result = await client.get_robot_status("AA:BB:CC:DD:EE:FF")
    assert len(result) == 1
    assert result[0]["sceneCode"] == "abc123"


async def test_get_robot_location_parses_coordinate(
    client: KeenonAPIClient, httpx_mock: HTTPXMock
) -> None:
    httpx_mock.add_response(
        url=f"{BASE_URL}/api/open/custom/robot/location?robotSn=AA%3ABB%3ACC%3ADD%3AEE%3AFF",
        json={
            "code": 610000,
            "msg": "ok",
            "data": {
                "building": "",
                "floor": 1,
                "coordinate": "-8.22,12.07,90.0",
                "takeElevatorStatus": 0,
            },
        },
    )
    loc = await client.get_robot_location("AA:BB:CC:DD:EE:FF")
    assert loc["coordinate"] == "-8.22,12.07,90.0"
    assert loc["floor"] == 1


async def test_token_refresh_on_expired_code(
    httpx_mock: HTTPXMock,
) -> None:
    """A 610401 response triggers a token refresh and one retry."""
    httpx_mock.add_response(
        url=f"{BASE_URL}/api/open/oauth/token",
        json=TOKEN_RESPONSE,
    )
    # First call returns expired-token error
    httpx_mock.add_response(
        url=f"{BASE_URL}/api/open/data/v1/store/robot/list?storeId=S1",
        json={"code": 610401, "msg": "Token verification failed"},
    )
    # Token refresh
    httpx_mock.add_response(
        url=f"{BASE_URL}/api/open/oauth/token",
        json={**TOKEN_RESPONSE, "access_token": "refreshed-token"},
    )
    # Retry succeeds
    httpx_mock.add_response(
        url=f"{BASE_URL}/api/open/data/v1/store/robot/list?storeId=S1",
        json={"code": 610000, "msg": "ok", "data": []},
    )
    c = KeenonAPIClient(api_domain=BASE_URL, client_id="cid", client_secret="csec")
    try:
        robots = await c.get_robot_list("S1")
        assert robots == []
    finally:
        await c.close()


async def test_api_error_raises_value_error(
    client: KeenonAPIClient, httpx_mock: HTTPXMock
) -> None:
    httpx_mock.add_response(
        url=f"{BASE_URL}/api/open/data/v1/store/robot/list?storeId=S1",
        json={"code": 610500, "msg": "Server exception"},
    )
    with pytest.raises(ValueError, match="610500"):
        await client.get_robot_list("S1")


async def test_call_to_point_returns_task_no(
    client: KeenonAPIClient, httpx_mock: HTTPXMock
) -> None:
    httpx_mock.add_response(
        url=f"{BASE_URL}/api/open/scene/v3/robot/call/task",
        json={"code": 610000, "msg": "ok", "data": {"taskNo": "task-001", "waitQueuing": 0}},
    )
    task_no = await client.call_to_point(
        uuid="uuid-1",
        point_id="pt-1",
        store_id="S1",
        robot_id="AA:BB:CC:DD:EE:FF",
    )
    assert task_no == "task-001"


async def test_cancel_task(client: KeenonAPIClient, httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url=f"{BASE_URL}/api/open/scene/v1/robot/call/task?taskNo=task-001",
        json={"code": 610000, "msg": "ok", "data": None},
    )
    await client.cancel_task("task-001")  # should not raise


# ---------------------------------------------------------------------------
# Session resilience: re-login, rate limit, connection pool
# ---------------------------------------------------------------------------

LIST_URL = f"{BASE_URL}/api/open/data/v1/store/robot/list?storeId=S1"
TOKEN_URL = f"{BASE_URL}/api/open/oauth/token"
OK_LIST = {"code": 610000, "msg": "ok", "data": []}


def _token_requests(httpx_mock: HTTPXMock) -> int:
    return len(httpx_mock.get_requests(url=TOKEN_URL))


async def test_business_errors_keep_the_token(
    client: KeenonAPIClient, httpx_mock: HTTPXMock
) -> None:
    """Non-auth API errors never drop the token or trigger a login."""
    for _ in range(4):
        httpx_mock.add_response(url=LIST_URL, json={"code": 610500, "msg": "Server exception"})
    httpx_mock.add_response(url=LIST_URL, json=OK_LIST)
    for _ in range(4):
        with pytest.raises(KeenonAPIError):
            await client.get_robot_list("S1")
    assert await client.get_robot_list("S1") == []
    assert _token_requests(httpx_mock) == 1


async def test_http_401_logs_in_again_once(
    client: KeenonAPIClient, httpx_mock: HTTPXMock
) -> None:
    httpx_mock.add_response(url=LIST_URL, json=OK_LIST)
    httpx_mock.add_response(url=LIST_URL, status_code=401, json={"error": "invalid_token"})
    httpx_mock.add_response(url=TOKEN_URL, json={**TOKEN_RESPONSE, "access_token": "new-token"})
    httpx_mock.add_response(url=LIST_URL, json=OK_LIST)

    await client.get_robot_list("S1")
    assert await client.get_robot_list("S1") == []
    assert _token_requests(httpx_mock) == 2
    assert httpx_mock.get_requests(url=LIST_URL)[-1].headers["Authorization"] == "bearer new-token"


async def test_repeated_auth_rejection_backs_off_logins(httpx_mock: HTTPXMock) -> None:
    """A token rejected again right after a fresh login (e.g. the same app logged
    in elsewhere) holds back further logins instead of logging in on every request."""
    httpx_mock.add_response(url=TOKEN_URL, json=TOKEN_RESPONSE)
    httpx_mock.add_response(url=LIST_URL, status_code=401)
    httpx_mock.add_response(url=TOKEN_URL, json=TOKEN_RESPONSE)
    httpx_mock.add_response(url=LIST_URL, json={"code": 610401, "msg": "Token verification failed"})
    c = KeenonAPIClient(
        api_domain=BASE_URL, client_id="cid", client_secret="csec", login_backoff_min_s=60.0
    )
    try:
        with pytest.raises(KeenonAuthError):
            await c.get_robot_list("S1")
        # Within the backoff: no login and no request at all.
        for _ in range(3):
            with pytest.raises(KeenonAuthError, match="held back"):
                await c.get_robot_list("S1")
        assert _token_requests(httpx_mock) == 2
        assert len(httpx_mock.get_requests(url=LIST_URL)) == 2
    finally:
        await c.close()


async def test_failed_login_backs_off_exponentially(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=TOKEN_URL, status_code=401, json={"error": "invalid_client"})
    c = KeenonAPIClient(
        api_domain=BASE_URL, client_id="cid", client_secret="bad",
        login_backoff_min_s=60.0, login_backoff_max_s=900.0,
    )
    try:
        with pytest.raises(KeenonAuthError, match="login failed"):
            await c.get_robot_list("S1")
        with pytest.raises(KeenonAuthError, match="held back"):
            await c.get_robot_list("S1")
        assert 59 < c._login_backoff_remaining() <= 60
        c._auth_failures = 3
        assert 239 < c._login_backoff_remaining() <= 240
        c._auth_failures = 10
        assert c._login_backoff_remaining() <= 900
        assert _token_requests(httpx_mock) == 1
    finally:
        await c.close()


async def test_rate_limit_backs_off_without_login(
    client: KeenonAPIClient, httpx_mock: HTTPXMock, monkeypatch
) -> None:
    from keenon_connector.src.api import client as client_module

    sleeps: list[float] = []

    async def fake_sleep(delay):
        sleeps.append(delay)

    monkeypatch.setattr(client_module.asyncio, "sleep", fake_sleep)
    httpx_mock.add_response(url=LIST_URL, json={"code": 610609, "msg": "Interface calls too frequent"})
    httpx_mock.add_response(url=LIST_URL, json=OK_LIST)

    with pytest.raises(KeenonRateLimitError):
        await client.get_robot_list("S1")
    assert await client.get_robot_list("S1") == []
    assert sleeps and 0 < sleeps[0] <= 2.0  # waited before the next request
    assert _token_requests(httpx_mock) == 1
    assert client._access_token == "test-token-abc"


async def test_transport_errors_swap_the_pool_without_closing_in_flight_requests(
    httpx_mock: HTTPXMock,
) -> None:
    release = asyncio.Event()

    async def slow_response(request: httpx.Request) -> httpx.Response:
        await release.wait()
        return httpx.Response(200, json=OK_LIST)

    slow_url = f"{BASE_URL}/slow"
    httpx_mock.add_callback(slow_response, url=slow_url)
    for _ in range(3):
        httpx_mock.add_exception(httpx.ConnectError("connection refused"), url=f"{BASE_URL}/fail")

    c = KeenonAPIClient(api_domain=BASE_URL, client_id="cid", client_secret="csec")
    old_pool = c._http
    try:
        in_flight = asyncio.create_task(c._send("GET", "/slow"))
        await asyncio.sleep(0)
        for _ in range(3):
            with pytest.raises(httpx.ConnectError):
                await c._send("GET", "/fail")
        assert c._http is not old_pool  # new requests use a fresh pool
        assert not old_pool.is_closed  # still serving the in-flight request
        release.set()
        resp = await in_flight
        assert resp.status_code == 200
        assert old_pool.is_closed  # closed once its last request finished
    finally:
        await c.close()
