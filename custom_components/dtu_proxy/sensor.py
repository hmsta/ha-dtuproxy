"""Sensor entities for DTU Proxy."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfInformation,
    UnitOfPower,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from . import DtuProxyConfigEntry
from .coordinator import ClientFleetCoordinator, MeterCoordinator, ProxyStatusCoordinator
from .entity import (
    client_device_info,
    gateway_ids,
    meter_device_info,
    nested_value,
    proxy_client,
    proxy_device_info,
)

ValueFn = Callable[[dict[str, Any]], Any]
AvailableFn = Callable[[dict[str, Any]], bool]


@dataclass(frozen=True, kw_only=True)
class DtuSensorDescription(SensorEntityDescription):
    """Describe a DTU Proxy sensor."""

    value_fn: ValueFn
    available_fn: AvailableFn | None = None
    stable_last_boot: bool = False


class _LastBootTracker:
    """Derive a stable boot timestamp from changing uptime data."""

    _last_boot: datetime | None = None
    _last_boot_count: int | None = None
    _last_uptime_ms: int | float | None = None

    def _stable_last_boot(self, data: dict[str, Any]) -> datetime | None:
        uptime_ms = nested_value(data, "runtime", "uptime_ms")
        if not isinstance(uptime_ms, (int, float)) or uptime_ms < 0:
            return None

        boot_count = nested_value(data, "runtime", "boot_count")
        valid_boot_count = boot_count if isinstance(boot_count, int) else None
        rebooted = (
            self._last_boot is None
            or (
                valid_boot_count is not None
                and self._last_boot_count is not None
                and valid_boot_count != self._last_boot_count
            )
            or (self._last_uptime_ms is not None and uptime_ms < self._last_uptime_ms)
        )
        if rebooted:
            self._last_boot = (dt_util.utcnow() - timedelta(milliseconds=uptime_ms)).replace(
                microsecond=0
            )

        self._last_boot_count = valid_boot_count
        self._last_uptime_ms = uptime_ms
        return self._last_boot


def _count_clients(data: dict[str, Any], key: str) -> int:
    clients = data.get("clients")
    if not isinstance(clients, list):
        return 0
    return sum(1 for client in clients if isinstance(client, dict) and bool(client.get(key)))


def _master(data: dict[str, Any]) -> str:
    clients = data.get("clients")
    if not isinstance(clients, list):
        return "none"
    masters = [
        str(client.get("id"))
        for client in clients
        if isinstance(client, dict) and client.get("id") and client.get("role") == 1
    ]
    return masters[0] if len(masters) == 1 else ("none" if not masters else "multiple")


def _milliseconds_to_seconds(field: str) -> ValueFn:
    """Convert a nullable millisecond value to seconds."""

    def value(data: dict[str, Any]) -> Any:
        raw = data.get(field)
        return raw / 1000 if isinstance(raw, (int, float)) else None

    return value


PROXY_SENSORS: tuple[DtuSensorDescription, ...] = (
    DtuSensorDescription(
        key="connected_clients",
        translation_key="connected_clients",
        icon="mdi:lan-connect",
        value_fn=lambda data: _count_clients(data, "connected"),
    ),
    DtuSensorDescription(
        key="healthy_clients",
        translation_key="healthy_clients",
        icon="mdi:check-network",
        entity_registry_enabled_default=False,
        value_fn=lambda data: _count_clients(data, "healthy"),
    ),
    DtuSensorDescription(
        key="active_master",
        translation_key="active_master",
        icon="mdi:account-network",
        value_fn=_master,
    ),
    DtuSensorDescription(
        key="temperature",
        translation_key="temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda data: (
            nested_value(data, "temperature", "celsius")
            if nested_value(data, "temperature", "valid")
            else None
        ),
    ),
    DtuSensorDescription(
        key="wifi_rssi",
        translation_key="wifi_rssi",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement="dBm",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: nested_value(data, "network", "wifi_sta_rssi"),
        available_fn=lambda data: (
            nested_value(data, "network", "wifi_sta_connected") is True
            and isinstance(nested_value(data, "network", "wifi_sta_rssi"), (int, float))
        ),
    ),
    DtuSensorDescription(
        key="last_boot",
        translation_key="last_boot",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: None,
        stable_last_boot=True,
    ),
    DtuSensorDescription(
        key="cache_entries",
        translation_key="cache_entries",
        icon="mdi:database",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.get("cache_entries"),
    ),
    DtuSensorDescription(
        key="cache_generation",
        translation_key="cache_generation",
        icon="mdi:counter",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.get("generation"),
    ),
    DtuSensorDescription(
        key="free_heap",
        translation_key="free_heap",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: nested_value(data, "runtime", "free_heap_bytes"),
    ),
    DtuSensorDescription(
        key="reset_reason",
        translation_key="reset_reason",
        icon="mdi:restart-alert",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: nested_value(data, "runtime", "reset_reason_name"),
    ),
)


CLIENT_SENSORS: tuple[DtuSensorDescription, ...] = (
    DtuSensorDescription(
        key="dtu_presence",
        translation_key="dtu_presence",
        icon="mdi:solar-power-variant",
        value_fn=lambda data: data.get("dtu_presence", "unknown"),
    ),
    DtuSensorDescription(
        key="wifi_rssi",
        translation_key="wifi_rssi",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement="dBm",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: nested_value(data, "wifi", "connected_rssi"),
    ),
    DtuSensorDescription(
        key="cache_ack_age",
        translation_key="cache_ack_age",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        suggested_display_precision=1,
        value_fn=_milliseconds_to_seconds("cache_ack_age_ms"),
    ),
    DtuSensorDescription(
        key="prepare_timeouts",
        translation_key="prepare_timeouts",
        icon="mdi:timer-alert-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.get("prepare_timeouts"),
    ),
    DtuSensorDescription(
        key="commit_timeouts",
        translation_key="commit_timeouts",
        icon="mdi:timer-alert-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.get("commit_timeouts"),
    ),
    DtuSensorDescription(
        key="master_attempts",
        translation_key="master_attempts",
        icon="mdi:counter",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.get("attempts"),
    ),
)


DIRECT_CLIENT_SENSORS: tuple[DtuSensorDescription, ...] = (
    DtuSensorDescription(
        key="client_temperature",
        translation_key="temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda data: (
            nested_value(data, "temperature", "celsius")
            if nested_value(data, "temperature", "valid")
            else None
        ),
    ),
    DtuSensorDescription(
        key="last_boot",
        translation_key="last_boot",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: None,
        stable_last_boot=True,
    ),
    DtuSensorDescription(
        key="proxy_receive_age",
        translation_key="proxy_receive_age",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        suggested_display_precision=1,
        value_fn=_milliseconds_to_seconds("proxy_rx_age_ms"),
    ),
    DtuSensorDescription(
        key="client_free_heap",
        translation_key="free_heap",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: nested_value(data, "runtime", "free_heap_bytes"),
    ),
    DtuSensorDescription(
        key="client_reset_reason",
        translation_key="reset_reason",
        icon="mdi:restart-alert",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: nested_value(data, "runtime", "reset_reason_name"),
    ),
)


def _scaled(field: str, divisor: float = 1.0) -> ValueFn:
    def value(data: dict[str, Any]) -> Any:
        raw = data.get(field)
        return raw / divisor if isinstance(raw, (int, float)) else None

    return value


def _power(key: str, field: str) -> DtuSensorDescription:
    return DtuSensorDescription(
        key=key,
        translation_key=key,
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=_scaled(field),
    )


def _voltage(key: str, field: str) -> DtuSensorDescription:
    return DtuSensorDescription(
        key=key,
        translation_key=key,
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=_scaled(field, 100),
    )


def _current(key: str, field: str) -> DtuSensorDescription:
    return DtuSensorDescription(
        key=key,
        translation_key=key,
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=3,
        value_fn=_scaled(field, 1000),
    )


def _power_factor(key: str, field: str) -> DtuSensorDescription:
    return DtuSensorDescription(
        key=key,
        translation_key=key,
        device_class=SensorDeviceClass.POWER_FACTOR,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=_scaled(field, 10),
    )


def _energy(key: str, field: str) -> DtuSensorDescription:
    return DtuSensorDescription(
        key=key,
        translation_key=key,
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=0,
        value_fn=_scaled(field),
    )


METER_SENSORS: tuple[DtuSensorDescription, ...] = (
    DtuSensorDescription(
        key="fault_code",
        translation_key="fault_code",
        icon="mdi:alert-circle-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_scaled("faultCode"),
    ),
    _power("total_power", "phaseTotalPower"),
    _power("phase_a_power", "phaseAPower"),
    _power("phase_b_power", "phaseBPower"),
    _power("phase_c_power", "phaseCPower"),
    _voltage("phase_a_voltage", "voltagePhaseA"),
    _voltage("phase_b_voltage", "voltagePhaseB"),
    _voltage("phase_c_voltage", "voltagePhaseC"),
    _current("phase_a_current", "currentPhaseA"),
    _current("phase_b_current", "currentPhaseB"),
    _current("phase_c_current", "currentPhaseC"),
    _power_factor("total_power_factor", "powerFactorTotal"),
    _power_factor("phase_a_power_factor", "powerFactorPhaseA"),
    _power_factor("phase_b_power_factor", "powerFactorPhaseB"),
    _power_factor("phase_c_power_factor", "powerFactorPhaseC"),
    _energy("exported_energy", "energyTotalPower"),
    _energy("imported_energy", "energyTotalConsumed"),
    _energy("phase_a_exported_energy", "energyPhaseA"),
    _energy("phase_b_exported_energy", "energyPhaseB"),
    _energy("phase_c_exported_energy", "energyPhaseC"),
    _energy("phase_a_imported_energy", "energyPhaseAConsumed"),
    _energy("phase_b_imported_energy", "energyPhaseBConsumed"),
    _energy("phase_c_imported_energy", "energyPhaseCConsumed"),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DtuProxyConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up all DTU Proxy sensors."""
    runtime = entry.runtime_data
    async_add_entities(
        [DtuProxySensor(entry, description) for description in PROXY_SENSORS]
        + [DtuMeterSensor(entry, description) for description in METER_SENSORS]
    )

    known_clients: set[str] = set()

    @callback
    def add_new_clients() -> None:
        ids = gateway_ids(runtime.status.data or {})
        new_ids = ids - known_clients
        if not new_ids:
            return
        entities: list[SensorEntity] = []
        for gateway_id in sorted(new_ids):
            entities.extend(
                DtuClientSensor(entry, gateway_id, description) for description in CLIENT_SENSORS
            )
            entities.extend(
                DtuDirectClientSensor(entry, gateway_id, description)
                for description in DIRECT_CLIENT_SENSORS
            )
        known_clients.update(new_ids)
        async_add_entities(entities)

    add_new_clients()
    entry.async_on_unload(runtime.status.async_add_listener(add_new_clients))


