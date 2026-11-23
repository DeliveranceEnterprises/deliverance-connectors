# SPDX-FileCopyrightText: 2026 Deliverance Enterprises
#
# SPDX-License-Identifier: MIT

"""Async HTTP client for the Keenon Cloud API with OAuth2 token management."""

import asyncio
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
KEENON_SUCCESS_ALT = 200  # some endpoints return 200 instead of 610000
KEENON_TOKEN_EXPIRED = 610401
KEENON_RATE_LIMITED = 610609  # "Interface calls too frequent"
# Refresh the token when this many seconds remain before expiry.
TOKEN_REFRESH_MARGIN_S = 300.0
# Recreate the HTTP connection pool after this many consecutive transport errors.
TRANSPORT_ERRORS_BEFORE_RESET = 3


class KeenonAPIError(ValueError):
    """The Keenon API answered with a non-success business code."""

    def __init__(self, code, msg: str) -> None:
        super().__init__(f"Keenon API error {code}: {msg}")
        self.code = code
        self.msg = msg


class KeenonAuthError(KeenonAPIError):
    """Login failed, the token was rejected, or a login is held back by the backoff."""


class KeenonRateLimitError(KeenonAPIError):
    """Keenon asked us to slow down (610609)."""


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

    Keenon keeps a single token per app: every login invalidates the token
    that any other process using the same appKey holds. So the client only
    logs in again when the token is rejected (HTTP 401 / code 610401), and
    repeated auth failures back off exponentially (``login_backoff_min_s``
    doubling up to ``login_backoff_max_s``) instead of logging in on every
    request. Rate-limit answers (610609) delay the next requests instead of
    resetting anything, and only transport errors recreate the connection
    pool (without closing it under requests still in flight).
    """

    def __init__(
        self,
        api_domain: str,
        client_id: str,
        client_secret: str,
        verify_ssl: bool = True,
        timeout: float = 30.0,
        login_backoff_min_s: float = 60.0,
        login_backoff_max_s: float = 900.0,
        rate_limit_backoff_min_s: float = 2.0,
        rate_limit_backoff_max_s: float = 60.0,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._api_domain = api_domain.rstrip("/")
        self._verify_ssl = verify_ssl
        self._timeout = timeout
        self._access_token: str | None = None
        self._token_expires_at: float = 0.0

        # Login backoff (consecutive auth failures).
        self._login_lock = asyncio.Lock()
        self._login_backoff_min_s = login_backoff_min_s
        self._login_backoff_max_s = login_backoff_max_s
        self._auth_failures = 0
        self._last_login_attempt = 0.0  # monotonic

        # Rate-limit backoff.
        self._rate_limit_backoff_min_s = rate_limit_backoff_min_s
        self._rate_limit_backoff_max_s = rate_limit_backoff_max_s
        self._rate_limit_backoff_s = 0.0
        self._rate_limited_until = 0.0  # monotonic

        # Connection pool and the requests in flight on each pool.
        self._transport_errors = 0
        self._in_flight: dict[httpx.AsyncClient, int] = {}
        self._retired: set[httpx.AsyncClient] = set()
        self._http = self._new_http_client()

    def _new_http_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self._api_domain,
            verify=self._verify_ssl,
            timeout=self._timeout,
            limits=httpx.Limits(
                max_keepalive_connections=5,
                max_connections=10,
                keepalive_expiry=30.0,
            ),
        )

    async def close(self) -> None:
        for http in (self._http, *self._retired):
            await http.aclose()
        self._retired.clear()

    # ------------------------------------------------------------------
    # Connection pool
    # ------------------------------------------------------------------

    async def _send(self, method: str, path: str, **kwargs) -> httpx.Response:
        """Send one HTTP request, tracking it on the pool it was sent on."""
        http = self._http
        self._in_flight[http] = self._in_flight.get(http, 0) + 1
        try:
            resp = await http.request(method, path, **kwargs)
        except httpx.TransportError:
            await self._note_transport_error(http)
            raise
        finally:
            self._in_flight[http] -= 1
            if http in self._retired and self._in_flight[http] == 0:
                await self._close_retired(http)
        self._transport_errors = 0
        return resp

    async def _note_transport_error(self, http: httpx.AsyncClient) -> None:
        if http is not self._http:
            return  # the pool was already replaced
        self._transport_errors += 1
        if self._transport_errors < TRANSPORT_ERRORS_BEFORE_RESET:
            return
        logger.warning(
            "Recreating HTTP connection pool after %d consecutive transport errors",
            self._transport_errors,
        )
        self._transport_errors = 0
        self._http = self._new_http_client()
        # The old pool is closed once its last in-flight request finishes
        # (in _send); the request that failed is still counted at this point.
        self._retired.add(http)

    async def _close_retired(self, http: httpx.AsyncClient) -> None:
        self._retired.discard(http)
        self._in_flight.pop(http, None)
        await http.aclose()

    # ------------------------------------------------------------------
    # Token management
    # ------------------------------------------------------------------

    def _login_backoff_remaining(self) -> float:
        if self._auth_failures == 0:
            return 0.0
        delay = min(
            self._login_backoff_max_s,
            self._login_backoff_min_s * 2 ** (self._auth_failures - 1),
        )
        return max(0.0, self._last_login_attempt + delay - time.monotonic())

    async def _refresh_token(self, stale_token: str | None = None) -> None:
        """Log in, unless another request already did since ``stale_token`` was used."""
        async with self._login_lock:
            if self._access_token is not None and self._access_token != stale_token:
                return  # refreshed by a concurrent request while we waited
            if (remaining := self._login_backoff_remaining()) > 0:
                raise KeenonAuthError(
                    KEENON_TOKEN_EXPIRED,
                    f"login held back after {self._auth_failures} auth failures, "
                    f"next attempt in {remaining:.0f}s",
                )
            self._last_login_attempt = time.monotonic()
            try:
                resp = await self._send(
                    "POST",
                    "/api/open/oauth/token",
                    data={
                        "client_id": self._client_id,
                        "client_secret": self._client_secret,
                        "grant_type": "client_credentials",
                    },
                )
                resp.raise_for_status()
                body = resp.json()
                token = body["access_token"]
                expires_in = float(body["expires_in"])
            except httpx.TransportError:
                raise  # network trouble, not an auth failure: no login backoff
            except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
                self._auth_failures += 1
                logger.warning(
                    "Keenon login failed (%d consecutive auth failures): %s",
                    self._auth_failures, exc,
                )
                raise KeenonAuthError(KEENON_TOKEN_EXPIRED, f"login failed: {exc}") from exc
            self._access_token = token
            self._token_expires_at = time.time() + expires_in
            logger.debug("Token refreshed, expires in %ss", expires_in)

    async def _ensure_token(self) -> None:
        if (
            self._access_token is None
            or time.time() >= self._token_expires_at - TOKEN_REFRESH_MARGIN_S
        ):
            await self._refresh_token(stale_token=self._access_token)

    def _drop_token(self, token: str | None) -> None:
        """Forget a rejected token, unless a concurrent request already replaced it."""
        if self._access_token == token:
            self._access_token = None

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"bearer {self._access_token}"}

    # ------------------------------------------------------------------
    # Internal request helpers
    # ------------------------------------------------------------------

    async def _wait_rate_limit(self) -> None:
        remaining = self._rate_limited_until - time.monotonic()
        if remaining > 0:
            await asyncio.sleep(remaining)

    def _note_rate_limited(self) -> None:
        self._rate_limit_backoff_s = min(
            self._rate_limit_backoff_max_s,
            max(self._rate_limit_backoff_min_s, self._rate_limit_backoff_s * 2),
        )
        self._rate_limited_until = time.monotonic() + self._rate_limit_backoff_s
        logger.warning(
            "Keenon rate limit hit, delaying requests for %.0fs", self._rate_limit_backoff_s
        )

    @staticmethod
    def _is_auth_rejection(resp: httpx.Response, payload: dict | None) -> bool:
        if resp.status_code == 401:
            return True
        return isinstance(payload, dict) and payload.get("code") == KEENON_TOKEN_EXPIRED

    async def _request(
        self,
        method: str,
        path: str,
        *,
        _retry_on_expired: bool = True,
        **kwargs,
    ) -> dict | list | None:
        await self._wait_rate_limit()
        await self._ensure_token()
        token_used = self._access_token
        resp = await self._send(method, path, headers=self._auth_headers(), **kwargs)
        payload = None
        if resp.status_code != 401:
            resp.raise_for_status()
            payload = resp.json()

        if self._is_auth_rejection(resp, payload):
            if _retry_on_expired:
                # Keenon keeps one token per app: our token was invalidated
                # (expired, or the same app logged in elsewhere). Log in once.
                logger.warning("Keenon rejected the token, logging in again")
                self._drop_token(token_used)
                await self._refresh_token(stale_token=token_used)
                return await self._request(method, path, _retry_on_expired=False, **kwargs)
            # Rejected again right after a fresh login: back off further logins.
            self._drop_token(token_used)
            self._auth_failures += 1
            msg = payload.get("msg") if isinstance(payload, dict) else f"HTTP {resp.status_code}"
            raise KeenonAuthError(KEENON_TOKEN_EXPIRED, f"token rejected: {msg}")

        code = payload.get("code")
        msg = payload.get("msg") or payload.get("message", "")
        if code == KEENON_RATE_LIMITED:
            self._note_rate_limited()
            raise KeenonRateLimitError(code, msg)
        if code not in (KEENON_SUCCESS, KEENON_SUCCESS_ALT) and str(msg).lower() != "success":
            raise KeenonAPIError(code, msg)
        # The token works and Keenon is not throttling us.
        self._auth_failures = 0
        self._rate_limit_backoff_s = 0.0
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
        """Return robot status list from the scene API.

        The endpoint returns either a single robot object directly in ``data``
        (observed in production) or a dict with a ``list`` key (as per the
        API spec).  Both formats are normalised to a list.
        """
        data = await self._get(
            "/api/open/scene/v1/robot/status", params={"robotId": robot_id}
        )
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            if "list" in data:
                return data["list"]
            # Single robot object returned directly — wrap in a list.
            return [data] if data else []
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

    async def get_task_info(self, task_no: str) -> dict | None:
        """Return remote/local meal-delivery task detail by taskNo.

        GET /api/open/scene/v1/robot/task/info - returns taskType, taskState
        and subTaskInfoList[] with per-point taskDistance (metres).  Keyed by
        taskNo, so no time-window search is needed.  (The API doc lists this as
        POST but the server only accepts GET.)

        This is the source of the per-task report (mileage/mode/destination).
        The data-statistics endpoint /store/task/food/list was evaluated first
        but only logs robot-initiated food-delivery rounds, not the remote
        "call to point" tasks we dispatch - so it returns no records for them.
        """
        return await self._get(
            "/api/open/scene/v1/robot/task/info", params={"taskNo": task_no}
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
