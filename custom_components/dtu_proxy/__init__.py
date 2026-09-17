"""Home Assistant integration for DTU Proxy firmware."""

from __future__ import annotations

import asyncio

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
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
    proxy_identifier,
)
from .coordinator import ClientFleetCoordinator, MeterCoordinator, ProxyStatusCoordinator
from .runtime import DtuProxyRuntimeData

type DtuProxyConfigEntry = ConfigEntry[DtuProxyRuntimeData]


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
    proxy_device = registry.async_get_or_create(
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
        proxy_device_id=proxy_device.id,
    )
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: DtuProxyConfigEntry) -> bool:
    """Unload a DTU Proxy config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload after integration options change."""
    await hass.config_entries.async_reload(entry.entry_id)
