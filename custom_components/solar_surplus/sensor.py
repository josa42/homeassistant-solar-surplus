"""Sensors: the surplus, the forecast, each consumer's status and the signals."""

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

from .const import AdapterType, ConsumerState, EnergySignal, SgState
from .coordinator import (
    SG_STATE_NAMES,
    Consumer,
    SolarSurplusConfigEntry,
    SolarSurplusCoordinator,
)
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
    async_add_entities(hub)
    for consumer in coordinator.consumers.values():
        entities: list[SensorEntity] = [StatusSensor(coordinator, consumer)]
        if consumer.spec.adapter is AdapterType.SIGNAL:
            entities.append(EnergySignalSensor(coordinator, consumer))
        async_add_entities(entities, config_subentry_id=consumer.id)


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
            "solar_share",
            "expected_on",
            "expected_off",
            "recommended_start",
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
        plan = self.coordinator.data.plan.get(self._consumer_id)
        if plan is not None:
            for key in ("expected_on", "expected_off", "recommended_start"):
                value = getattr(plan, key)
                attributes[key] = value.isoformat() if value else None
            if plan.solar_share is not None:
                attributes["solar_share"] = plan.solar_share
        return attributes


class EnergySignalSensor(ConsumerEntity, SensorEntity):
    """What a signal consumer tells another integration, after SG Ready 1 to 4.

    Text states rather than numbers: a unitless number would be taken for a
    measurement and drawn as a line. Without a grid reading it is unavailable
    rather than a guess, and whoever follows it falls back to normal.
    """

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = [signal.value for signal in EnergySignal]

    def __init__(
        self, coordinator: SolarSurplusCoordinator, consumer: Consumer
    ) -> None:
        super().__init__(coordinator, consumer, "energy_signal")

    @property
    def available(self) -> bool:
        data = self.coordinator.data
        return super().available and data is not None and data.surplus is not None

    @property
    def native_value(self) -> str:
        # What was last told, which in test mode is not what the simulation
        # decided: the signal is not changed there either.
        level = self.coordinator.memory.consumer(self._consumer_id).signal
        return SG_STATE_NAMES[SgState(level)].value
