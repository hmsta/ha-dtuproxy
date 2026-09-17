"""Home Assistant integration for DTU Proxy firmware."""

from __future__ import annotations

import asyncio
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import DtuProxyApi
from .const import (
    CONF_METER_INTERVAL,
    CONF_PORT,
    DEFAULT_METER_INTERVAL,
    DEFAULT_NAME,
    DEFAULT_PORT,
    DOMAIN,
    PLATFORMS,
    client_identifier,
    proxy_identifier,
)
from .coordinator import ClientFleetCoordinator, MeterCoordinator, ProxyStatusCoordinator
from .runtime import DtuProxyRuntimeData

type DtuProxyConfigEntry = ConfigEntry[DtuProxyRuntimeData]


def _update_device_firmware(
    registry: dr.DeviceRegistry,
    identifier: tuple[str, str],
    payload: dict[str, Any],
) -> None:
    """Update registry firmware metadata only when reported values change."""
    device = registry.async_get_device(identifiers={identifier})
    if device is None:
        return

    firmware = payload.get("firmware")
    if not isinstance(firmware, dict):
        return

    reported_sw = firmware.get("version")
    reported_hw = firmware.get("target")
    sw_version = reported_sw if isinstance(reported_sw, str) and reported_sw else device.sw_version
    hw_version = reported_hw if isinstance(reported_hw, str) and reported_hw else device.hw_version
    if sw_version == device.sw_version and hw_version == device.hw_version:
        return

    registry.async_update_device(
        device.id,
        sw_version=sw_version,
        hw_version=hw_version,
    )


async def async_setup_entry(hass: HomeAssistant, entry: DtuProxyConfigEntry) -> bool:
    """Set up DTU Proxy from a config entry."""
    session = async_get_clientsession(hass)
    api = DtuProxyApi(
        session,
        entry.data[CONF_HOST],
        entry.data.get(CONF_PORT, DEFAULT_PORT),
    )
    status = ProxyStatusCoordinator(hass, entry, api)
    meter_interval = int(entry.options.get(CONF_METER_INTERVAL, DEFAULT_METER_INTERVAL))
    meter = MeterCoordinator(hass, entry, api, meter_interval)

    await status.async_config_entry_first_refresh()
    clients = ClientFleetCoordinator(hass, entry, session, status)
    await asyncio.gather(meter.async_refresh(), clients.async_refresh())

    firmware = status.data.get("firmware", {})
    if not isinstance(firmware, dict):
        firmware = {}
    registry = dr.async_get(hass)
    registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, proxy_identifier(entry.entry_id))},
        name=DEFAULT_NAME,
        manufacturer="hmsta",
        model="Hoymiles DTU Proxy",
        sw_version=firmware.get("version"),
        hw_version=firmware.get("target"),
        configuration_url=api.base_url,
    )

    entry.runtime_data = DtuProxyRuntimeData(
        api=api,
        status=status,
        meter=meter,
        clients=clients,
    )
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    @callback
    def sync_proxy_firmware() -> None:
        _update_device_firmware(
            registry,
            (DOMAIN, proxy_identifier(entry.entry_id)),
            status.data or {},
        )

    @callback
    def sync_client_firmware() -> None:
        for gateway_id, payload in (clients.data or {}).items():
            _update_device_firmware(
                registry,
                (DOMAIN, client_identifier(entry.entry_id, gateway_id)),
                payload,
            )

    entry.async_on_unload(status.async_add_listener(sync_proxy_firmware))
    entry.async_on_unload(clients.async_add_listener(sync_client_firmware))
    sync_proxy_firmware()
    sync_client_firmware()
    return True


async def async_unload_entry(hass: HomeAssistant, entry: DtuProxyConfigEntry) -> bool:
    """Unload a DTU Proxy config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload after integration options change."""
    await hass.config_entries.async_reload(entry.entry_id)
