"""Data coordinators for DTU Proxy."""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from ipaddress import ip_address
from typing import Any

from aiohttp import ClientSession
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import DtuProxyApi, DtuProxyError, client_gateway_id, normalize_host
from .const import (
    CLIENT_STATUS_INTERVAL,
    PROXY_STATUS_INTERVAL,
    RETRY_BACKOFF_INITIAL_SECONDS,
    RETRY_BACKOFF_MAX_SECONDS,
)
from .retry_policy import FailedRunBackoff

_LOGGER = logging.getLogger(__name__)


class _DtuCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Base coordinator that translates API errors for Home Assistant."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        api: DtuProxyApi,
        *,
        name: str,
        update_interval: timedelta,
    ) -> None:
        super().__init__(
            hass,
            logger=_LOGGER,
            config_entry=entry,
            name=name,
            update_interval=update_interval,
        )
        self.api = api
        interval_seconds = (
            update_interval.total_seconds()
            if update_interval is not None
            else RETRY_BACKOFF_INITIAL_SECONDS
        )
        self._failed_run_backoff = FailedRunBackoff(
            initial_delay=min(
                max(interval_seconds, RETRY_BACKOFF_INITIAL_SECONDS),
                RETRY_BACKOFF_MAX_SECONDS,
            ),
            maximum_delay=RETRY_BACKOFF_MAX_SECONDS,
        )

    def _next_retry_delay(self) -> float:
        """Return the bounded delay after an exhausted polling run."""
        return self._failed_run_backoff.record_failure()

    def _request_failed(self, err: DtuProxyError) -> dict[str, Any]:
        """Expose an exhausted retry batch and schedule a bounded retry."""
        raise UpdateFailed(str(err), retry_after=self._next_retry_delay()) from err

    def _request_succeeded(self) -> None:
        """Reset failed-run backoff after communication recovers."""
        self._failed_run_backoff.record_success()


class ProxyStatusCoordinator(_DtuCoordinator):
    """Fetch proxy and proxy-observed client status."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, api: DtuProxyApi) -> None:
        super().__init__(
            hass,
            entry,
            api,
            name="DTU Proxy status",
            update_interval=PROXY_STATUS_INTERVAL,
        )

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            data = await self.api.async_status()
        except DtuProxyError as err:
            return self._request_failed(err)
        self._request_succeeded()
        return data


class MeterCoordinator(_DtuCoordinator):
    """Fetch decoded meter measurements."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        api: DtuProxyApi,
        update_interval_seconds: int,
    ) -> None:
        super().__init__(
            hass,
            entry,
            api,
            name="DTU Proxy meter",
            update_interval=timedelta(seconds=update_interval_seconds),
        )

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            data = await self.api.async_meter()
        except DtuProxyError as err:
            return self._request_failed(err)
        self._request_succeeded()
        return data


class ClientFleetCoordinator(DataUpdateCoordinator[dict[str, dict[str, Any]]]):
    """Fetch direct diagnostics from clients discovered through the proxy."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        session: ClientSession,
        proxy_status: ProxyStatusCoordinator,
    ) -> None:
        super().__init__(
            hass,
            logger=_LOGGER,
            config_entry=entry,
            name="DTU Proxy direct client status",
            update_interval=CLIENT_STATUS_INTERVAL,
        )
        self._session = session
        self._proxy_status = proxy_status
        self._hosts: dict[str, str] = {}

    def client_base_url(self, gateway_id: str) -> str | None:
        """Return the current direct URL for a discovered client."""
        host = self._hosts.get(gateway_id)
        return DtuProxyApi(self._session, host).base_url if host else None

    def _discovered_hosts(self) -> dict[str, str]:
        clients = (self._proxy_status.data or {}).get("clients")
        if not isinstance(clients, list):
            return {}

        discovered: dict[str, str] = {}
        for client in clients:
            if not isinstance(client, dict):
                continue
            gateway_id = client.get("id")
            remote_ip = client.get("remote_ip")
            if not isinstance(gateway_id, str) or not gateway_id:
                continue
            if not isinstance(remote_ip, str) or not remote_ip:
                continue
            try:
                host = normalize_host(remote_ip)
                address = ip_address(host)
            except ValueError:
                _LOGGER.debug("Ignoring invalid remote_ip reported for gateway %s", gateway_id)
                continue
            if address.is_unspecified or address.is_multicast:
                _LOGGER.debug("Ignoring unusable remote_ip reported for gateway %s", gateway_id)
                continue
            discovered[gateway_id] = host
        return discovered

    async def _async_fetch_client(
        self, gateway_id: str, host: str
    ) -> tuple[str, dict[str, Any] | None]:
        try:
            payload = await DtuProxyApi(self._session, host).async_status()
            reported_gateway_id = client_gateway_id(payload)
        except (DtuProxyError, ValueError) as err:
            _LOGGER.debug(
                "Unable to update client %s at its discovered address: %s", gateway_id, err
            )
            return gateway_id, None

        if reported_gateway_id != gateway_id:
            _LOGGER.debug(
                "Client address discovered for %s returned gateway ID %s",
                gateway_id,
                reported_gateway_id,
            )
            return gateway_id, None
        return gateway_id, payload

    async def _async_update_data(self) -> dict[str, dict[str, Any]]:
        self._hosts = self._discovered_hosts()
        results = await asyncio.gather(
            *(
                self._async_fetch_client(gateway_id, host)
                for gateway_id, host in self._hosts.items()
            )
        )
        return {gateway_id: payload for gateway_id, payload in results if payload is not None}
