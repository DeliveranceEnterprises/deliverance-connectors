# SPDX-FileCopyrightText: 2026 Deliverance Enterprises
#
# SPDX-License-Identifier: MIT

"""REST client for the Ally Fleet Robot API with dual-auth support."""

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

    @_retry()
    async def _get(self, path: str, headers: dict, **kwargs) -> dict | list | None:
        resp = await self._http.get(path, headers=headers, **kwargs)
        if resp.status_code in (401, 403):
            logger.warning("Auth error on %s — session may have expired", path)
        resp.raise_for_status()
        body = resp.json()
        if not self._is_success(body):
            raise ValueError(f"Allybot API error on {path}: {body.get('message')} ({body.get('code')})")
        return body.get("data")

    @_retry()
    async def _post(self, path: str, headers: dict, **kwargs) -> dict | list | None:
        resp = await self._http.post(path, headers=headers, **kwargs)
        resp.raise_for_status()
        body = resp.json()
        if not self._is_success(body):
            raise ValueError(f"Allybot API error on {path}: {body.get('message')} ({body.get('code')})")
        return body.get("data")

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
