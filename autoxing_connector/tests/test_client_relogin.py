# SPDX-FileCopyrightText: 2026 Deliverance Enterprises
#
# SPDX-License-Identifier: MIT

"""The client logs in again after a 401, never more often than the minimum interval."""

from __future__ import annotations

import httpx

from autoxing_cloud_connector.src.api.client import AutoxingAPIClient


class FakeAutoxing:
    """Two-step login plus a robot state endpoint whose token can be revoked."""

    def __init__(self) -> None:
        self.logins = 0
        self.valid_token: str | None = None
        self.body_401 = False

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/user/v1.1/login":
            return httpx.Response(200, json={"status": 200, "data": {"token": "step1", "ticket": "tk"}})
        if path.startswith("/user/v1.0/ticket/"):
            self.logins += 1
            self.valid_token = f"jwt-{self.logins}"
            return httpx.Response(200, json={"status": 200, "data": {"token": self.valid_token, "expireTime": 604800}})
        if request.headers.get("X-Token") != self.valid_token:
            if self.body_401:
                return httpx.Response(200, json={"status": 401, "message": "token invalid"})
            return httpx.Response(401, json={"status": 401, "message": "token invalid"})
        return httpx.Response(200, json={"status": 200, "data": {"x": 1}})

    def revoke(self) -> None:
        self.valid_token = "someone-else"


def make_client(api: FakeAutoxing, interval: float = 60.0) -> tuple[AutoxingAPIClient, list[float]]:
    client = AutoxingAPIClient(
        base_url="https://api.example.com",
        login_name="user@example.com",
        password="secret",
        business_id="biz",
        login_appcode="a",
        api_appcode="b",
        relogin_min_interval=interval,
        transport=httpx.MockTransport(api.handler),
    )
    now = [1000.0]
    client._clock = lambda: now[0]
    return client, now


async def test_a_revoked_token_is_replaced_on_the_next_call() -> None:
    api = FakeAutoxing()
    client, now = make_client(api)
    await client.login()
    assert await client.get_robot_state("R1") == {"x": 1}

    api.revoke()
    now[0] += 61
    assert await client.get_robot_state("R1") is None  # the 401 itself
    assert await client.get_robot_state("R1") == {"x": 1}  # logged in again
    assert api.logins == 2
    await client.close()


async def test_logins_are_spaced_by_the_minimum_interval() -> None:
    api = FakeAutoxing()
    client, now = make_client(api, interval=60)
    await client.login()
    api.revoke()
    for _ in range(5):
        assert await client.get_robot_state("R1") is None
        now[0] += 10
    assert api.logins == 1  # 40 s after the first login: no new login yet
    now[0] += 20
    assert await client.get_robot_state("R1") == {"x": 1}
    assert api.logins == 2
    await client.close()


async def test_a_401_in_the_body_also_triggers_a_new_login() -> None:
    api = FakeAutoxing()
    api.body_401 = True
    client, now = make_client(api)
    await client.login()
    api.revoke()
    now[0] += 61
    assert await client.get_robot_state("R1") is None
    assert await client.get_robot_state("R1") == {"x": 1}
    assert api.logins == 2
    await client.close()


async def test_the_first_call_logs_in_without_waiting() -> None:
    api = FakeAutoxing()
    client, _ = make_client(api)
    assert await client.get_robot_state("R1") == {"x": 1}
    assert api.logins == 1
    await client.close()
