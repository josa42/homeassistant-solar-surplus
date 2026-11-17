"""The solar forecast, read through the energy platform of other integrations.

Forecast.Solar, Solcast and others all feed the energy dashboard through the
same function, `async_get_solar_forecast`, which returns watt-hours per period.
Reading it there means none of them is special here, and several (one per roof)
simply add up.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.loader import IntegrationNotFound, async_get_integration
from homeassistant.util import dt as dt_util

from .const import FORECAST_REFRESH
from .models import ForecastPeriod

_LOGGER = logging.getLogger(__name__)

HOUR = timedelta(hours=1)


class ForecastReader:
    """Reads and caches the forecast of the chosen config entries."""

    def __init__(self, hass: HomeAssistant, entry_ids: list[str]) -> None:
        self._hass = hass
        self._entry_ids = list(entry_ids)
        self._periods: tuple[ForecastPeriod, ...] = ()
        self._read_at: datetime | None = None

    @property
    def configured(self) -> bool:
        """Whether any forecast was chosen at all."""
        return bool(self._entry_ids)

    async def async_get(self, now: datetime) -> tuple[ForecastPeriod, ...]:
        """The forecast from the start of today on, read again when it is stale."""
        if not self._entry_ids:
            return ()
        if (
            self._read_at is not None
            and now - self._read_at < FORECAST_REFRESH
            and self._periods
        ):
            return self._periods
        self._read_at = now
        watt_hours: dict[datetime, float] = {}
        for entry_id in self._entry_ids:
            for start, value in (await self._async_read(entry_id)).items():
                watt_hours[start] = watt_hours.get(start, 0.0) + value
        today = dt_util.start_of_local_day(now)
        self._periods = tuple(
            period for period in to_periods(watt_hours) if period.end > today
        )
        return self._periods

    async def _async_read(self, entry_id: str) -> dict[datetime, float]:
        entry = self._hass.config_entries.async_get_entry(entry_id)
        if entry is None or entry.state is not ConfigEntryState.LOADED:
            return {}
        try:
            integration = await async_get_integration(self._hass, entry.domain)
            platform = await integration.async_get_platform("energy")
        except IntegrationNotFound, ImportError:
            _LOGGER.warning("%s has no solar forecast to read", entry.title)
            return {}
        get_forecast = getattr(platform, "async_get_solar_forecast", None)
        if get_forecast is None:
            return {}
        try:
            result = await get_forecast(self._hass, entry_id)
        except Exception:  # noqa: BLE001 - another integration's failure is not ours
            _LOGGER.exception("Reading the solar forecast of %s failed", entry.title)
            return {}
        values: dict[datetime, float] = {}
        for key, value in ((result or {}).get("wh_hours") or {}).items():
            start = dt_util.parse_datetime(key)
            if start is None or not isinstance(value, int | float):
                continue
            values[start] = float(value)
        return values


def to_periods(watt_hours: dict[datetime, float]) -> tuple[ForecastPeriod, ...]:
    """Turn watt-hours per period start into average power per period.

    The periods are as long as the closest two starts are apart, an hour at
    most: Forecast.Solar reports hours, Solcast half hours.
    """
    starts = sorted(watt_hours)
    gaps = [
        later - earlier
        for earlier, later in zip(starts, starts[1:], strict=False)
        if later > earlier
    ]
    length = min([HOUR, *gaps])
    hours = length / HOUR
    return tuple(
        ForecastPeriod(start=start, end=start + length, watts=watt_hours[start] / hours)
        for start in starts
    )


def remaining_today(periods: tuple[ForecastPeriod, ...], now: datetime) -> float:
    """The energy still expected today, in watt-hours."""
    end_of_day = dt_util.start_of_local_day(now) + timedelta(days=1)
    total = 0.0
    for period in periods:
        start = max(period.start, now)
        end = min(period.end, end_of_day)
        if end > start:
            total += period.watts * ((end - start) / HOUR)
    return total


def power_now(periods: tuple[ForecastPeriod, ...], now: datetime) -> float | None:
    """The power the forecast expects right now."""
    for period in periods:
        if period.start <= now < period.end:
            return period.watts
    return None
