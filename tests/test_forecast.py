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

from custom_components.solar_surplus.const import (
    CONF_BATTERY_CAPACITY,
    CONF_BATTERY_SOC,
    CONF_FORECAST_ENTRIES,
)
from custom_components.solar_surplus.forecast import (
    ForecastReader,
    power_now,
    remaining_today,
    to_periods,
)

from .conftest import HEATING_ROD_DATA, grid, hub

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


async def test_each_consumer_says_when_it_is_expected_to_run(
    hass: HomeAssistant, setup_entry, roof
) -> None:
    now = dt_util.now()
    start = _hour(now)
    sky = roof(
        {
            start: 300,
            start + HOUR: 3000,
            start + 2 * HOUR: 3000,
            start + 3 * HOUR: 300,
        }
    )
    entry = hub(HEATING_ROD_DATA, **{CONF_FORECAST_ENTRIES: [sky.entry_id]})
    entry.add_to_hass(hass)
    grid(hass, 0)
    coordinator = await setup_entry(entry)
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    state = hass.states.get("sensor.heating_rod_status")
    # Base load and reserve take 500 W: 2500 W are left for the 2000 W rod.
    assert dt_util.parse_datetime(state.attributes["expected_on"]) == start + HOUR
    assert dt_util.parse_datetime(state.attributes["expected_off"]) == start + 3 * HOUR
    assert state.attributes["recommended_start"] is None
    plan = coordinator.data.to_dict()["plan"]
    assert [len(p["windows"]) for p in plan.values()] == [1]


async def test_with_its_capacity_the_battery_charge_is_forecast(
    hass: HomeAssistant, setup_entry, roof
) -> None:
    now = dt_util.now()
    start = _hour(now)
    sky = roof({start + HOUR: 2500})
    entry = hub(
        **{
            CONF_FORECAST_ENTRIES: [sky.entry_id],
            CONF_BATTERY_SOC: "sensor.battery_soc",
            CONF_BATTERY_CAPACITY: 10,
        }
    )
    entry.add_to_hass(hass)
    grid(hass, 0)
    hass.states.async_set("sensor.battery_soc", "50")
    coordinator = await setup_entry(entry)
    await coordinator.async_refresh()

    points = coordinator.data.to_dict()["soc_forecast"]
    # 2500 W less 400 W base load for an hour: 2.1 kWh, 21 % of 10 kWh.
    assert points[-1] == {"time": (start + 2 * HOUR).isoformat(), "soc": 71.0}
