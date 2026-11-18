"""The switches that let the allocation write, show, or only tell what it would do."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import STATE_OFF, STATE_ON
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
    coordinator = entry.runtime_data
    async_add_entities([ControlSwitch(coordinator), TestModeSwitch(coordinator)])


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


class TestModeSwitch(HubEntity, SwitchEntity, RestoreEntity):
    """On, nothing is switched: what would be is sent as notifications.

    The decisions are carried out in a simulation of the house, so they go on
    as if they had been, and a consumer switched on stays on.
    """

    def __init__(self, coordinator: SolarSurplusCoordinator) -> None:
        super().__init__(coordinator, "test_mode")

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state == STATE_ON:
            self.coordinator.async_set_test_mode(True)

    @property
    def is_on(self) -> bool:
        return self.coordinator.test_mode

    async def async_turn_on(self, **kwargs: Any) -> None:
        self.coordinator.async_set_test_mode(True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self.coordinator.async_set_test_mode(False)
        self.async_write_ha_state()
