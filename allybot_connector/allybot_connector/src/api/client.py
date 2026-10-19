# SPDX-FileCopyrightText: 2026 Deliverance Enterprises
#
# SPDX-License-Identifier: MIT

"""REST client for the Ally Fleet Robot API with dual-auth support."""

import asyncio
import base64
import logging

import httpx
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

logger = logging.getLogger(__name__)

ALLYBOT_SUCCESS = 619  # most common success code; some endpoints use others
# A response is successful when message == "success" regardless of code variance.

SESSION_LOST_CODE = 505  # "LOGGED IN SOMEWHERE ELSE"


class AllybotSessionExpired(ValueError):
    """Another login invalidated this client's session.

    The Allybot cloud keeps ONE session per account: any other login (the phone
    app, another connector instance, a script) silently kills ours. Every call
    that needs the token then fails until we log in again. Subclasses ValueError
    so existing handlers that catch ValueError keep working.
    """


def _is_session_lost(message: str | None, code: int | None = None) -> bool:
    return code == SESSION_LOST_CODE or "logged in somewhere else" in (message or "").lower()


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, (httpx.TimeoutException, httpx.ConnectError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in (408, 429, 500, 502, 503, 504)
    return False


def _retry():
    return retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential_jitter(initial=1, max=10),
        retry=retry_if_exception(_is_retryable),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )


