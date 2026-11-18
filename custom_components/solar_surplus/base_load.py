"""The base load, learned from what the house drew in the past.

The energy dashboard's statistics say what the house drew in each hour: solar,
plus what came from the grid and the battery, less what went to them. Less
again what Solar Surplus switched on, as its status and signal sensors recall
it, that is what the house draws on its own. For each hour of the day, the
median of the days the recorder still has is what the plan expects.

What Solar Surplus switched counts only for the power it added: a heat pump's
own running stays part of the base load, as the plan does not book it either.
While in test mode, or with the control off, nothing was switched, so nothing
is taken off.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, tzinfo
from statistics import median
from typing import Any

from homeassistant.components.recorder import get_instance, history, statistics
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from .const import DOMAIN, AdapterType, ConsumerState, EnergySignal
from .models import ConsumerSpec

_LOGGER = logging.getLogger(__name__)

HOUR = timedelta(hours=1)
#: How far back the history goes, at most. The recorder keeps ten days by
#: default; what it has, up to this, is used.
HISTORY = timedelta(days=14)
#: An hour of the day needs this many days before its median counts.
MIN_DAYS = 3

#: A run: from, until, and the power it added.
Run = tuple[datetime, datetime, float]


@dataclass(frozen=True, slots=True)
class BaseLoad:
    """The expected base load for each hour of the day, where it is known."""

    hours: dict[int, float] = field(default_factory=dict)

    @property
    def learned(self) -> bool:
        return bool(self.hours)


################################################################################
# Pure
################################################################################


def house_load(
    changes: dict[str, dict[datetime, float]],
    added: Iterable[str],
    taken: Iterable[str],
) -> dict[datetime, float]:
    """What the house drew in each hour, in Wh, from the statistics' changes.

    An hour counts only when every statistic has it.
    """
    added, taken = list(added), list(taken)
    hours: set[datetime] | None = None
    for statistic_id in (*added, *taken):
        known = set(changes.get(statistic_id, {}))
        hours = known if hours is None else hours & known
    return {
        hour: sum(changes[s][hour] for s in added)
        - sum(changes[s][hour] for s in taken)
        for hour in sorted(hours or ())
    }


def runs(
    states: list[tuple[datetime, str]],
    end: datetime,
    power: dict[str, float],
    off: list[tuple[datetime, datetime]] = (),
) -> list[Run]:
    """The stretches a sensor was in a state that adds `power[state]`,
    outside the stretches in `off`."""
    found: list[Run] = []
    for index, (start, state) in enumerate(states):
        watts = power.get(state)
        if not watts:
            continue
        until = states[index + 1][0] if index + 1 < len(states) else end
        found.extend((a, b, watts) for a, b in _without(start, until, off))
    return found


def _without(
    start: datetime, end: datetime, off: list[tuple[datetime, datetime]]
) -> list[tuple[datetime, datetime]]:
    parts = [(start, end)]
    for off_start, off_end in off:
        parts = [
            piece
            for a, b in parts
            for piece in ((a, min(b, off_start)), (max(a, off_end), b))
            if piece[1] > piece[0]
        ]
    return parts


def per_hour(found: Iterable[Run]) -> dict[datetime, float]:
    """The energy of runs in each hour, in Wh, by hour start."""
    energy: dict[datetime, float] = {}
    for start, end, watts in found:
        hour = start.replace(minute=0, second=0, microsecond=0)
        while hour < end:
            overlap = min(end, hour + HOUR) - max(start, hour)
            if overlap > timedelta(0):
                energy[hour] = energy.get(hour, 0.0) + watts * (overlap / HOUR)
            hour += HOUR
    return energy


def profile(
    house: dict[datetime, float], switched: dict[datetime, float], zone: tzinfo
) -> BaseLoad:
    """The median base load of each hour of the day, in W."""
    by_hour: dict[int, list[float]] = {}
    for hour, energy in house.items():
        load = max(energy - switched.get(hour, 0.0), 0.0)
        by_hour.setdefault(hour.astimezone(zone).hour, []).append(load)
    return BaseLoad(
        {
            hour: round(median(values))
            for hour, values in sorted(by_hour.items())
            if len(values) >= MIN_DAYS
        }
    )


def added_power(spec: ConsumerSpec, signal: bool) -> dict[str, float]:
    """What a consumer adds in each state of its status or signal sensor."""
    if signal:
        return {
            EnergySignal.RECOMMENDED.value: spec.power,
            EnergySignal.FORCED.value: spec.power + (spec.forced_power or 0),
        }
    return {ConsumerState.ON.value: spec.power, ConsumerState.RUNNING.value: spec.power}


################################################################################
# Home Assistant
################################################################################


@dataclass(frozen=True, slots=True)
class Tracked:
    """A consumer as the history knows it."""

    spec: ConsumerSpec
    power_sensor: str | None = None


class BaseLoadReader:
    """Learns the base load, once an hour."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._hass = hass
        self._entry_id = entry_id
        self._base_load = BaseLoad()
        self._hour: datetime | None = None

    async def async_get(self, now: datetime, consumers: dict[str, Tracked]) -> BaseLoad:
        """The base load, learned again in each new hour."""
        hour = now.replace(minute=0, second=0, microsecond=0)
        if hour == self._hour:
            return self._base_load
        self._hour = hour
        try:
            self._base_load = await self._async_learn(hour, consumers)
        except Exception:  # noqa: BLE001 - the setting is there to fall back on
            _LOGGER.exception("Learning the base load failed")
            self._base_load = BaseLoad()
        return self._base_load

    async def _async_learn(
        self, end: datetime, consumers: dict[str, Tracked]
    ) -> BaseLoad:
        if "recorder" not in self._hass.config.components:
            return BaseLoad()
        sources = await _async_sources(self._hass)
        if sources is None:
            return BaseLoad()
        added, taken = sources
        start = end - HISTORY
        recorder = get_instance(self._hass)
        sensors = {c.power_sensor for c in consumers.values() if c.power_sensor}
        rows = await recorder.async_add_executor_job(
            statistics.statistics_during_period,
            self._hass,
            start,
            end,
            {*added, *taken, *sensors},
            "hour",
            {"energy": "Wh", "power": "W"},
            {"change", "mean"},
        )
        changes = {key: _column(value, "change") for key, value in rows.items()}
        house = house_load(changes, added, taken)
        if not house:
            return BaseLoad()

        entities = self._entities(consumers)
        wanted = [e for e in entities.values() if e] + [
            e for e in self._switches() if e
        ]
        states = await recorder.async_add_executor_job(
            lambda: history.get_significant_states(
                self._hass,
                start,
                end,
                wanted,
                significant_changes_only=False,
                no_attributes=True,
            )
        )
        timeline = {
            entity: [(s.last_changed, s.state) for s in values]
            for entity, values in states.items()
        }
        off = self._not_switching(timeline, start, end)
        switched: dict[datetime, float] = {}
        for consumer_id, tracked in consumers.items():
            entity = entities.get(consumer_id)
            if entity is None:
                continue
            signal = tracked.spec.adapter is AdapterType.SIGNAL
            found = runs(
                timeline.get(entity, []),
                end,
                added_power(tracked.spec, signal),
                # A signal is published whatever the mode: it was followed.
                () if signal else off,
            )
            energy = per_hour(found)
            measured = _column(rows.get(tracked.power_sensor or "", []), "mean")
            for hour, value in energy.items():
                # Measured, the hour's whole draw was the consumer's doing.
                value = measured.get(hour, value) if measured else value
                switched[hour] = switched.get(hour, 0.0) + value
        return profile(house, switched, dt_util.get_default_time_zone())

    def _entities(self, consumers: dict[str, Tracked]) -> dict[str, str | None]:
        registry = er.async_get(self._hass)
        return {
            consumer_id: registry.async_get_entity_id(
                "sensor",
                DOMAIN,
                f"{consumer_id}_energy_signal"
                if tracked.spec.adapter is AdapterType.SIGNAL
                else f"{consumer_id}_status",
            )
            for consumer_id, tracked in consumers.items()
        }

    def _switches(self) -> tuple[str | None, str | None]:
        registry = er.async_get(self._hass)
        return (
            registry.async_get_entity_id("switch", DOMAIN, f"{self._entry_id}_control"),
            registry.async_get_entity_id(
                "switch", DOMAIN, f"{self._entry_id}_test_mode"
            ),
        )

    def _not_switching(
        self,
        timeline: dict[str, list[tuple[datetime, str]]],
        start: datetime,
        end: datetime,
    ) -> list[tuple[datetime, datetime]]:
        """When nothing was switched: in test mode, or with the control off."""
        control, test_mode = self._switches()
        stretches = [
            (a, b)
            for a, b, _ in runs(timeline.get(test_mode or "", []), end, {"on": 1})
        ]
        stretches += [
            (a, b) for a, b, _ in runs(timeline.get(control or "", []), end, {"off": 1})
        ]
        return [(max(a, start), b) for a, b in stretches]


