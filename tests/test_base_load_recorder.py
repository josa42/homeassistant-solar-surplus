"""The base load, learned from a recorder with the energy dashboard's history."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from homeassistant.components.energy.data import async_get_manager
from homeassistant.components.recorder.models import StatisticMeanType
from homeassistant.components.recorder.statistics import async_import_statistics
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
)

from custom_components.solar_surplus.base_load import BaseLoadReader, Tracked
from custom_components.solar_surplus.const import DOMAIN

from .house import spec

HOUR = timedelta(hours=1)
DAY = timedelta(days=1)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(recorder_mock, enable_custom_integrations):
    """The recorder has to be there before Home Assistant starts."""
    return


def _import(hass, statistic_id: str, hours: dict[datetime, float]) -> None:
    """Hourly energy statistics, in kWh per hour."""
    total = 0.0
    rows = []
    for start in sorted(hours):
        total += hours[start]
        rows.append({"start": start, "state": total, "sum": total})
    async_import_statistics(
        hass,
        {
            "mean_type": StatisticMeanType.NONE,
            "has_sum": True,
            "name": None,
            "source": "recorder",
            "statistic_id": statistic_id,
            "unit_class": "energy",
            "unit_of_measurement": "kWh",
        },
        rows,
    )


async def _house(hass: HomeAssistant, test_mode: bool = False) -> dict[int, float]:
    """Three days of a house drawing 1500 W, with a 1000 W rod on for an hour
    each day, and what is learned from them."""
    await async_setup_component(hass, "energy", {})
    manager = await async_get_manager(hass)
    await manager.async_update(
        {
            "energy_sources": [
                {"type": "solar", "stat_energy_from": "sensor.solar"},
                {
                    "type": "grid",
                    "stat_energy_from": "sensor.grid_import",
                    "stat_energy_to": "sensor.grid_export",
                    "stat_cost": None,
                    "stat_compensation": None,
                    "entity_energy_price": None,
                    "number_energy_price": None,
                    "entity_energy_price_export": None,
                    "number_energy_price_export": None,
                    "cost_adjustment_day": 0,
                },
            ]
        }
    )
    registry = er.async_get(hass)
    status = registry.async_get_or_create(
        "sensor", DOMAIN, "rod_status", suggested_object_id="rod_status"
    )
    switch = registry.async_get_or_create(
        "switch", DOMAIN, "entry_test_mode", suggested_object_id="test_mode"
    )

    now = dt_util.now()
    hour = now.replace(minute=0, second=0, microsecond=0)
    # Three days back, two hours each, and the hour before them as a start.
    starts = [
        hour - day * DAY - offset * HOUR for day in (1, 2, 3) for offset in (2, 1)
    ]
    first = min(starts) - HOUR
    _import(hass, "sensor.solar", {first: 0} | dict.fromkeys(starts, 3.0))
    _import(hass, "sensor.grid_import", {first: 0} | dict.fromkeys(starts, 0.5))
    _import(hass, "sensor.grid_export", {first: 0} | dict.fromkeys(starts, 2.0))
    hass.states.async_set(
        switch.entity_id, "on" if test_mode else "off", timestamp=first.timestamp()
    )
    # The rod is on through the second of the hours every day.
    hass.states.async_set(status.entity_id, "off", timestamp=first.timestamp())
    for day in (1, 2, 3):
        on = hour - day * DAY - HOUR
        hass.states.async_set(status.entity_id, "on", timestamp=on.timestamp())
        hass.states.async_set(
            status.entity_id, "off", timestamp=(on + HOUR).timestamp()
        )
    await async_wait_recording_done(hass)

    reader = BaseLoadReader(hass, "entry")
    base_load = await reader.async_get(now, {"rod": Tracked(spec=spec("rod", 1000))})
    local = (hour - 2 * HOUR).astimezone(dt_util.get_default_time_zone()).hour
    # By hour after the first of the two.
    return {(h - local) % 24: value for h, value in base_load.hours.items()}


async def test_the_base_load_is_learned_from_the_energy_dashboard(
    hass: HomeAssistant,
) -> None:
    assert await _house(hass) == {0: 1500, 1: 500}, "less the rod while it was on"


async def test_in_test_mode_nothing_was_switched(hass: HomeAssistant) -> None:
    assert await _house(hass, test_mode=True) == {0: 1500, 1: 1500}


async def test_without_a_solar_source_nothing_is_learned(hass: HomeAssistant) -> None:
    await async_setup_component(hass, "energy", {})
    reader = BaseLoadReader(hass, "entry")
    assert not (await reader.async_get(dt_util.now(), {})).learned
