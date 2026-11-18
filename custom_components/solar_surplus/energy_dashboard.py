"""What the energy dashboard already knows about the house.

Its preferences name the meters: the power of the grid and the battery, the
battery's charge and capacity, the forecast of the solar panels, and the
energy statistics the base load is learned from. What the hub leaves empty is
taken from there, so a house set up for the energy dashboard needs next to
nothing more.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from homeassistant.core import HomeAssistant

from .const import (
    CONF_BATTERY_CAPACITY,
    CONF_BATTERY_DISCHARGE_POSITIVE,
    CONF_BATTERY_POWER,
    CONF_BATTERY_SOC,
    CONF_FORECAST_ENTRIES,
    CONF_GRID_EXPORT_POSITIVE,
    CONF_GRID_POWER,
)


async def async_preferences(hass: HomeAssistant) -> dict[str, Any]:
    """The energy dashboard's preferences, empty without it."""
    if "energy" not in hass.config.components:
        return {}
    from homeassistant.components.energy.data import (  # noqa: PLC0415
        async_get_manager,
    )

    manager = await async_get_manager(hass)
    return dict(manager.data or {})


def _sources(prefs: Mapping[str, Any], kind: str) -> list[dict[str, Any]]:
    return [s for s in prefs.get("energy_sources", []) if s.get("type") == kind]


def hub_values(prefs: Mapping[str, Any]) -> dict[str, Any]:
    """The hub's inputs as the energy dashboard has them.

    Its power sensors count the energy dashboard's way: positive when drawing
    from the grid and when the battery discharges. A meter is only taken when
    there is one of its kind; several would have to be added up.
    """
    values: dict[str, Any] = {}
    grids = [rate for s in _sources(prefs, "grid") if (rate := _grid_rate(s))]
    if len(grids) == 1:
        values[CONF_GRID_POWER] = grids[0]
        values[CONF_GRID_EXPORT_POSITIVE] = False
    batteries = _sources(prefs, "battery")
    if len(batteries) == 1:
        battery = batteries[0]
        if battery.get("stat_rate"):
            values[CONF_BATTERY_POWER] = battery["stat_rate"]
            values[CONF_BATTERY_DISCHARGE_POSITIVE] = True
        if battery.get("stat_soc"):
            values[CONF_BATTERY_SOC] = battery["stat_soc"]
        if battery.get("capacity"):
            values[CONF_BATTERY_CAPACITY] = battery["capacity"]
    forecasts = [
        entry_id
        for source in _sources(prefs, "solar")
        for entry_id in source.get("config_entry_solar_forecast") or []
    ]
    if forecasts:
        values[CONF_FORECAST_ENTRIES] = list(dict.fromkeys(forecasts))
    return values


def _grid_rate(source: Mapping[str, Any]) -> str | None:
    if source.get("stat_rate"):
        return source["stat_rate"]
    # Older preferences give a grid a list of power meters.
    rates = [p["stat_rate"] for p in source.get("power", []) if p.get("stat_rate")]
    return rates[0] if len(rates) == 1 else None


#: What a meter taken from the energy dashboard brings along with it.
_WITH = {
    CONF_GRID_POWER: (CONF_GRID_EXPORT_POSITIVE,),
    CONF_BATTERY_POWER: (CONF_BATTERY_DISCHARGE_POSITIVE,),
    CONF_BATTERY_SOC: (),
    CONF_BATTERY_CAPACITY: (),
    CONF_FORECAST_ENTRIES: (),
}


def merge(values: Mapping[str, Any], dashboard: Mapping[str, Any]) -> dict[str, Any]:
    """The hub's values, with what they leave empty from the energy dashboard."""
    merged = dict(values)
    for key, along in _WITH.items():
        if merged.get(key) or not dashboard.get(key):
            continue
        merged[key] = dashboard[key]
        for other in along:
            merged[other] = dashboard[other]
    return merged


def energy_statistics(prefs: Mapping[str, Any]) -> tuple[list[str], list[str]] | None:
    """The statistics the house's draw is made of: added, and taken off.

    None without a grid and a solar source.
    """
    added: list[str] = []
    taken: list[str] = []
    grids = _sources(prefs, "grid")
    solars = _sources(prefs, "solar")
    if not (grids and solars):
        return None
    added += [s["stat_energy_from"] for s in solars]
    for battery in _sources(prefs, "battery"):
        added.append(battery["stat_energy_from"])
        taken.append(battery["stat_energy_to"])
    for grid in grids:
        imports = [grid.get("stat_energy_from")]
        exports = [grid.get("stat_energy_to")]
        # Older preferences give a grid lists of meters.
        imports += [f.get("stat_energy_from") for f in grid.get("flow_from", [])]
        exports += [f.get("stat_energy_to") for f in grid.get("flow_to", [])]
        added += [s for s in imports if s]
        taken += [s for s in exports if s]
    return added, taken
