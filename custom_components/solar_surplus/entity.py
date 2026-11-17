"""Shared entity base classes."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import Consumer, SolarSurplusCoordinator
from .models import ConsumerDecision

MANUFACTURER = "Solar Surplus"


class HubEntity(CoordinatorEntity[SolarSurplusCoordinator]):
    """An entity on the hub's device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: SolarSurplusCoordinator, key: str) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer=MANUFACTURER,
            model="Hub",
            entry_type=DeviceEntryType.SERVICE,
        )


class ConsumerEntity(CoordinatorEntity[SolarSurplusCoordinator]):
    """An entity on one consumer's own device.

    The consumer gets a device of this integration rather than hanging off the
    one it is switched through: a consumer can be switched through scripts, or
    through two contacts that belong to different devices.
    """

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: SolarSurplusCoordinator, consumer: Consumer, key: str
    ) -> None:
        super().__init__(coordinator)
        self._consumer_id = consumer.id
        self._attr_unique_id = f"{consumer.id}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, consumer.id)},
            name=consumer.title,
            manufacturer=MANUFACTURER,
            model="Consumer",
            via_device_id=coordinator.hub_device_id,
        )

    @property
    def decision(self) -> ConsumerDecision | None:
        """This consumer's part of the last run."""
        data = self.coordinator.data
        return data.consumer(self._consumer_id) if data else None
