"""Small asynchronous HTTP client for DTU Proxy firmware."""

from __future__ import annotations

import asyncio
from ipaddress import ip_address
from typing import Any

from aiohttp import ClientError, ClientSession, ClientTimeout

from .const import (
    DEFAULT_PORT,
    REQUEST_RETRY_DELAYS_SECONDS,
    REQUEST_TIMEOUT_SECONDS,
    SHARED_HOST_COOLDOWN_SECONDS,
)
from .retry_policy import async_retry_request


class DtuProxyError(Exception):
    """Base exception for the DTU Proxy API."""


class DtuProxyRetryableError(DtuProxyError):
    """Base exception for a request that may succeed when repeated."""


class DtuProxyConnectionError(DtuProxyRetryableError):
    """Raised when an endpoint cannot be reached."""


class DtuProxyInvalidResponse(DtuProxyRetryableError):
    """Raised when an endpoint returns malformed or incomplete JSON."""


class DtuProxyHttpError(DtuProxyError):
    """Raised for a non-retryable HTTP response."""


class DtuProxyCooldownError(DtuProxyConnectionError):
    """Raised when another endpoint already exhausted the shared host."""


def normalize_host(value: str) -> str:
    """Normalize and validate a host supplied through a config flow."""
    host = value.strip().rstrip(".")
    if not host or "://" in host or "/" in host or " " in host:
        raise ValueError("A host or IP address is required, without a URL path")
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    return host.lower()


def _url_host(host: str) -> str:
    """Bracket IPv6 literals for use in a URL."""
    try:
        return f"[{host}]" if ip_address(host).version == 6 else host
    except ValueError:
        return host


class DtuProxyApi:
    """Read-only client for one proxy or client web endpoint."""

    def __init__(self, session: ClientSession, host: str, port: int = DEFAULT_PORT) -> None:
        self._session = session
        self._request_lock = asyncio.Lock()
        self._cooldown_until = 0.0
        self.host = normalize_host(host)
        self.port = port

    @property
    def base_url(self) -> str:
        """Return the endpoint base URL."""
        authority = _url_host(self.host)
        if self.port != DEFAULT_PORT:
            authority = f"{authority}:{self.port}"
        return f"http://{authority}"

    async def _request_json_once(self, path: str) -> dict[str, Any]:
        """Make one HTTP request and classify failures for retry handling."""
        try:
            async with self._session.get(
                f"{self.base_url}{path}",
                timeout=ClientTimeout(total=REQUEST_TIMEOUT_SECONDS),
            ) as response:
                if response.status >= 400:
                    if response.status in (408, 429) or response.status >= 500:
                        raise DtuProxyConnectionError(f"HTTP {response.status}")
                    raise DtuProxyHttpError(f"HTTP {response.status}")
                payload = await response.json(content_type=None)
        except DtuProxyError:
            raise
        except (ClientError, TimeoutError) as err:
            raise DtuProxyConnectionError(str(err)) from err
        except ValueError as err:
            raise DtuProxyInvalidResponse("Endpoint did not return valid JSON") from err

        if not isinstance(payload, dict):
            raise DtuProxyInvalidResponse("Expected a JSON object")
        return payload

    async def _get_json(self, path: str) -> dict[str, Any]:
        # Proxy status and meter coordinators share this API instance. The lock
        # covers the complete retry batch so their requests cannot interleave.
        async with self._request_lock:
            loop = asyncio.get_running_loop()
            cooldown_remaining = self._cooldown_until - loop.time()
            if cooldown_remaining > 0:
                raise DtuProxyCooldownError(
                    f"Host retry cooldown active for {cooldown_remaining:.1f} seconds"
                )

            try:
                payload = await async_retry_request(
                    lambda: self._request_json_once(path),
                    should_retry=lambda err: isinstance(err, DtuProxyRetryableError),
                    delays=REQUEST_RETRY_DELAYS_SECONDS,
                )
            except DtuProxyConnectionError:
                self._cooldown_until = loop.time() + SHARED_HOST_COOLDOWN_SECONDS
                raise
            except DtuProxyInvalidResponse:
                raise

            self._cooldown_until = 0.0
            return payload

    async def async_status(self) -> dict[str, Any]:
        """Fetch status data."""
        return await self._get_json("/status.json")

    async def async_meter(self) -> dict[str, Any]:
        """Fetch decoded meter and raw cache data."""
        return await self._get_json("/meter.json")


def validate_proxy_status(payload: dict[str, Any]) -> None:
    """Validate that a status payload belongs to proxy firmware."""
    firmware = payload.get("firmware")
    role = firmware.get("role") if isinstance(firmware, dict) else None
    if role != "proxy" and not isinstance(payload.get("clients"), list):
        raise DtuProxyInvalidResponse("The endpoint is not a DTU Proxy")


def client_gateway_id(payload: dict[str, Any]) -> str:
    """Validate a client status payload and return its gateway ID."""
    firmware = payload.get("firmware")
    role = firmware.get("role") if isinstance(firmware, dict) else None
    gateway_id = payload.get("gateway")
    if role != "client" or not isinstance(gateway_id, str) or not gateway_id:
        raise DtuProxyInvalidResponse("The endpoint is not a DTU Proxy client")
    return gateway_id
