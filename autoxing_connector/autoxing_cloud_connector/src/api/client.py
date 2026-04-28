# SPDX-FileCopyrightText: 2026 Deliverance Enterprises
#
# SPDX-License-Identifier: MIT

"""REST client for the AutoXing Cloud Platform API."""

import logging
import time

import httpx
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

logger = logging.getLogger(__name__)


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


class AutoxingAPIClient:
    """Async REST client for the AutoXing Cloud Platform.

    Handles two-step web login authentication and proactive token refresh.
    All data endpoints use the API APPCODE and the 7-day JWT from login.
    """

    def __init__(
        self,
        base_url: str,
        login_name: str,
        password: str,
        business_id: str,
        login_appcode: str,
        api_appcode: str,
        verify_ssl: bool = True,
        timeout: float = 30.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._login_name = login_name
        self._password = password
        self._business_id = business_id
        self._login_appcode = login_appcode
        self._api_appcode = api_appcode

        self._http = httpx.AsyncClient(
            base_url=self._base_url,
            verify=verify_ssl,
            timeout=timeout,
        )
        self._token: str | None = None
        self._token_expires_at: float = 0.0

    async def close(self) -> None:
        await self._http.aclose()

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    async def login(self) -> None:
        """Perform two-step web login and store the 7-day JWT.

        The password field must be the AES-encrypted value as produced by the
        AutoXing web app (captured from browser traffic or Postman collection).
        It is sent as-is — no additional encryption is performed here.
        """
        # Step 1 — Login
        resp = await self._http.post(
            "/user/v1.1/login",
            headers={
                "Authorization": f"APPCODE {self._login_appcode}",
                "Origin": "https://serviceglobal.autoxing.com",
                "Referer": "https://serviceglobal.autoxing.com/",
            },
            json={"loginName": self._login_name, "password": self._password},
        )
        resp.raise_for_status()
        body = resp.json()
        if body.get("status") != 200:
            raise RuntimeError(f"AutoXing login failed: {body.get('message')} ({body.get('status')})")
        step1_data = body.get("data") or {}
        step1_token = step1_data.get("token")
        # Step 2 URL uses the `ticket` field from step 1 (not openId/userId)
        ticket = step1_data.get("ticket")
        if not ticket:
            raise RuntimeError("AutoXing login did not return a ticket — cannot complete auth")

        # Step 2 — Ticket exchange for fresh 7-day JWT
        resp2 = await self._http.get(
            f"/user/v1.0/ticket/{ticket}",
            headers={
                "Authorization": f"APPCODE {self._api_appcode}",
                "X-Token": step1_token,
                "Origin": "https://serviceglobal.autoxing.com",
                "Referer": "https://serviceglobal.autoxing.com/",
                # No Content-Type on GET requests
            },
        )
        resp2.raise_for_status()
        body2 = resp2.json()
        if body2.get("status") != 200:
            raise RuntimeError(f"AutoXing ticket exchange failed: {body2.get('message')}")
        data2 = body2.get("data") or {}
        self._token = data2.get("token")
        expire_s = data2.get("expireTime", 604800)
        # Refresh proactively at 90% of expiry
        self._token_expires_at = time.time() + expire_s * 0.9
        # Update openId/businessId if returned
        if data2.get("openid"):
            self._open_id = data2["openid"]
        if data2.get("businessId"):
            self._business_id = data2["businessId"]
        logger.info("AutoXing login OK (token valid for ~%.0f days)", expire_s / 86400)

    async def _ensure_token(self) -> None:
        if not self._token or time.time() >= self._token_expires_at:
            logger.info("AutoXing token expired or missing — refreshing")
            await self.login()

    def _api_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"APPCODE {self._api_appcode}",
            "X-Token": self._token or "",
            "Content-Type": "application/json",
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _check(self, body: dict, path: str) -> None:
        if body.get("status") != 200:
            raise ValueError(
                f"AutoXing API error on {path}: {body.get('message')} (status={body.get('status')})"
            )

    @_retry()
    async def _get(self, path: str, **kwargs) -> dict | list | None:
        await self._ensure_token()
        resp = await self._http.get(path, headers=self._api_headers(), **kwargs)
        resp.raise_for_status()
        body = resp.json()
        self._check(body, path)
        return body.get("data")

    @_retry()
    async def _post(self, path: str, **kwargs) -> dict | list | None:
        await self._ensure_token()
        resp = await self._http.post(path, headers=self._api_headers(), **kwargs)
        resp.raise_for_status()
        body = resp.json()
        self._check(body, path)
        return body.get("data")

    @_retry()
    async def _post_raw(self, path: str, **kwargs) -> httpx.Response:
        """POST that returns the raw response (for endpoints with non-standard bodies)."""
        await self._ensure_token()
        resp = await self._http.post(path, headers=self._api_headers(), **kwargs)
        resp.raise_for_status()
        return resp

    # ------------------------------------------------------------------
    # Robot endpoints
    # ------------------------------------------------------------------

    async def get_robot_list(self, page_size: int = 100) -> list[dict]:
        data = await self._post(
            "/robot/v1.1/list", json={"pageSize": page_size, "pageNum": 1}
        )
        if isinstance(data, dict):
            return data.get("list") or []
        return []

    async def get_robot_state(self, robot_id: str) -> dict | None:
        try:
            return await self._get(f"/robot/v1.1/{robot_id}/state")
        except Exception as exc:
            logger.warning("get_robot_state(%s) failed: %s", robot_id, exc)
            return None

    # ------------------------------------------------------------------
    # Map / area endpoints
    # ------------------------------------------------------------------

    async def get_area_list(self, robot_id: str | None = None) -> list[dict]:
        body: dict = {}
        if robot_id:
            body["robotId"] = robot_id
        else:
            body["businessId"] = self._business_id
        try:
            data = await self._post("/map/v1.1/area/list", json=body)
            if isinstance(data, dict):
                return data.get("list") or []
        except Exception as exc:
            logger.warning("get_area_list failed: %s", exc)
        return []

    async def get_map_image(self, area_id: str) -> bytes | None:
        try:
            await self._ensure_token()
            resp = await self._http.get(
                f"/map/v1.1/area/{area_id}/base-map",
                headers=self._api_headers(),
            )
            resp.raise_for_status()
            return resp.content
        except Exception as exc:
            logger.warning("get_map_image(%s) failed: %s", area_id, exc)
            return None

    async def get_poi_list(self, area_id: str) -> list[dict]:
        try:
            data = await self._post("/map/v1.1/poi/list", json={"areaId": area_id})
            if isinstance(data, dict):
                return data.get("list") or []
        except Exception as exc:
            logger.warning("get_poi_list(%s) failed: %s", area_id, exc)
        return []

    # ------------------------------------------------------------------
    # Task endpoints
    # ------------------------------------------------------------------

    async def create_task(self, payload: dict) -> str | None:
        """POST /task/v1.1 — create a task, return its taskId."""
        try:
            data = await self._post("/task/v1.1", json=payload)
            if isinstance(data, dict):
                return data.get("taskId")
            return str(data) if data else None
        except Exception as exc:
            raise ValueError(f"Task creation failed: {exc}") from exc

    async def execute_task(self, task_id: str) -> None:
        """POST /task/v1.1/{taskId}/execute"""
        await self._post(f"/task/v1.1/{task_id}/execute")

    async def cancel_task(self, task_id: str) -> None:
        """POST /task/v1.1/{taskId}/cancel"""
        try:
            await self._post(f"/task/v1.1/{task_id}/cancel")
        except Exception as exc:
            logger.warning("cancel_task(%s) failed: %s", task_id, exc)

    async def get_task(self, task_id: str) -> dict | None:
        try:
            return await self._get(f"/task/v1.1/{task_id}")
        except Exception as exc:
            logger.warning("get_task(%s) failed: %s", task_id, exc)
            return None
