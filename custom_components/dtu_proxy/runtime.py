"""Runtime data model for DTU Proxy."""

from __future__ import annotations

from dataclasses import dataclass

from .api import DtuProxyApi
from .coordinator import ClientFleetCoordinator, MeterCoordinator, ProxyStatusCoordinator


@dataclass
class DtuProxyRuntimeData:
    """Objects owned by one config entry."""

    api: DtuProxyApi
    status: ProxyStatusCoordinator
    meter: MeterCoordinator
    clients: ClientFleetCoordinator
    proxy_device_id: str
