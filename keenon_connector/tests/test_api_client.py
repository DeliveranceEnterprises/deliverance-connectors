# SPDX-FileCopyrightText: 2026 Deliverance Enterprises
#
# SPDX-License-Identifier: MIT

"""Tests for keenon_connector.src.api.client."""

from __future__ import annotations

import pytest
from pytest_httpx import HTTPXMock

from keenon_connector.src.api.client import KeenonAPIClient

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
