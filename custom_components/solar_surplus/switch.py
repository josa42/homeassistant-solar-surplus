"""The switch that lets the allocation write, or only show what it would do."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import STATE_OFF
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .coordinator import SolarSurplusConfigEntry, SolarSurplusCoordinator
from .entity import HubEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SolarSurplusConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([ControlSwitch(entry.runtime_data)])


class ControlSwitch(HubEntity, SwitchEntity, RestoreEntity):
    """Off, every decision is still made and shown, but nothing is switched.

    It keeps its state across a restart, so a house left in manual stays there.
    """

    def __init__(self, coordinator: SolarSurplusCoordinator) -> None:
        super().__init__(coordinator, "control")

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state == STATE_OFF:
            self.coordinator.async_set_control(False)

    @property
    def is_on(self) -> bool:
        return self.coordinator.control_enabled

    async def async_turn_on(self, **kwargs: Any) -> None:
        self.coordinator.async_set_control(True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self.coordinator.async_set_control(False)
        self.async_write_ha_state()
