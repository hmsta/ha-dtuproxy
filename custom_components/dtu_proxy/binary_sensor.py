"""Binary sensor entities for DTU Proxy."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import DtuProxyConfigEntry
from .coordinator import MeterCoordinator, ProxyStatusCoordinator
from .entity import (
    client_device_info,
    gateway_ids,
    meter_device_info,
    nested_value,
    proxy_client,
    proxy_device_info,
)

BoolFn = Callable[[dict[str, Any]], bool | None]


@dataclass(frozen=True, kw_only=True)
class DtuBinaryDescription(BinarySensorEntityDescription):
    """Describe a DTU Proxy binary sensor."""

    value_fn: BoolFn


def _fleet_healthy(data: dict[str, Any]) -> bool:
    clients = data.get("clients")
    if not isinstance(clients, list):
        return False
    expected = [client for client in clients if isinstance(client, dict) and bool(client.get("id"))]
    if not expected:
        return False
    masters = sum(1 for client in expected if client.get("role") == 1)
    return masters == 1 and all(
        bool(client.get("connected"))
        and bool(client.get("healthy"))
        and bool(client.get("cache_synchronized"))
        for client in expected
    )


def _active_master_dtu_confirmed(data: dict[str, Any]) -> bool:
    """Return whether the one active master has confirmed local DTU traffic."""
    clients = data.get("clients")
    if not isinstance(clients, list):
        return False
    masters = [client for client in clients if isinstance(client, dict) and client.get("role") == 1]
    return len(masters) == 1 and bool(masters[0].get("master_dtu_confirmed"))


PROXY_BINARY_SENSORS: tuple[DtuBinaryDescription, ...] = (
    DtuBinaryDescription(
        key="fleet_healthy",
        translation_key="fleet_healthy",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        value_fn=_fleet_healthy,
    ),
    DtuBinaryDescription(
        key="active_master_dtu_confirmed",
        translation_key="active_master_dtu_confirmed",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        value_fn=_active_master_dtu_confirmed,
    ),
    DtuBinaryDescription(
        key="ethernet_link",
        translation_key="ethernet_link",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: bool(nested_value(data, "network", "ethernet_link_up")),
    ),
    DtuBinaryDescription(
        key="wifi_connected",
        translation_key="wifi_connected",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: bool(nested_value(data, "network", "wifi_sta_connected")),
    ),
    DtuBinaryDescription(
        key="network_transition",
        translation_key="network_transition",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: bool(data.get("network_transition_active")),
    ),
)


CLIENT_BINARY_SENSORS: tuple[DtuBinaryDescription, ...] = (
    DtuBinaryDescription(
        key="connected",
        translation_key="connected",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        value_fn=lambda data: bool(data.get("connected")),
    ),
    DtuBinaryDescription(
        key="healthy",
        translation_key="healthy",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        value_fn=lambda data: bool(data.get("healthy")),
    ),
    DtuBinaryDescription(
        key="cache_synchronized",
        translation_key="cache_synchronized",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        value_fn=lambda data: bool(data.get("cache_synchronized")),
    ),
    DtuBinaryDescription(
        key="resynchronizing",
        translation_key="resynchronizing",
        device_class=BinarySensorDeviceClass.RUNNING,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: bool(data.get("resyncing")),
    ),
)


def _first_meter(data: dict[str, Any]) -> dict[str, Any] | None:
    meter_data = data.get("meterData")
    if isinstance(meter_data, list) and meter_data and isinstance(meter_data[0], dict):
        return meter_data[0]
    return None


METER_BINARY_SENSORS: tuple[DtuBinaryDescription, ...] = (
    DtuBinaryDescription(
        key="meter_data_available",
        translation_key="meter_data_available",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        value_fn=lambda data: _first_meter(data) is not None,
    ),
    DtuBinaryDescription(
        key="power_data_available",
        translation_key="power_data_available",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: (
            (meter := _first_meter(data)) is not None and meter.get("phaseTotalPower") is not None
        ),
    ),
    DtuBinaryDescription(
        key="energy_data_available",
        translation_key="energy_data_available",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: (
            (meter := _first_meter(data)) is not None and meter.get("energyTotalPower") is not None
        ),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DtuProxyConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up all binary sensors."""
    runtime = entry.runtime_data
    async_add_entities(
        [DtuProxyBinarySensor(entry, description) for description in PROXY_BINARY_SENSORS]
        + [DtuMeterBinarySensor(entry, description) for description in METER_BINARY_SENSORS]
    )

    known_clients: set[str] = set()

    @callback
    def add_new_clients() -> None:
        ids = gateway_ids(runtime.status.data or {})
        new_ids = ids - known_clients
        if not new_ids:
            return
        async_add_entities(
            DtuClientBinarySensor(entry, gateway_id, description)
            for gateway_id in sorted(new_ids)
            for description in CLIENT_BINARY_SENSORS
        )
        known_clients.update(new_ids)

    add_new_clients()
    entry.async_on_unload(runtime.status.async_add_listener(add_new_clients))


class DtuProxyBinarySensor(CoordinatorEntity[ProxyStatusCoordinator], BinarySensorEntity):
    """A binary sensor attached to the proxy."""

    _attr_has_entity_name = True

    def __init__(self, entry: DtuProxyConfigEntry, description: DtuBinaryDescription) -> None:
        super().__init__(entry.runtime_data.status)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}:proxy:{description.key}"
        self._attr_device_info = proxy_device_info(entry, entry.runtime_data)

    @property
    def is_on(self) -> bool | None:
        """Return the current state."""
        return self.entity_description.value_fn(self.coordinator.data or {})


class DtuClientBinarySensor(CoordinatorEntity[ProxyStatusCoordinator], BinarySensorEntity):
    """A binary sensor for one proxy-observed client."""

    _attr_has_entity_name = True

    def __init__(
        self,
        entry: DtuProxyConfigEntry,
        gateway_id: str,
        description: DtuBinaryDescription,
    ) -> None:
        super().__init__(entry.runtime_data.status)
        self.entity_description = description
        self._gateway_id = gateway_id
        self._attr_unique_id = f"{entry.entry_id}:client:{gateway_id}:{description.key}"
        self._attr_device_info = client_device_info(entry, entry.runtime_data, gateway_id)

    @property
    def _client(self) -> dict[str, Any] | None:
        return proxy_client(self.coordinator.data or {}, self._gateway_id)

    @property
    def available(self) -> bool:
        """Return whether the proxy still reports this client slot."""
        return super().available and self._client is not None

    @property
    def is_on(self) -> bool | None:
        """Return the current state."""
        client = self._client
        return self.entity_description.value_fn(client) if client else None


class DtuMeterBinarySensor(CoordinatorEntity[MeterCoordinator], BinarySensorEntity):
    """A meter-block availability sensor."""

    _attr_has_entity_name = True

    def __init__(self, entry: DtuProxyConfigEntry, description: DtuBinaryDescription) -> None:
        super().__init__(entry.runtime_data.meter)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}:meter:{description.key}"
        self._attr_device_info = meter_device_info(entry, entry.runtime_data)

    @property
    def is_on(self) -> bool | None:
        """Return whether the decoded block is available and fresh."""
        return self.entity_description.value_fn(self.coordinator.data or {})
