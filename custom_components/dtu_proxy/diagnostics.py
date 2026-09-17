"""Privacy-conscious diagnostics for DTU Proxy."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import REDACTED
from homeassistant.core import HomeAssistant

from . import DtuProxyConfigEntry
from .entity import gateway_ids

_SENSITIVE_KEYS = {
    "ap_ip",
    "ethernet_ip",
    "host",
    "ip",
    "password",
    "proxy_host",
    "remote_ip",
    "sta_ip",
    "wifi_ssid",
    "wifi_sta_ip",
}


def _redact(value: Any, key: str = "") -> Any:
    """Recursively redact network addresses and credentials."""
    lowered = key.lower()
    if (
        lowered in _SENSITIVE_KEYS
        or lowered.endswith("_password")
        or lowered.endswith("_ssid")
        or lowered.endswith("_ip")
        or lowered.endswith("_host")
    ):
        return REDACTED
    if isinstance(value, dict):
        return {str(item_key): _redact(item, str(item_key)) for item_key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: DtuProxyConfigEntry
) -> dict[str, Any]:
    """Return diagnostics without local addresses, SSIDs, or raw Modbus frames."""
    runtime = entry.runtime_data
    proxy_status = runtime.status.data or {}
    client_ids = gateway_ids(proxy_status)
    direct_clients = runtime.clients.data or {}
    meter = dict(runtime.meter.data or {})
    meter.pop("entries", None)
    return {
        "config": {
            "proxy": REDACTED,
            "client_count": len(client_ids),
        },
        "proxy_status": _redact(proxy_status),
        "meter": _redact(meter),
        "direct_clients": {
            gateway_id: {
                "available": gateway_id in direct_clients,
                "status": _redact(direct_clients.get(gateway_id, {})),
            }
            for gateway_id in sorted(client_ids)
        },
    }
