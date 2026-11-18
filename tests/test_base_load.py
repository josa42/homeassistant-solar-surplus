"""The base load, learned from the energy dashboard's history."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from custom_components.solar_surplus.base_load import (
    added_power,
    house_load,
    per_hour,
    profile,
    runs,
)
from custom_components.solar_surplus.const import AdapterType

from .house import spec

HOUR = timedelta(hours=1)
DAY = timedelta(days=1)
T0 = datetime(2026, 6, 10, tzinfo=UTC)


def test_the_house_draws_solar_and_grid_less_export_and_charging() -> None:
    changes = {
        "solar": {T0: 3000, T0 + HOUR: 0},
        "import": {T0: 0, T0 + HOUR: 500},
        "export": {T0: 2000, T0 + HOUR: 0},
        "discharge": {T0: 0, T0 + HOUR: 300},
        "charge": {T0: 600, T0 + HOUR: 0},
    }
    house = house_load(changes, ["solar", "import", "discharge"], ["export", "charge"])
    assert house == {T0: 400, T0 + HOUR: 800}


def test_an_hour_a_statistic_misses_is_left_out() -> None:
    changes = {"solar": {T0: 1000, T0 + HOUR: 1000}, "import": {T0: 0}}
    assert house_load(changes, ["solar", "import"], []) == {T0: 1000}


def test_a_run_counts_while_its_state_adds_power() -> None:
    states = [(T0, "off"), (T0 + HOUR / 2, "on"), (T0 + 2 * HOUR, "off")]
    assert runs(states, T0 + 3 * HOUR, {"on": 1000}) == [
        (T0 + HOUR / 2, T0 + 2 * HOUR, 1000)
    ]


def test_a_run_does_not_count_while_nothing_was_switched() -> None:
    states = [(T0, "on")]
    off = [(T0 + HOUR, T0 + 2 * HOUR)]
    assert runs(states, T0 + 3 * HOUR, {"on": 1000}, off) == [
        (T0, T0 + HOUR, 1000),
        (T0 + 2 * HOUR, T0 + 3 * HOUR, 1000),
    ]


def test_runs_are_split_into_hours() -> None:
    energy = per_hour([(T0 + HOUR / 2, T0 + 2 * HOUR, 1000)])
    assert energy == {T0: 500, T0 + HOUR: 1000}


def test_each_hour_of_the_day_gets_its_median() -> None:
    house = {T0 + day * DAY: load for day, load in enumerate((300, 400, 2000))}
    house |= {T0 + HOUR + day * DAY: 500 for day in range(3)}
    assert profile(house, {}, UTC).hours == {0: 400, 1: 500}


def test_what_was_switched_is_taken_off() -> None:
    house = {T0 + day * DAY: 1500 for day in range(3)}
    switched = {T0: 1000, T0 + DAY: 1000, T0 + 2 * DAY: 2000}
    assert profile(house, switched, UTC).hours == {0: 500}, "and not below zero"


def test_an_hour_needs_three_days() -> None:
    house = {T0: 400, T0 + DAY: 400}
    base_load = profile(house, {}, UTC)
    assert base_load.hours == {}
    assert not base_load.learned


def test_the_hours_are_local() -> None:
    house = {T0 + day * DAY: 400 for day in range(3)}
    berlin = ZoneInfo("Europe/Berlin")
    assert profile(house, {}, berlin).hours == {2: 400}, "midnight UTC is 2:00 there"


def test_a_signal_adds_its_power_and_more_when_forced() -> None:
    signal = spec("wgt", 600, AdapterType.SIGNAL, forced_power=1500)
    assert added_power(signal, True) == {"recommended": 600, "forced": 2100}


def test_a_switched_consumer_adds_its_power_while_on() -> None:
    assert added_power(spec("rod", 2000), False) == {"on": 2000, "running": 2000}
