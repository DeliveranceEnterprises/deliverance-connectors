# SPDX-FileCopyrightText: 2026 Deliverance Enterprises
#
# SPDX-License-Identifier: MIT

"""Tests for allybot_connector.src.api.client."""

from __future__ import annotations

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
