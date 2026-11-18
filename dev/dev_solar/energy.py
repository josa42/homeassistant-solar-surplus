"""The forecast, as the energy dashboard and Solar Surplus read it."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from .sun import forecast


async def async_get_solar_forecast(
    hass: HomeAssistant, config_entry_id: str
) -> dict[str, Any]:
    return {"wh_hours": forecast(hass)}
