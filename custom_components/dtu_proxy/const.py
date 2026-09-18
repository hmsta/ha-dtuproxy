"""Constants for the DTU Proxy integration."""

from datetime import timedelta

from homeassistant.const import Platform

DOMAIN = "dtu_proxy"

CONF_METER_INTERVAL = "meter_interval"
CONF_PORT = "port"

DEFAULT_PORT = 80
DEFAULT_NAME = "DTU Proxy"
DEFAULT_METER_INTERVAL = 30
METER_INTERVALS = (5, 10, 15, 30, 60)

PLATFORMS = (Platform.BINARY_SENSOR, Platform.SENSOR)

PROXY_STATUS_INTERVAL = timedelta(seconds=30)
CLIENT_STATUS_INTERVAL = timedelta(seconds=60)

REQUEST_TIMEOUT_SECONDS = 5
REQUEST_RETRY_DELAYS_SECONDS = (1.0, 2.0)
SHARED_HOST_COOLDOWN_SECONDS = 30
RETRY_BACKOFF_INITIAL_SECONDS = 30
RETRY_BACKOFF_MAX_SECONDS = 60


def proxy_identifier(entry_id: str) -> str:
    """Return the integration-owned proxy identifier."""
    return f"{entry_id}:proxy"


def meter_identifier(entry_id: str) -> str:
    """Return the integration-owned meter identifier."""
    return f"{entry_id}:meter"


def client_identifier(entry_id: str, gateway_id: str) -> str:
    """Return the integration-owned client identifier."""
    return f"{entry_id}:client:{gateway_id}"