class DtuProxySensor(_LastBootTracker, CoordinatorEntity[ProxyStatusCoordinator], SensorEntity):
    """A sensor attached to the proxy device."""

    _attr_has_entity_name = True

    def __init__(self, entry: DtuProxyConfigEntry, description: DtuSensorDescription) -> None:
        super().__init__(entry.runtime_data.status)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}:proxy:{description.key}"
        self._attr_device_info = proxy_device_info(entry, entry.runtime_data)

    @property
    def available(self) -> bool:
        """Return whether this proxy sensor currently has a usable value."""
        available_fn = self.entity_description.available_fn
        return super().available and (
            available_fn(self.coordinator.data or {}) if available_fn else True
        )

    @property
    def native_value(self) -> Any:
        """Return the current value."""
        if self.entity_description.stable_last_boot:
            return self._stable_last_boot(self.coordinator.data or {})
        return self.entity_description.value_fn(self.coordinator.data or {})


class DtuClientSensor(CoordinatorEntity[ProxyStatusCoordinator], SensorEntity):
    """A client sensor observed by the proxy."""

    _attr_has_entity_name = True

    def __init__(
        self,
        entry: DtuProxyConfigEntry,
        gateway_id: str,
        description: DtuSensorDescription,
    ) -> None:
        super().__init__(entry.runtime_data.status)
        self.entity_description = description
        self._gateway_id = gateway_id
        self._attr_unique_id = f"{entry.entry_id}:client:{gateway_id}:{description.key}"
        self._attr_device_info = client_device_info(entry, entry.runtime_data, gateway_id)

    @property
    def available(self) -> bool:
        """Return whether this client is still represented by the proxy."""
        return super().available and self._client is not None

    @property
    def _client(self) -> dict[str, Any] | None:
        return proxy_client(self.coordinator.data or {}, self._gateway_id)

    @property
    def native_value(self) -> Any:
        """Return the current value."""
        client = self._client
        return self.entity_description.value_fn(client) if client else None


