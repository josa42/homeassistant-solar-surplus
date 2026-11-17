"""A hand on each consumer: automatic, on or off."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import Override
from .coordinator import Consumer, SolarSurplusConfigEntry, SolarSurplusCoordinator
from .entity import ConsumerEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SolarSurplusConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    for consumer in coordinator.consumers.values():
        async_add_entities(
            [OverrideSelect(coordinator, consumer)], config_subentry_id=consumer.id
        )


class OverrideSelect(ConsumerEntity, SelectEntity):
    """The same hand the panel sets. Automatic lets the allocation decide."""

    _attr_options = [override.value for override in Override]

    def __init__(
        self, coordinator: SolarSurplusCoordinator, consumer: Consumer
    ) -> None:
        super().__init__(coordinator, consumer, "override")

    @property
    def current_option(self) -> str:
        return self.coordinator.store.override(self._consumer_id).value

    async def async_select_option(self, option: str) -> None:
        self.coordinator.store.async_set_override(self._consumer_id, Override(option))
        self.async_write_ha_state()
