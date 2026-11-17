"""The Solar Surplus integration."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN
from .coordinator import SolarSurplusConfigEntry, SolarSurplusCoordinator
from .store import SolarSurplusStore

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup_entry(
    hass: HomeAssistant, entry: SolarSurplusConfigEntry
) -> bool:
    """Set up Solar Surplus from a config entry."""
    store = SolarSurplusStore(hass)
    await store.async_load(entry.subentries)
    coordinator = SolarSurplusCoordinator(hass, entry, store)
    entry.runtime_data = coordinator
    await coordinator.async_config_entry_first_refresh()
    coordinator.async_start_watching()
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: SolarSurplusConfigEntry
) -> bool:
    """Unload a config entry."""
    await entry.runtime_data.async_shutdown()
    return True


async def _async_reload(hass: HomeAssistant, entry: SolarSurplusConfigEntry) -> None:
    """Reload when the options or the consumers change."""
    await hass.config_entries.async_reload(entry.entry_id)
