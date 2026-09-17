"""Small asynchronous HTTP client for DTU Proxy firmware."""

from __future__ import annotations

from ipaddress import ip_address
from typing import Any

from aiohttp import ClientError, ClientSession, ClientTimeout

from .const import DEFAULT_PORT, REQUEST_TIMEOUT_SECONDS


class DtuProxyError(Exception):
    """Base exception for the DTU Proxy API."""


class DtuProxyConnectionError(DtuProxyError):
    """Raised when an endpoint cannot be reached."""


class DtuProxyInvalidResponse(DtuProxyError):
    """Raised when an endpoint returns an unexpected response."""


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
        self.host = normalize_host(host)
        self.port = port

    @property
    def base_url(self) -> str:
        """Return the endpoint base URL."""
        authority = _url_host(self.host)
        if self.port != DEFAULT_PORT:
            authority = f"{authority}:{self.port}"
        return f"http://{authority}"

    async def _get_json(self, path: str) -> dict[str, Any]:
        try:
            async with self._session.get(
                f"{self.base_url}{path}",
                timeout=ClientTimeout(total=REQUEST_TIMEOUT_SECONDS),
            ) as response:
                response.raise_for_status()
                payload = await response.json(content_type=None)
        except (ClientError, TimeoutError) as err:
            raise DtuProxyConnectionError(str(err)) from err
        except ValueError as err:
            raise DtuProxyInvalidResponse("Endpoint did not return valid JSON") from err

        if not isinstance(payload, dict):
            raise DtuProxyInvalidResponse("Expected a JSON object")
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