class DtuDirectClientSensor(
    _LastBootTracker, CoordinatorEntity[ClientFleetCoordinator], SensorEntity
):
    """A diagnostic sensor fetched directly from a client."""

    _attr_has_entity_name = True

    def __init__(
        self,
        entry: DtuProxyConfigEntry,
        gateway_id: str,
        description: DtuSensorDescription,
    ) -> None:
        super().__init__(entry.runtime_data.clients)
        self.entity_description = description
        self._gateway_id = gateway_id
        self._attr_unique_id = f"{entry.entry_id}:client:{gateway_id}:{description.key}"
        self._attr_device_info = client_device_info(entry, entry.runtime_data, gateway_id)

    @property
    def _client(self) -> dict[str, Any] | None:
        return (self.coordinator.data or {}).get(self._gateway_id)

    @property
    def available(self) -> bool:
        """Return whether the client responded at its discovered address."""
        return super().available and self._client is not None

    @property
    def native_value(self) -> Any:
        """Return the current value."""
        client = self._client
        if client is None:
            return None
        if self.entity_description.stable_last_boot:
            return self._stable_last_boot(client)
        return self.entity_description.value_fn(client)


class DtuMeterSensor(CoordinatorEntity[MeterCoordinator], SensorEntity):
    """A decoded physical meter sensor."""

    _attr_has_entity_name = True

    def __init__(self, entry: DtuProxyConfigEntry, description: DtuSensorDescription) -> None:
        super().__init__(entry.runtime_data.meter)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}:meter:{description.key}"
        self._attr_device_info = meter_device_info(entry, entry.runtime_data)

    @property
    def _meter(self) -> dict[str, Any] | None:
        data = self.coordinator.data or {}
        meter_data = data.get("meterData")
        if (
            not isinstance(meter_data, list)
            or not meter_data
            or not isinstance(meter_data[0], dict)
        ):
            return None
        return meter_data[0]

    @property
    def available(self) -> bool:
        """Make each field independently unavailable when firmware reports null."""
        meter = self._meter
        return (
            super().available
            and meter is not None
            and self.entity_description.value_fn(meter) is not None
        )

    @property
    def native_value(self) -> Any:
        """Return the scaled meter value."""
        meter = self._meter
        return self.entity_description.value_fn(meter) if meter else None
