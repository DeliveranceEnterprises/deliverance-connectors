# SPDX-FileCopyrightText: 2026 Deliverance Enterprises
#
# SPDX-License-Identifier: MIT

"""Async HTTP client for the Keenon Cloud API with OAuth2 token management."""

import base64
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

KEENON_SUCCESS = 610000
KEENON_TOKEN_EXPIRED = 610401
# Refresh the token when this many seconds remain before expiry.
TOKEN_REFRESH_MARGIN_S = 300.0


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


class KeenonAPIClient:
    """Async REST client for the Keenon Cloud API.

    Handles OAuth2 client-credentials token acquisition and proactive
    refresh, plus automatic retry on transient network errors.
    """

    def __init__(
        self,
        api_domain: str,
        client_id: str,
        client_secret: str,
        verify_ssl: bool = True,
        timeout: float = 30.0,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._access_token: str | None = None
        self._token_expires_at: float = 0.0
        self._http = httpx.AsyncClient(
            base_url=api_domain.rstrip("/"),
            verify=verify_ssl,
            timeout=timeout,
        )

    async def close(self) -> None:
        await self._http.aclose()

    # ------------------------------------------------------------------
    # Token management
    # ------------------------------------------------------------------

    async def _refresh_token(self) -> None:
        resp = await self._http.post(
            "/api/open/oauth/token",
            data={
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "grant_type": "client_credentials",
            },
        )
        resp.raise_for_status()
        body = resp.json()
        self._access_token = body["access_token"]
        self._token_expires_at = time.time() + body["expires_in"]
        logger.debug("Token refreshed, expires in %ss", body["expires_in"])

    async def _ensure_token(self) -> None:
        if (
            self._access_token is None
            or time.time() >= self._token_expires_at - TOKEN_REFRESH_MARGIN_S
        ):
            await self._refresh_token()

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"bearer {self._access_token}"}

    # ------------------------------------------------------------------
    # Internal request helpers
    # ------------------------------------------------------------------

    async def _request(
        self,
        method: str,
        path: str,
        *,
        _retry_on_expired: bool = True,
        **kwargs,
    ) -> dict | list | None:
        await self._ensure_token()
        resp = await self._http.request(
            method, path, headers=self._auth_headers(), **kwargs
        )
        resp.raise_for_status()
        payload = resp.json()

        if payload.get("code") == KEENON_TOKEN_EXPIRED:
            if _retry_on_expired:
                logger.warning("Token expired mid-request, refreshing and retrying")
                await self._refresh_token()
                return await self._request(
                    method, path, _retry_on_expired=False, **kwargs
                )
            raise ValueError(f"Keenon token error: {payload.get('msg')}")

        if payload.get("code") != KEENON_SUCCESS:
            raise ValueError(
                f"Keenon API error {payload.get('code')}: {payload.get('msg')}"
            )
        return payload.get("data")

    @_retry()
    async def _get(self, path: str, **kwargs) -> dict | list | None:
        return await self._request("GET", path, **kwargs)

    @_retry()
    async def _post(self, path: str, **kwargs) -> dict | list | None:
        return await self._request("POST", path, **kwargs)

    @_retry()
    async def _delete(self, path: str, **kwargs) -> dict | list | None:
        return await self._request("DELETE", path, **kwargs)

    # ------------------------------------------------------------------
    # Data endpoints
    # ------------------------------------------------------------------

    async def get_robot_list(self, store_id: str) -> list[dict]:
        """Return all robots in the given store."""
        data = await self._get(
            "/api/open/data/v1/store/robot/list", params={"storeId": store_id}
        )
        return data if isinstance(data, list) else []

    async def get_robot_status(self, robot_id: str) -> list[dict]:
        """Return robot status list from the scene API."""
        data = await self._get(
            "/api/open/scene/v1/robot/status", params={"robotId": robot_id}
        )
        if isinstance(data, dict):
            return data.get("list", [])
        return []

    async def get_robot_location(self, robot_sn: str) -> dict | None:
        """Return real-time location (x, y, angle) for the robot."""
        return await self._get(
            "/api/open/custom/robot/location", params={"robotSn": robot_sn}
        )

    async def get_clean_robot_status(self, robot_sn: str) -> dict | None:
        """Return detailed status for a cleaning robot."""
        return await self._get(
            "/api/open/custom/clean/robot/status", params={"robotSn": robot_sn}
        )

    async def get_task_status(self, task_no: str) -> dict | None:
        """Return current status for an active call task."""
        return await self._get(
            "/api/open/scene/v1/robot/call/task", params={"taskNo": task_no}
        )

    async def get_map(
        self,
        scene_code: str,
        floor_info: str,
        building_info: str = "",
    ) -> bytes | None:
        """Fetch map image for a scene/floor (base64-encoded PNG)."""
        params: dict[str, str] = {
            "sceneCode": scene_code,
            "floorInfo": floor_info,
        }
        if building_info:
            params["buildingInfo"] = building_info
        data = await self._get("/api/open/custom/robot/map", params=params)
        if isinstance(data, dict):
            content = data.get("content")
            if content:
                try:
                    return base64.b64decode(content)
                except Exception:
                    logger.warning("Could not base64-decode map content")
        return None

    # ------------------------------------------------------------------
    # Command endpoints
    # ------------------------------------------------------------------

    async def call_to_point(
        self,
        uuid: str,
        point_id: str,
        store_id: str,
        robot_id: str,
        scene_code: str | None = None,
        robot_type: str | None = None,
    ) -> str:
        """Send a robot to a single delivery point. Returns the taskNo."""
        body: dict = {
            "uuid": uuid,
            "pointId": point_id,
            "storeId": store_id,
            "robotId": robot_id,
        }
        if scene_code:
            body["sceneCode"] = scene_code
        if robot_type:
            body["robotType"] = robot_type
        data = await self._post("/api/open/scene/v3/robot/call/task", json=body)
        return data.get("taskNo", "") if isinstance(data, dict) else ""

    async def return_to_origin(self, store_id: str, robot_id: str) -> str:
        """Send a food-delivery robot back to its origin. Returns the taskNo."""
        data = await self._post(
            "/api/open/scene/v2/robot/call/back/task",
            params={"storeId": store_id, "robotId": robot_id},
        )
        return data.get("taskNo", "") if isinstance(data, dict) else ""

    async def cancel_task(self, task_no: str) -> None:
        """Cancel an active call task."""
        await self._delete(
            "/api/open/scene/v1/robot/call/task", params={"taskNo": task_no}
        )

    async def clean_recharge(self, robot_sn: str) -> None:
        """Send a cleaning robot to its charging station."""
        await self._post(
            "/api/open/custom/clean/robot/recharge/task",
            json={"robotSn": robot_sn},
        )

    async def clean_finish(self, robot_sn: str) -> None:
        """End the current cleaning task."""
        await self._post(
            "/api/open/custom/clean/robot/finish/task",
            json={"robotSn": robot_sn},
        )

    async def clean_pause(self, robot_sn: str) -> None:
        """Pause the current cleaning task."""
        await self._post(
            "/api/open/custom/clean/robot/pause/task",
            json={"robotSn": robot_sn},
        )

    async def clean_temporary_task(
        self,
        robot_sn: str,
        area_id_list: list[str],
        clean_model_id: str,
        clean_times: int,
        back_point_id: int,
    ) -> None:
        """Start an immediate (temporary) cleaning task."""
        await self._post(
            "/api/open/custom/clean/robot/strategy/temporary/task",
            json={
                "robotSn": robot_sn,
                "areaIdList": area_id_list,
                "cleanModelId": clean_model_id,
                "cleanTimes": clean_times,
                "backPointId": back_point_id,
            },
        )

    async def control_cabin(
        self,
        store_id: str,
        robot_sn: str,
        cabin: str,
        ctrl_type: str,
    ) -> None:
        """Open (ctrl_type='1') or close (ctrl_type='0') a hotel robot cabin."""
        await self._post(
            "/api/open/custom/robot/cabin/door",
            json={
                "storeId": store_id,
                "robotSn": robot_sn,
                "cabin": cabin,
                "ctrlType": ctrl_type,
            },
        )
