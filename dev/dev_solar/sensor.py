"""What the array produces right now."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfPower
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.util import dt as dt_util

from .sun import INPUTS, power_at


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([SolarPowerSensor(entry)])


class SolarPowerSensor(SensorEntity):
    _attr_name = "Dev solar power"
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry) -> None:
        self._attr_unique_id = f"{entry.entry_id}_power"

    async def async_added_to_hass(self) -> None:
        @callback
        def _update(*_: Event | object) -> None:
            self._attr_native_value = power_at(self.hass, dt_util.now())
            self.async_write_ha_state()

        self.async_on_remove(
            async_track_state_change_event(self.hass, list(INPUTS), _update)
        )
        self.async_on_remove(
            async_track_time_interval(self.hass, _update, timedelta(seconds=10))
        )
        _update()