async def _async_sources(hass: HomeAssistant) -> tuple[list[str], list[str]] | None:
    """The statistics the house's draw is made of: added, and taken off.

    None without a grid and a solar source in the energy dashboard.
    """
    if "energy" not in hass.config.components:
        return None
    from homeassistant.components.energy.data import (  # noqa: PLC0415
        async_get_manager,
    )

    manager = await async_get_manager(hass)
    prefs: dict[str, Any] = manager.data or {}
    added: list[str] = []
    taken: list[str] = []
    grid = solar = False
    for source in prefs.get("energy_sources", []):
        kind = source.get("type")
        if kind == "solar":
            solar = True
            added.append(source["stat_energy_from"])
        elif kind == "battery":
            added.append(source["stat_energy_from"])
            taken.append(source["stat_energy_to"])
        elif kind == "grid":
            grid = True
            imports = [source.get("stat_energy_from")]
            exports = [source.get("stat_energy_to")]
            # Older preferences give a grid lists of meters.
            imports += [f.get("stat_energy_from") for f in source.get("flow_from", [])]
            exports += [f.get("stat_energy_to") for f in source.get("flow_to", [])]
            added += [s for s in imports if s]
            taken += [s for s in exports if s]
    if not (grid and solar):
        return None
    return added, taken


def _column(rows: list[dict[str, Any]], key: str) -> dict[datetime, float]:
    return {
        dt_util.utc_from_timestamp(row["start"]): row[key]
        for row in rows
        if row.get(key) is not None
    }
