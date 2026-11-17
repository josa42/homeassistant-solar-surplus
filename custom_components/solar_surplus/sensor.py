"""Sensors: the surplus, the forecast, the energy signal and each consumer's status."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import UnitOfEnergy, UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import ConsumerState, EnergySignal
from .coordinator import Consumer, SolarSurplusConfigEntry, SolarSurplusCoordinator
from .entity import ConsumerEntity, HubEntity
from .forecast import power_now, remaining_today
from .models import Decision


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SolarSurplusConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    hub: list[SensorEntity] = [
        PowerSensor(coordinator, description) for description in POWER_SENSORS
    ]
    if coordinator.forecast.configured:
        hub += [ForecastRemainingSensor(coordinator), ForecastPowerSensor(coordinator)]
    hub.append(EnergySignalSensor(coordinator))
    async_add_entities(hub)
    for consumer in coordinator.consumers.values():
        async_add_entities(
            [StatusSensor(coordinator, consumer)], config_subentry_id=consumer.id
        )


@dataclass(frozen=True, slots=True)
class PowerDescription:
    key: str
    value: Callable[[Decision], float | None]


POWER_SENSORS = (
    PowerDescription("surplus", lambda decision: decision.surplus),
    PowerDescription("allocated_power", lambda decision: decision.allocated),
    PowerDescription("remaining_power", lambda decision: decision.remaining),
)


class PowerSensor(HubEntity, SensorEntity):
    """A power figure of the last run."""

    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_suggested_display_precision = 0

    def __init__(
        self, coordinator: SolarSurplusCoordinator, description: PowerDescription
    ) -> None:
        super().__init__(coordinator, description.key)
        self._value = description.value

    @property
    def native_value(self) -> float | None:
        data = self.coordinator.data
        value = None if data is None else self._value(data)
        return None if value is None else round(value)


class ForecastRemainingSensor(HubEntity, SensorEntity):
    """The solar energy still expected today."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_suggested_display_precision = 1

    def __init__(self, coordinator: SolarSurplusCoordinator) -> None:
        super().__init__(coordinator, "forecast_remaining_today")

    @property
    def native_value(self) -> float | None:
        data = self.coordinator.data
        if data is None or not data.forecast:
            return None
        return round(remaining_today(data.forecast, dt_util.now()) / 1000, 3)


class ForecastPowerSensor(HubEntity, SensorEntity):
    """The solar power the forecast expects right now."""

    _attr_device_class = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_suggested_display_precision = 0

    def __init__(self, coordinator: SolarSurplusCoordinator) -> None:
        super().__init__(coordinator, "forecast_power")

    @property
    def native_value(self) -> float | None:
        data = self.coordinator.data
        if data is None or not data.forecast:
            return None
        value = power_now(data.forecast, dt_util.now())
        return None if value is None else round(value)


class EnergySignalSensor(HubEntity, SensorEntity):
    """The energy signal other integrations follow, after SG Ready 1 to 4.

    Text states rather than numbers: a unitless number would be taken for a
    measurement and drawn as a line. Without a grid reading it is unavailable
    rather than a guess, and whoever follows it falls back to normal.
    """

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = [signal.value for signal in EnergySignal]

    def __init__(self, coordinator: SolarSurplusCoordinator) -> None:
        super().__init__(coordinator, "energy_signal")

    @property
    def available(self) -> bool:
        data = self.coordinator.data
        return super().available and data is not None and data.signal.state is not None

    @property
    def native_value(self) -> str | None:
        data = self.coordinator.data
        return data.signal.state.value if data and data.signal.state else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data
        if data is None or data.signal.state is None:
            return {}
        signal = data.signal
        attributes: dict[str, Any] = {
            "reason": signal.reason.value,
            "since": signal.since.isoformat() if signal.since else None,
        }
        if signal.until is not None:
            attributes["until"] = signal.until.isoformat()
        return attributes


class StatusSensor(ConsumerEntity, SensorEntity):
    """What a consumer is doing, and why."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = [state.value for state in ConsumerState]
    #: The details change with every run; the history needs the state and the
    #: reason, not every figure behind them.
    _unrecorded_attributes = frozenset(
        {
            "power",
            "needed",
            "available",
            "until",
            "level",
            "deadline",
            "latest_start",
            "expected_start",
            "started_at",
            "expected_end",
            "finished_at",
        }
    )

    def __init__(
        self, coordinator: SolarSurplusCoordinator, consumer: Consumer
    ) -> None:
        super().__init__(coordinator, consumer, "status")

    @property
    def native_value(self) -> str | None:
        decision = self.decision
        return decision.state.value if decision else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        decision = self.decision
        if decision is None:
            return {}
        attributes: dict[str, Any] = {
            "reason": decision.reason.value,
            "power": round(decision.power),
        }
        for key, value in decision.details.items():
            attributes[key] = (
                value.isoformat() if hasattr(value, "isoformat") else value
            )
        return attributes