class AllybotAPIClient:
    """Async REST client for the Ally Fleet Robot API.

    Maintains two independent auth sessions:
    - **Mobile Fleet auth** (``/fleetapi/account/login``): always performed; provides
      ``token`` + ``openid`` for the App WebSocket URL and ``/fleetapi/*`` endpoints.
    - **Regular REST auth** (``/user/login``): attempted opportunistically; provides
      an ``x-token`` JWT for ``/robot/*``, ``/map/*``, ``/task/*`` endpoints.
      If this login fails or returns no token, REST metadata endpoints are skipped
      gracefully.
    """

    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        verify_ssl: bool = True,
        timeout: float = 30.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._username = username
        self._password = password
        self._http = httpx.AsyncClient(
            base_url=self._base_url,
            verify=verify_ssl,
            timeout=timeout,
        )
        # Mobile Fleet auth
        self.mobile_token: str | None = None
        self.openid: str | None = None
        # Regular REST auth
        self._x_token: str | None = None

    async def close(self) -> None:
        await self._http.aclose()

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    async def login(self) -> None:
        """Perform both mobile and REST logins."""
        await self._mobile_login()
        await self._rest_login()

    async def _mobile_login(self) -> None:
        """POST /fleetapi/account/login with base64-encoded password."""
        password_b64 = base64.b64encode(self._password.encode()).decode()
        resp = await self._http.post(
            "/fleetapi/account/login",
            headers={"X-Api-Version": "184"},
            data={"username": self._username, "password": password_b64},
        )
        resp.raise_for_status()
        body = resp.json()
        data = body.get("data") or {}
        self.mobile_token = data.get("token")
        self.openid = data.get("openid")
        if not self.mobile_token or not self.openid:
            raise ValueError(
                f"Mobile login succeeded but returned no token/openid: {body}"
            )
        logger.debug("Mobile auth OK (openid=%s)", self.openid)

    async def _rest_login(self) -> None:
        """POST /user/login — JWT may be in header or body; try both."""
        try:
            resp = await self._http.post(
                "/user/login",
                json={"account": self._username, "password": self._password},
            )
            resp.raise_for_status()
            # Check response header first (some versions put JWT there)
            token = resp.headers.get("x-token")
            if not token:
                body = resp.json()
                data = body.get("data")
                if isinstance(data, str):
                    token = data
                elif isinstance(data, dict):
                    token = data.get("token") or data.get("x-token")
            self._x_token = token or None
            if self._x_token:
                logger.debug("REST auth OK (x-token acquired)")
            else:
                logger.warning(
                    "REST login succeeded but no JWT found — "
                    "/robot/* endpoints will be skipped"
                )
        except Exception as exc:
            logger.warning("REST login failed: %s — /robot/* endpoints will be skipped", exc)
            self._x_token = None

    def _rest_headers(self) -> dict[str, str]:
        return {"x-token": self._x_token} if self._x_token else {}

    def _mobile_headers(self) -> dict[str, str]:
        return {
            "Token": self.mobile_token or "",
            "Mobile-User-Id": self.openid or "",
            "X-Api-Version": "184",
            "Language": "en_US",
        }

    # ------------------------------------------------------------------
    # Internal request helpers
    # ------------------------------------------------------------------

    def _is_success(self, body: dict) -> bool:
        return body.get("message", "").lower() == "success" or body.get("code") == 200

    def _api_error(self, path: str, body: dict) -> ValueError:
        message, code = body.get("message"), body.get("code")
        text = f"Allybot API error on {path}: {message} ({code})"
        if _is_session_lost(message, code):
            return AllybotSessionExpired(text)
        return ValueError(text)

    @_retry()
    async def _get(self, path: str, headers: dict, **kwargs) -> dict | list | None:
        resp = await self._http.get(path, headers=headers, **kwargs)
        if resp.status_code in (401, 403):
            logger.warning("Auth error on %s — session may have expired", path)
        resp.raise_for_status()
        body = resp.json()
        if not self._is_success(body):
            raise self._api_error(path, body)
        return body.get("data")

    @_retry()
    async def _post(self, path: str, headers: dict, **kwargs) -> dict | list | None:
        resp = await self._http.post(path, headers=headers, **kwargs)
        resp.raise_for_status()
        body = resp.json()
        if not self._is_success(body):
            raise self._api_error(path, body)
        return body.get("data")

    async def _with_relogin(self, call):
        """Run a command; if our session was killed, log in again and retry ONCE.

        Only commands use this (start/pause/resume/stop). Polling deliberately does
        not: a background poll re-logging in every minute would fight any other
        session (e.g. someone using the phone app) and keep kicking it out. A
        command is an explicit request, so taking the session back is intended.
        """
        try:
            return await call()
        except AllybotSessionExpired:
            logger.warning("Allybot session lost (another login) — logging in again and retrying once")
            await self.login()
            return await call()

    # ------------------------------------------------------------------
    # Data endpoints
    # ------------------------------------------------------------------

    async def get_robot_info(self, robot_id: str) -> dict | None:
        """GET /robot/singleRobotInfo — requires REST auth."""
        if not self._x_token:
            return None
        try:
            return await self._get(
                "/robot/singleRobotInfo",
                headers=self._rest_headers(),
                params={"robotId": robot_id},
            )
        except Exception as exc:
            logger.warning("get_robot_info(%s) failed: %s", robot_id, exc)
            return None

    async def get_active_map(self, device_id: str) -> dict | None:
        """POST /fleetapi/device/usemap — returns active map metadata + image URL."""
        try:
            return await self._post(
                "/fleetapi/device/usemap",
                headers=self._mobile_headers(),
                data={
                    "openid": self.openid,
                    "token": self.mobile_token,
                    "id": device_id,
                },
            )
        except Exception as exc:
            logger.warning("get_active_map(%s) failed: %s", device_id, exc)
            return None

    async def fetch_map_image(self, image_url: str) -> bytes | None:
        """Fetch the map PNG from a full URL (may be on the same host)."""
        try:
            resp = await self._http.get(image_url)
            resp.raise_for_status()
            return resp.content
        except Exception as exc:
            logger.warning("fetch_map_image(%s) failed: %s", image_url, exc)
            return None

    # ------------------------------------------------------------------
    # Task control endpoints (mobile auth)
    # ------------------------------------------------------------------

    async def list_tasks(self, device_id: str) -> list[dict]:
        """POST /fleetapi/clean/list — returns available cleaning tasks for a robot."""
        try:
            data = await self._post(
                "/fleetapi/clean/list",
                headers=self._mobile_headers(),
                data={
                    "id": device_id,
                    "page": 1,
                    "pageSize": 20,
                    "type": 0,
                    "openid": self.openid,
                    "token": self.mobile_token,
                },
            )
            if isinstance(data, list):
                return data
            return []
        except Exception as exc:
            logger.warning("list_tasks(%s) failed: %s", device_id, exc)
            return []

    async def _check_task_reachable(self, device_id: str, task_id: str) -> None:
        """GET /fleetapi/task/plan/reachable — triggers server-side path planning.

        The mobile app always calls this before clean/default/start.  Skipping it
        causes the server to return error 1149 ("Failed to start from the charging
        pile").  The endpoint always returns code 200; the message field carries
        any human-readable warning (e.g. map mismatch) which we log.
        """
        try:
            resp = await self._http.get(
                "/fleetapi/task/plan/reachable",
                headers=self._mobile_headers(),
                params={"robotId": device_id, "taskId": task_id, "planId": ""},
            )
            resp.raise_for_status()
            body = resp.json()
            msg = body.get("message", "")
            if msg.lower() != "success":
                logger.warning("Task reachability check: %s", msg)
        except Exception as exc:
            logger.warning("check_task_reachable failed (proceeding anyway): %s", exc)

    async def get_device_status(self, device_id: str) -> dict | None:
        """POST /fleetapi/device/usestatus — snapshot of robot state including location flag."""
        try:
            return await self._post(
                "/fleetapi/device/usestatus",
                headers=self._mobile_headers(),
                data={
                    "openid": self.openid,
                    "token": self.mobile_token,
                    "id": device_id,
                },
            )
        except Exception as exc:
            logger.warning("get_device_status(%s) failed: %s", device_id, exc)
            return None

    async def start_task(
        self,
        device_id: str,
        task_id: str,
        reach_charge_point: bool = True,
    ) -> None:
        """POST /fleetapi/clean/default/start — dispatches a cleaning task to the robot.

        Raises ValueError if the API rejects the task. If the rejection is because
        another login killed our session, logs in again and retries once.
        """
        await self._with_relogin(
            lambda: self._start_task_once(device_id, task_id, reach_charge_point)
        )

    async def _start_task_once(
        self, device_id: str, task_id: str, reach_charge_point: bool
    ) -> None:
        await self._check_task_reachable(device_id, task_id)
        # The mobile app waits ~2 s after the reachability check before dispatching —
        # the server needs this time to pre-compute the path plan.
        await asyncio.sleep(2.0)

        resp = await self._http.post(
            "/fleetapi/clean/default/start",
            headers=self._mobile_headers(),
            data={
                "id": device_id,
                "taskId": task_id,
                "reachChargePoint": str(reach_charge_point).lower(),
                "openid": self.openid,
                "token": self.mobile_token,
            },
        )
        resp.raise_for_status()
        body = resp.json()
        # Success: data is boolean True.  Failure: data is an integer error code
        # (e.g. 1146 = not localized, 1149 = path planning failed) even when code=200.
        data = body.get("data")
        if data is not True:
            msg = body.get("message", "unknown error")
            text = f"Task start rejected by robot: {msg} (data={data})"
            if _is_session_lost(msg, body.get("code")):
                raise AllybotSessionExpired(text)
            raise ValueError(text)

    async def task_action(self, device_id: str, action_type: int) -> None:
        """POST /fleetapi/device/taskaction — pause(1) / resume(0) / stop(2) a running task."""
        await self._with_relogin(lambda: self._task_action_once(device_id, action_type))

    async def _task_action_once(self, device_id: str, action_type: int) -> None:
        await self._post(
            "/fleetapi/device/taskaction",
            headers=self._mobile_headers(),
            params={
                "openid": self.openid,
                "token": self.mobile_token,
                "id": device_id,
                "type": action_type,
            },
        )
