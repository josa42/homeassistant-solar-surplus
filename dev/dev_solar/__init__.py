"""A simulated solar array for the development instance, with a forecast.

Only for `make dev`: it is not part of Solar Surplus. The sun follows a curve
over the day, scaled by the peak power and the cloud cover set on the dev
input numbers, and the same curve, without passing clouds, is the forecast it
hands to the energy platform.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event

from .sun import FORECAST_INPUTS

PLATFORMS = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    @callback
    def _forecast_changed(event: Event) -> None:
        # Solar Surplus keeps a forecast for 15 minutes; a reload reads the
        # new one at once.
        for other in hass.config_entries.async_entries("solar_surplus"):
            hass.config_entries.async_schedule_reload(other.entry_id)

    entry.async_on_unload(
        async_track_state_change_event(hass, list(FORECAST_INPUTS), _forecast_changed)
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
