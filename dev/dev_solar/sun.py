"""The simulated sun."""

from __future__ import annotations

import math
from datetime import datetime, timedelta

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

DOMAIN = "dev_solar"

PEAK = "input_number.dev_solar_peak"
CLOUDS = "input_number.dev_solar_clouds"
PASSING_CLOUD = "input_number.dev_solar_passing_cloud"
SHIFT = "input_number.dev_solar_shift"
INPUTS = (PEAK, CLOUDS, PASSING_CLOUD, SHIFT)
#: The ones that change the forecast too.
FORECAST_INPUTS = (PEAK, CLOUDS, SHIFT)

SUNRISE = 6.0
SUNSET = 20.0


def _value(hass: HomeAssistant, entity_id: str, default: float) -> float:
    state = hass.states.get(entity_id)
    try:
        return float(state.state) if state else default
    except ValueError:
        return default


def power_at(hass: HomeAssistant, when: datetime, *, passing: bool = True) -> float:
    """What the array produces at `when`, in watts.

    *Shift* moves the sun by whole hours, so midday can be had at night.
    """
    local = dt_util.as_local(when) + timedelta(hours=_value(hass, SHIFT, 0))
    hour = local.hour + local.minute / 60 + local.second / 3600
    if not SUNRISE < hour < SUNSET:
        return 0.0
    curve = math.sin(math.pi * (hour - SUNRISE) / (SUNSET - SUNRISE)) ** 1.5
    clouds = _value(hass, CLOUDS, 0) / 100
    power = _value(hass, PEAK, 8000) * curve * (1 - 0.8 * clouds)
    if passing:
        power *= 1 - _value(hass, PASSING_CLOUD, 0) / 100
    return round(power)


def forecast(hass: HomeAssistant) -> dict[str, float]:
    """Watt-hours per hour, today and tomorrow, without the passing cloud."""
    start = dt_util.start_of_local_day()
    return {
        (start + timedelta(hours=i)).isoformat(): power_at(
            hass, start + timedelta(hours=i, minutes=30), passing=False
        )
        for i in range(48)
    }
