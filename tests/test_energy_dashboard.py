"""What is taken from the energy dashboard."""

from __future__ import annotations

from custom_components.solar_surplus.const import (
    CONF_BATTERY_CAPACITY,
    CONF_BATTERY_DISCHARGE_POSITIVE,
    CONF_BATTERY_POWER,
    CONF_BATTERY_SOC,
    CONF_FORECAST_ENTRIES,
    CONF_GRID_EXPORT_POSITIVE,
    CONF_GRID_POWER,
)
from custom_components.solar_surplus.energy_dashboard import (
    energy_statistics,
    hub_values,
    merge,
)

GRID = {
    "type": "grid",
    "stat_energy_from": "sensor.import",
    "stat_energy_to": "sensor.export",
    "stat_rate": "sensor.grid_power",
}
SOLAR = {
    "type": "solar",
    "stat_energy_from": "sensor.solar",
    "config_entry_solar_forecast": ["forecast"],
}
BATTERY = {
    "type": "battery",
    "stat_energy_from": "sensor.discharge",
    "stat_energy_to": "sensor.charge",
    "stat_rate": "sensor.battery_power",
    "stat_soc": "sensor.battery_soc",
    "capacity": 10,
}
PREFS = {"energy_sources": [GRID, SOLAR, BATTERY]}


def test_the_meters_are_taken_with_the_dashboards_signs() -> None:
    assert hub_values(PREFS) == {
        CONF_GRID_POWER: "sensor.grid_power",
        CONF_GRID_EXPORT_POSITIVE: False,
        CONF_BATTERY_POWER: "sensor.battery_power",
        CONF_BATTERY_DISCHARGE_POSITIVE: True,
        CONF_BATTERY_SOC: "sensor.battery_soc",
        CONF_BATTERY_CAPACITY: 10,
        CONF_FORECAST_ENTRIES: ["forecast"],
    }


def test_an_older_grid_has_a_list_of_power_meters() -> None:
    grid = {"type": "grid", "power": [{"stat_rate": "sensor.grid_power"}]}
    assert hub_values({"energy_sources": [grid]})[CONF_GRID_POWER] == (
        "sensor.grid_power"
    )


def test_two_grids_or_batteries_would_have_to_be_added_up() -> None:
    other = {**BATTERY, "stat_rate": "sensor.other"}
    values = hub_values({"energy_sources": [GRID, GRID, BATTERY, other]})
    assert values == {}


def test_without_a_dashboard_there_is_nothing() -> None:
    assert hub_values({}) == {}
    assert energy_statistics({}) is None


def test_what_the_hub_has_wins_with_its_own_sign() -> None:
    values = {CONF_GRID_POWER: "sensor.mine", CONF_GRID_EXPORT_POSITIVE: True}
    merged = merge(values, hub_values(PREFS))
    assert merged[CONF_GRID_POWER] == "sensor.mine"
    assert merged[CONF_GRID_EXPORT_POSITIVE] is True
    assert merged[CONF_BATTERY_POWER] == "sensor.battery_power"


def test_what_the_hub_leaves_empty_comes_with_the_dashboards_sign() -> None:
    values = {CONF_BATTERY_DISCHARGE_POSITIVE: False, CONF_FORECAST_ENTRIES: []}
    merged = merge(values, hub_values(PREFS))
    assert merged[CONF_BATTERY_DISCHARGE_POSITIVE] is True
    assert merged[CONF_FORECAST_ENTRIES] == ["forecast"]


def test_the_house_is_made_of_solar_grid_and_battery() -> None:
    assert energy_statistics(PREFS) == (
        ["sensor.solar", "sensor.discharge", "sensor.import"],
        ["sensor.charge", "sensor.export"],
    )


def test_without_solar_the_house_is_not_known() -> None:
    assert energy_statistics({"energy_sources": [GRID]}) is None
