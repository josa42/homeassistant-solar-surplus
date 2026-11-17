"""Reading the solar forecast through other integrations' energy platform."""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    MockModule,
    mock_integration,
    mock_platform,
)

from custom_components.solar_surplus.forecast import (
    ForecastReader,
    power_now,
    remaining_today,
    to_periods,
)

HOUR = timedelta(hours=1)


@pytest.fixture
def roof(hass: HomeAssistant):
    """A forecast integration whose answer the test sets."""
    answers: dict[str, dict | Exception] = {}
    calls: list[str] = []

    async def async_get_solar_forecast(hass: HomeAssistant, config_entry_id: str):
        calls.append(config_entry_id)
        answer = answers.get(config_entry_id)
        if isinstance(answer, Exception):
            raise answer
        return answer

    mock_integration(hass, MockModule("roof_forecast"))
    mock_platform(
        hass,
        "roof_forecast.energy",
        SimpleNamespace(async_get_solar_forecast=async_get_solar_forecast),
    )

    def add(wh_hours: dict[datetime, float] | Exception) -> MockConfigEntry:
        entry = MockConfigEntry(domain="roof_forecast", state=ConfigEntryState.LOADED)
        entry.add_to_hass(hass)
        answers[entry.entry_id] = (
            wh_hours
            if isinstance(wh_hours, Exception)
            else {
                "wh_hours": {
                    start.isoformat(): value for start, value in wh_hours.items()
                }
            }
        )
        return entry

    add.calls = calls
    return add


def _hour(now: datetime) -> datetime:
    return now.replace(minute=0, second=0, microsecond=0)


async def test_the_forecast_is_read_as_power_per_hour(
    hass: HomeAssistant, roof
) -> None:
    now = dt_util.now()
    hour = _hour(now)
    entry = roof({hour: 1000, hour + HOUR: 2500})

    periods = await ForecastReader(hass, [entry.entry_id]).async_get(now)

    assert [(p.start, p.end, p.watts) for p in periods] == [
        (hour, hour + HOUR, 1000),
        (hour + HOUR, hour + 2 * HOUR, 2500),
    ]


async def test_two_roofs_add_up(hass: HomeAssistant, roof) -> None:
    now = dt_util.now()
    hour = _hour(now)
    east = roof({hour: 1000})
    west = roof({hour: 500})

    periods = await ForecastReader(hass, [east.entry_id, west.entry_id]).async_get(now)
    assert [p.watts for p in periods] == [1500]


async def test_the_forecast_is_reused_for_a_while(hass: HomeAssistant, roof) -> None:
    now = dt_util.now()
    entry = roof({_hour(now): 1000})
    reader = ForecastReader(hass, [entry.entry_id])

    await reader.async_get(now)
    await reader.async_get(now + timedelta(minutes=5))
    assert len(roof.calls) == 1
    await reader.async_get(now + timedelta(minutes=16))
    assert len(roof.calls) == 2


async def test_a_failing_forecast_is_left_out(hass: HomeAssistant, roof) -> None:
    now = dt_util.now()
    good = roof({_hour(now): 1000})
    bad = roof(RuntimeError("cloud API down"))

    periods = await ForecastReader(hass, [bad.entry_id, good.entry_id]).async_get(now)
    assert [p.watts for p in periods] == [1000]


async def test_an_entry_that_is_gone_or_not_loaded_is_left_out(
    hass: HomeAssistant, roof
) -> None:
    now = dt_util.now()
    entry = roof({_hour(now): 1000})
    unloaded = MockConfigEntry(
        domain="roof_forecast", state=ConfigEntryState.NOT_LOADED
    )
    unloaded.add_to_hass(hass)

    reader = ForecastReader(hass, ["missing", unloaded.entry_id, entry.entry_id])
    assert [p.watts for p in await reader.async_get(now)] == [1000]


async def test_without_a_forecast_there_is_nothing_to_read(hass: HomeAssistant) -> None:
    reader = ForecastReader(hass, [])
    assert not reader.configured
    assert await reader.async_get(dt_util.now()) == ()


def test_half_hours_are_read_as_half_hours() -> None:
    start = datetime(2026, 6, 15, 12, 0, tzinfo=dt_util.UTC)
    periods = to_periods({start: 500, start + HOUR / 2: 1000})
    assert [(p.end - p.start, p.watts) for p in periods] == [
        (HOUR / 2, 1000),
        (HOUR / 2, 2000),
    ]


async def test_what_is_left_of_today(hass: HomeAssistant) -> None:
    await hass.config.async_set_time_zone("UTC")
    start = datetime(2026, 6, 15, 12, 0, tzinfo=dt_util.UTC)
    periods = to_periods({start: 1000, start + HOUR: 2000, start + 12 * HOUR: 5000})

    now = start + HOUR / 2
    assert remaining_today(periods, now) == 500 + 2000, (
        "half the current hour, and the next; not tomorrow"
    )
    assert power_now(periods, now) == 1000
    assert power_now(periods, start - HOUR) is None
