"""Async wrapper around the synchronous pyezvizapi client."""

import asyncio
import logging
from typing import Any

from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

try:
    from pyezvizapi import EzvizClient  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover
    from pyezvizapi.client import EzvizClient  # type: ignore[import-not-found]

logger = logging.getLogger(__name__)


class EzvizAPIError(Exception):
    """Raised when an Ezviz cloud call cannot be completed."""


class EzvizAPIClient:
    """Async-friendly facade over pyezvizapi.EzvizClient.

    pyezvizapi is synchronous and uses requests; every call is dispatched to
    a worker thread via asyncio.to_thread() so the connector's event loop
    stays responsive. Retries are applied at this layer with tenacity.
    """

    def __init__(
        self,
        account: str,
        password: str,
        region_url: str,
        timeout: float = 30.0,
        sms_code: int | None = None,
    ) -> None:
        self._account = account
        self._password = password
        self._region_url = region_url
        self._timeout = int(timeout)
        self._sms_code = sms_code
        self._client: EzvizClient | None = None
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    async def login(self) -> None:
        """Authenticate and cache the session.

        Idempotent — repeat calls re-use the existing client.
        """
        async with self._lock:
            if self._client is not None:
                return
            self._client = await asyncio.to_thread(
                EzvizClient,
                self._account,
                self._password,
                self._region_url,
                self._timeout,
            )
            await asyncio.to_thread(self._do_login)
            logger.info("Logged in to Ezviz cloud at %s", self._region_url)

    def _do_login(self) -> Any:
        assert self._client is not None
        if hasattr(self._client, "login"):
            return (
                self._client.login(sms_code=self._sms_code)
                if self._sms_code is not None
                else self._client.login()
            )
        return (
            self._client._login(smscode=self._sms_code)
            if self._sms_code is not None
            else self._client._login()
        )

    async def close(self) -> None:
        """Best-effort session teardown."""
        async with self._lock:
            if self._client is None:
                return
            try:
                close_fn = getattr(self._client, "close_session", None)
                if callable(close_fn):
                    await asyncio.to_thread(close_fn)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Error closing Ezviz session: %s", exc)
            self._client = None

    async def _ensure(self) -> EzvizClient:
        if self._client is None:
            await self.login()
        assert self._client is not None
        return self._client

    # ------------------------------------------------------------------
    # Cloud calls — each retries with backoff on transient errors.
    # ------------------------------------------------------------------

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception_type(Exception),
        reraise=True,
    )
    async def load_devices(self) -> dict:
        client = await self._ensure()
        return await asyncio.to_thread(client.load_devices, True)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception_type(Exception),
        reraise=True,
    )
    async def get_device_infos(self, serial: str) -> dict:
        client = await self._ensure()
        return await asyncio.to_thread(client.get_device_infos, serial)

    async def get_alarminfo(self, serial: str, limit: int = 1) -> dict:
        client = await self._ensure()
        return await asyncio.to_thread(client.get_alarminfo, serial, limit)
