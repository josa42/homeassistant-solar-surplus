"""The coordinator: reads the house, runs the engine, writes what it decided."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .adapters import Adapter, as_float, as_watts, build_adapter, build_spec
from .const import (
    CONF_BASE_LOAD,
    CONF_BATTERY_DISCHARGE_POSITIVE,
    CONF_BATTERY_MAX_CHARGE,
    CONF_BATTERY_MIN_SOC,
    CONF_BATTERY_POWER,
    CONF_BATTERY_SOC,
    CONF_BATTERY_TARGET_SOC,
    CONF_FORECAST_ENTRIES,
    CONF_GRID_EXPORT_POSITIVE,
    CONF_GRID_POWER,
    CONF_RESERVE,
    CONF_SIGNAL_BLOCKED,
    CONF_SIGNAL_FALL_DELAY,
    CONF_SIGNAL_FOLLOWERS,
    CONF_SIGNAL_FORCED,
    CONF_SIGNAL_FORCED_SOC,
    CONF_SIGNAL_MIN_DWELL,
    CONF_SIGNAL_RECOMMENDED,
    CONF_SIGNAL_RISE_DELAY,
    DEFAULT_BASE_LOAD,
    DEFAULT_BATTERY_MIN_SOC,
    DEFAULT_BATTERY_TARGET_SOC,
    DEFAULT_RESERVE,
    DEFAULT_SIGNAL_BLOCKED,
    DEFAULT_SIGNAL_FALL_DELAY,
    DEFAULT_SIGNAL_FORCED,
    DEFAULT_SIGNAL_FORCED_SOC,
    DEFAULT_SIGNAL_MIN_DWELL,
    DEFAULT_SIGNAL_RECOMMENDED,
    DEFAULT_SIGNAL_RISE_DELAY,
    DOMAIN,
    REFRESH_COOLDOWN,
    SUBENTRY_TYPE_CONSUMER,
    TICK_INTERVAL,
)
from .engine import decide
from .forecast import ForecastReader
from .models import (
    ConsumerInput,
    ConsumerMemory,
    ConsumerReading,
    ConsumerSpec,
    Decision,
    EngineMemory,
    HubSettings,
    Inputs,
)
from .store import SolarSurplusStore

_LOGGER = logging.getLogger(__name__)

type SolarSurplusConfigEntry = ConfigEntry[SolarSurplusCoordinator]

#: Sent after every run, for the panel's subscriptions.
SIGNAL_UPDATE = f"{DOMAIN}_update"


@dataclass(slots=True)
class Consumer:
    """One configured consumer: what the engine needs and how to reach it."""

    id: str
    title: str
    spec: ConsumerSpec
    adapter: Adapter


def hub_settings(values: Mapping[str, Any]) -> HubSettings:
    """The engine's settings from the entry's data and options."""
    max_charge = values.get(CONF_BATTERY_MAX_CHARGE)
    return HubSettings(
        battery_target_soc=float(
            values.get(CONF_BATTERY_TARGET_SOC, DEFAULT_BATTERY_TARGET_SOC)
        ),
        battery_min_soc=float(
            values.get(CONF_BATTERY_MIN_SOC, DEFAULT_BATTERY_MIN_SOC)
        ),
        battery_max_charge=float(max_charge) if max_charge else None,
        reserve=float(values.get(CONF_RESERVE, DEFAULT_RESERVE)),
        base_load=float(values.get(CONF_BASE_LOAD, DEFAULT_BASE_LOAD)),
        signal_recommended=float(
            values.get(CONF_SIGNAL_RECOMMENDED, DEFAULT_SIGNAL_RECOMMENDED)
        ),
        signal_forced=float(values.get(CONF_SIGNAL_FORCED, DEFAULT_SIGNAL_FORCED)),
        signal_forced_soc=float(
            values.get(CONF_SIGNAL_FORCED_SOC, DEFAULT_SIGNAL_FORCED_SOC)
        ),
        signal_blocked=float(values.get(CONF_SIGNAL_BLOCKED, DEFAULT_SIGNAL_BLOCKED)),
        signal_rise_delay=timedelta(
            seconds=values.get(CONF_SIGNAL_RISE_DELAY, DEFAULT_SIGNAL_RISE_DELAY)
        ),
        signal_fall_delay=timedelta(
            seconds=values.get(CONF_SIGNAL_FALL_DELAY, DEFAULT_SIGNAL_FALL_DELAY)
        ),
        signal_min_dwell=timedelta(
            minutes=values.get(CONF_SIGNAL_MIN_DWELL, DEFAULT_SIGNAL_MIN_DWELL)
        ),
    )


class SolarSurplusCoordinator(DataUpdateCoordinator[Decision]):
    """Runs the allocation every tick and whenever an input changes."""

    config_entry: SolarSurplusConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: SolarSurplusConfigEntry,
        store: SolarSurplusStore,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=TICK_INTERVAL,
            request_refresh_debouncer=Debouncer(
                hass, _LOGGER, cooldown=REFRESH_COOLDOWN, immediate=False
            ),
            always_update=True,
        )
        self.entry = entry
        self.store = store
        self.values: dict[str, Any] = {**entry.data, **entry.options}
        self.settings = hub_settings(self.values)
        self.forecast = ForecastReader(hass, self.values.get(CONF_FORECAST_ENTRIES, []))
        self.consumers: dict[str, Consumer] = {}
        for subentry_id, subentry in entry.subentries.items():
            if subentry.subentry_type != SUBENTRY_TYPE_CONSUMER:
                continue
            spec = build_spec(subentry_id, subentry.data)
            self.consumers[subentry_id] = Consumer(
                id=subentry_id,
                title=subentry.title,
                spec=spec,
                adapter=build_adapter(hass, spec, subentry.data),
            )
        self.memory = EngineMemory(
            consumers={
                consumer_id: ConsumerMemory.from_dict(store.memories.get(consumer_id))
                for consumer_id in self.consumers
            }
        )
        #: Off, everything is still decided and shown, but nothing is written.
        self.control_enabled = True
        #: The first run only reads: nothing is known yet about how long
        #: anything has been in its state.
        self._first_run = True
        self._unsubscribe: list = []
        self.hub_device_id: str | None = None

    @callback
    def async_register_hub_device(self) -> str:
        """Make the hub's device, so the consumers' devices can hang off it."""
        device = dr.async_get(self.hass).async_get_or_create(
            config_entry_id=self.entry.entry_id,
            identifiers={(DOMAIN, self.entry.entry_id)},
            name=self.entry.title,
            manufacturer="Solar Surplus",
            model="Hub",
            entry_type=dr.DeviceEntryType.SERVICE,
        )
        self.hub_device_id = device.id
        return device.id

    ############################################################################
    # Watching
    ############################################################################

    @property
    def watched_entities(self) -> list[str]:
        """Every entity whose change triggers a run."""
        hub = [
            self.values.get(CONF_GRID_POWER),
            self.values.get(CONF_BATTERY_POWER),
            self.values.get(CONF_BATTERY_SOC),
        ]
        consumers = [
            entity
            for consumer in self.consumers.values()
            for entity in consumer.adapter.entities
        ]
        return sorted({entity for entity in (*hub, *consumers) if entity})

    @callback
    def async_start_watching(self) -> None:
        """Run whenever an input changes, and when the order or a hand changes."""

        @callback
        def _on_change(event: Event[EventStateChangedData]) -> None:
            self.hass.async_create_task(self.async_request_refresh(), eager_start=True)

        self._unsubscribe.append(
            async_track_state_change_event(self.hass, self.watched_entities, _on_change)
        )
        self._unsubscribe.append(
            self.store.async_add_listener(lambda: _on_change(None))
        )
        self._unsubscribe.append(
            self.async_add_listener(
                lambda: async_dispatcher_send(self.hass, SIGNAL_UPDATE)
            )
        )

    async def async_shutdown(self) -> None:
        for unsubscribe in self._unsubscribe:
            unsubscribe()
        self._unsubscribe.clear()
        self._sync_memories()
        await self.store.async_save()
        await super().async_shutdown()

    @callback
    def async_set_control(self, enabled: bool) -> None:
        """Let the allocation write, or only show what it would do."""
        if self.control_enabled == enabled:
            return
        self.control_enabled = enabled
        self.hass.async_create_task(self.async_request_refresh(), eager_start=True)

    async def async_set_control_now(self, enabled: bool) -> None:
        """Like `async_set_control`, but run at once."""
        self.control_enabled = enabled
        await self.async_refresh()

    ############################################################################
    # Running
    ############################################################################

    def _state(self, key: str):
        entity_id = self.values.get(key)
        return self.hass.states.get(entity_id) if entity_id else None

    def _inputs(self, now, forecast) -> Inputs:
        grid = as_watts(self._state(CONF_GRID_POWER))
        if grid is not None and self.values.get(CONF_GRID_EXPORT_POSITIVE):
            grid = -grid
        battery = as_watts(self._state(CONF_BATTERY_POWER))
        if battery is not None and self.values.get(CONF_BATTERY_DISCHARGE_POSITIVE):
            battery = -battery
        followers = sum(
            max(value, 0.0)
            for entity_id in self.values.get(CONF_SIGNAL_FOLLOWERS, [])
            if (value := as_watts(self.hass.states.get(entity_id))) is not None
        )
        return Inputs(
            now=now,
            grid=grid,
            battery=battery,
            soc=as_float(self._state(CONF_BATTERY_SOC)),
            followers=followers,
            forecast=forecast,
            control_enabled=self.control_enabled and not self._first_run,
            settings=self.settings,
        )

    async def _async_update_data(self) -> Decision:
        now = dt_util.now()
        forecast = await self.forecast.async_get(now)
        inputs = self._inputs(now, forecast)
        readings: dict[str, ConsumerReading] = {
            consumer_id: consumer.adapter.read(self.memory.consumer(consumer_id), now)
            for consumer_id, consumer in self.consumers.items()
        }
        consumers = [
            ConsumerInput(
                spec=consumer.spec,
                reading=readings[consumer_id],
                override=self.store.override(consumer_id),
            )
            for consumer_id, consumer in self.consumers.items()
        ]
        previous = self.data
        decision = decide(inputs, consumers, self.store.order, self.memory)

        if inputs.control_enabled:
            for item in decision.consumers:
                consumer = self.consumers[item.id]
                try:
                    await consumer.adapter.async_apply(
                        item, readings[item.id], self.memory.consumer(item.id)
                    )
                except Exception:
                    _LOGGER.exception("Switching %s failed", consumer.title)
        self._first_run = False
        self._log_changes(previous, decision)
        self._sync_memories()
        return decision

    def _sync_memories(self) -> None:
        self.store.async_set_memories(
            {
                consumer_id: self.memory.consumer(consumer_id).to_dict()
                for consumer_id in self.consumers
            }
        )

    def _log_changes(self, previous: Decision | None, decision: Decision) -> None:
        """Log each consumer whose state or reason changed, and the signal."""
        for item in decision.consumers:
            before = previous.consumer(item.id) if previous else None
            if before is None or (before.state, before.reason) != (
                item.state,
                item.reason,
            ):
                _LOGGER.debug(
                    "%s: %s (%s), surplus %s W, %s",
                    item.name,
                    item.state,
                    item.reason,
                    None if decision.surplus is None else round(decision.surplus),
                    item.details,
                )
        if previous is None or previous.signal.state != decision.signal.state:
            _LOGGER.debug(
                "Energy signal: %s (%s)", decision.signal.state, decision.signal.reason
            )
