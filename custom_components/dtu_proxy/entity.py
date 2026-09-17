"""Shared entity helpers for DTU Proxy."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo

from . import DtuProxyConfigEntry
from .const import DOMAIN, client_identifier, meter_identifier, proxy_identifier
from .runtime import DtuProxyRuntimeData


def nested_value(data: dict[str, Any], *path: str) -> Any:
    """Read a value from nested dictionaries."""
    value: Any = data
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def proxy_client(data: dict[str, Any], gateway_id: str) -> dict[str, Any] | None:
    """Find one client in a proxy status payload."""
    clients = data.get("clients")
    if not isinstance(clients, list):
        return None
    for client in clients:
        if isinstance(client, dict) and client.get("id") == gateway_id:
            return client
    return None


def gateway_ids(data: dict[str, Any]) -> set[str]:
    """Return all non-empty gateway IDs reported by a proxy."""
    clients = data.get("clients")
    if not isinstance(clients, list):
        return set()
    return {
        client["id"]
        for client in clients
        if isinstance(client, dict) and isinstance(client.get("id"), str) and client["id"]
    }


def proxy_device_info(entry: DtuProxyConfigEntry, runtime: DtuProxyRuntimeData) -> DeviceInfo:
    """Build device information for the proxy."""
    firmware = runtime.status.data.get("firmware", {}) if runtime.status.data else {}
    if not isinstance(firmware, dict):
        firmware = {}
    return DeviceInfo(
        identifiers={(DOMAIN, proxy_identifier(entry.entry_id))},
        name="DTU Proxy",
        manufacturer="hmsta",
        model="Hoymiles DTU Proxy",
        sw_version=firmware.get("version"),
        hw_version=firmware.get("target"),
        configuration_url=runtime.api.base_url,
    )


def client_device_info(
    entry: DtuProxyConfigEntry,
    runtime: DtuProxyRuntimeData,
    gateway_id: str,
) -> DeviceInfo:
    """Build device information for one gateway client."""
    direct_clients = runtime.clients.data or {}
    data = direct_clients.get(gateway_id, {})
    firmware = data.get("firmware", {}) if isinstance(data, dict) else {}
    if not isinstance(firmware, dict):
        firmware = {}
    return DeviceInfo(
        identifiers={(DOMAIN, client_identifier(entry.entry_id, gateway_id))},
        name=gateway_id,
        manufacturer="hmsta",
        model="DTU Proxy client",
        sw_version=firmware.get("version"),
        hw_version=firmware.get("target"),
        configuration_url=(runtime.clients.client_base_url(gateway_id) or runtime.api.base_url),
        via_device=(DOMAIN, proxy_identifier(entry.entry_id)),
    )


def meter_device_info(entry: DtuProxyConfigEntry, runtime: DtuProxyRuntimeData) -> DeviceInfo:
    """Build device information for the physical meter."""
    serial_number = None
    data = runtime.meter.data or {}
    meter_data = data.get("meterData")
    if isinstance(meter_data, list) and meter_data and isinstance(meter_data[0], dict):
        candidate = meter_data[0].get("serialNumber")
        if isinstance(candidate, str) and candidate:
            serial_number = candidate
    return DeviceInfo(
        identifiers={(DOMAIN, meter_identifier(entry.entry_id))},
        name="DTU Proxy Meter",
        manufacturer="CHINT",
        model="DTSU666 energy meter",
        serial_number=serial_number,
        configuration_url=f"{runtime.api.base_url}/meter.json",
        via_device=(DOMAIN, proxy_identifier(entry.entry_id)),
    )
