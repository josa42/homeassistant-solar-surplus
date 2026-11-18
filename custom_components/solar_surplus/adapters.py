"""How a consumer is read and switched, one adapter per kind.

An adapter turns the consumer's entities into a `ConsumerReading` for the
engine, and the engine's decision back into service calls. It only calls a
service when the entity is not already where the decision wants it.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Mapping
from datetime import datetime, time, timedelta
from typing import Any

from homeassistant.const import STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant, State
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util

from .const import (
    CONF_ADAPTER,
    CONF_DEADLINE_ENTITY,
    CONF_DEADLINE_TIME,
    CONF_FINISH_DELAY,
    CONF_FINISH_POWER,
    CONF_MIN_OFF_TIME,
    CONF_MIN_ON_TIME,
    CONF_MIN_POWER,
    CONF_NAME,
    CONF_NUMBER_ENTITY,
    CONF_OFF_DELAY,
    CONF_OFF_ENTITY,
    CONF_ON_DELAY,
    CONF_ON_ENTITY,
    CONF_POWER,
    CONF_POWER_SENSOR,
    CONF_POWER_STEP,
    CONF_READY_ENTITY,
    CONF_RUN_TIME,
    CONF_SG_CONTACT_1,
    CONF_SG_CONTACT_2,
    CONF_SG_FORCED_POWER,
    CONF_SG_LOCK,
    CONF_START_ENTITY,
    CONF_STATE_ENTITY,
    CONF_SWITCH_ENTITY,
    CONF_TURN_OFF_WHEN_DONE,
    CONF_WAIT_FOR_BEST,
    CONF_WATTS_PER_UNIT,
    DEFAULT_DEADLINE_TIME,
    DEFAULT_FINISH_DELAY,
    DEFAULT_FINISH_POWER,
    DEFAULT_MIN_OFF_TIME,
    DEFAULT_MIN_ON_TIME,
    DEFAULT_OFF_DELAY,
    DEFAULT_ON_DELAY,
    DEFAULT_POWER_STEP,
    DEFAULT_RUN_TIME,
    DEFAULT_WATTS_PER_UNIT,
    AdapterType,
    SgState,
)
from .engine import next_occurrence
from .models import ConsumerDecision, ConsumerMemory, ConsumerReading, ConsumerSpec

_LOGGER = logging.getLogger(__name__)

#: Domains that are turned on and off, as opposed to run or pressed.
SWITCHED_DOMAINS = {"switch", "input_boolean", "light"}

#: The SG Ready states as the two contacts set them.
SG_CONTACTS: dict[SgState, tuple[bool, bool]] = {
    SgState.LOCK: (True, False),
    SgState.NORMAL: (False, False),
    SgState.RECOMMENDED: (False, True),
    SgState.FORCED: (True, True),
}


def build_spec(consumer_id: str, data: Mapping[str, Any]) -> ConsumerSpec:
    """The engine's view of a consumer's configuration."""
    adapter = AdapterType(data[CONF_ADAPTER])
    forced = data.get(CONF_SG_FORCED_POWER)
    return ConsumerSpec(
        id=consumer_id,
        name=data[CONF_NAME],
        adapter=adapter,
        power=float(data[CONF_POWER]),
        has_power_sensor=bool(data.get(CONF_POWER_SENSOR)),
        min_on_time=timedelta(minutes=data.get(CONF_MIN_ON_TIME, DEFAULT_MIN_ON_TIME)),
        min_off_time=timedelta(
            minutes=data.get(CONF_MIN_OFF_TIME, DEFAULT_MIN_OFF_TIME)
        ),
        on_delay=timedelta(seconds=data.get(CONF_ON_DELAY, DEFAULT_ON_DELAY)),
        off_delay=timedelta(seconds=data.get(CONF_OFF_DELAY, DEFAULT_OFF_DELAY)),
        min_power=float(data.get(CONF_MIN_POWER, 0)),
        power_step=float(data.get(CONF_POWER_STEP, DEFAULT_POWER_STEP)),
        forced_power=float(forced) if forced is not None else None,
        lock=bool(data.get(CONF_SG_LOCK, False)),
        run_time=timedelta(minutes=data.get(CONF_RUN_TIME, DEFAULT_RUN_TIME)),
        wait_for_best=bool(data.get(CONF_WAIT_FOR_BEST, True)),
        finish_power=float(data.get(CONF_FINISH_POWER, DEFAULT_FINISH_POWER)),
        finish_delay=timedelta(
            minutes=data.get(CONF_FINISH_DELAY, DEFAULT_FINISH_DELAY)
        ),
    )


def build_adapter(
    hass: HomeAssistant, spec: ConsumerSpec, data: Mapping[str, Any]
) -> Adapter:
    """The adapter for a consumer's kind."""
    adapter = {
        AdapterType.SWITCH: SwitchAdapter,
        AdapterType.NUMBER: NumberAdapter,
        AdapterType.SG_READY: SgReadyAdapter,
        AdapterType.SCRIPT: ScriptAdapter,
        AdapterType.DEFERRABLE: DeferrableAdapter,
        AdapterType.SIGNAL: SignalAdapter,
    }[spec.adapter]
    return adapter(hass, spec, data)


################################################################################
# Reading states
################################################################################


def usable(state: State | None) -> bool:
    """Whether a state says anything."""
    return state is not None and state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN)


def present(state: State | None) -> bool:
    """Whether an entity exists and can be used, even if it has no state yet.

    A button that was never pressed is `unknown`, and can be pressed all the
    same.
    """
    return state is not None and state.state != STATE_UNAVAILABLE


def as_float(state: State | None) -> float | None:
    """A state's number, if it has one."""
    if not usable(state):
        return None
    try:
        return float(state.state)
    except ValueError:
        return None


def as_watts(state: State | None) -> float | None:
    """A power sensor's reading in watts, whatever unit it reports in."""
    value = as_float(state)
    if value is None:
        return None
    unit = state.attributes.get("unit_of_measurement")
    if unit == "kW":
        return value * 1000
    if unit == "MW":
        return value * 1_000_000
    return value


def is_on(state: State | None) -> bool:
    return usable(state) and state.state == STATE_ON


def resolve_deadline(
    state: State | None, default_time: str, after: datetime
) -> datetime:
    """When a run has to be done, from an entity or a time of day.

    A date and time is taken as it is. A time of day, from an entity or the
    configured default, is its next occurrence once the consumer became ready.
    """
    after = dt_util.as_local(after)
    if usable(state):
        domain = state.domain
        attributes = state.attributes
        if (
            domain == "input_datetime"
            and attributes.get("has_date")
            and not attributes.get("has_time")
        ):
            moment = None
        elif domain == "time" or (
            domain == "input_datetime" and not attributes.get("has_date")
        ):
            moment = _time_of_day(state.state, after)
        elif domain == "input_datetime":
            parsed = dt_util.parse_datetime(state.state)
            moment = (
                dt_util.as_local(parsed.replace(tzinfo=dt_util.get_default_time_zone()))
                if parsed
                else None
            )
        else:
            parsed = dt_util.parse_datetime(state.state)
            moment = dt_util.as_local(parsed) if parsed and parsed.tzinfo else None
        if moment is not None:
            return moment
    return _time_of_day(default_time, after) or _time_of_day(
        DEFAULT_DEADLINE_TIME, after
    )


def _time_of_day(value: str, after: datetime) -> datetime | None:
    try:
        parsed = time.fromisoformat(value)
    except ValueError:
        return None
    return next_occurrence(after, parsed.hour, parsed.minute, parsed.second)


################################################################################
# Adapters
################################################################################


class Adapter:
    """Reads and switches one consumer."""

    def __init__(
        self, hass: HomeAssistant, spec: ConsumerSpec, data: Mapping[str, Any]
    ) -> None:
        self.hass = hass
        self.spec = spec
        self.data = data

    @property
    def entities(self) -> list[str]:
        """Every entity whose change should trigger a run."""
        return [entity for entity in self._entities() if entity]

    def _entities(self) -> list[str | None]:
        return [self.data.get(CONF_POWER_SENSOR)]

    def state(self, key: str) -> State | None:
        entity_id = self.data.get(key)
        return self.hass.states.get(entity_id) if entity_id else None

    def power(self) -> float | None:
        return as_watts(self.state(CONF_POWER_SENSOR))

    def read(self, memory: ConsumerMemory, now: datetime) -> ConsumerReading:
        raise NotImplementedError

    async def async_apply(
        self,
        decision: ConsumerDecision,
        reading: ConsumerReading,
        memory: ConsumerMemory,
    ) -> None:
        raise NotImplementedError

    async def _call(
        self, domain: str, service: str, entity_id: str, **data: Any
    ) -> None:
        _LOGGER.debug(
            "%s: %s.%s %s %s", self.spec.name, domain, service, entity_id, data
        )
        try:
            await self.hass.services.async_call(
                domain, service, {"entity_id": entity_id, **data}, blocking=True
            )
        except HomeAssistantError as err:
            _LOGGER.warning(
                "%s: %s.%s on %s failed: %s",
                self.spec.name,
                domain,
                service,
                entity_id,
                err,
            )

    async def _switch(self, entity_id: str, on: bool) -> None:
        domain = entity_id.split(".", 1)[0]
        await self._call(domain, "turn_on" if on else "turn_off", entity_id)

    async def _run(self, entity_id: str) -> None:
        """Run a script or scene, press a button, or turn a switch on."""
        domain = entity_id.split(".", 1)[0]
        if domain in ("button", "input_button"):
            await self._call(domain, "press", entity_id)
        else:
            await self._call(domain, "turn_on", entity_id)


class SwitchAdapter(Adapter):
    """A consumer switched on and off."""

    def _entities(self) -> list[str | None]:
        return [self.data.get(CONF_SWITCH_ENTITY), *super()._entities()]

    def read(self, memory: ConsumerMemory, now: datetime) -> ConsumerReading:
        state = self.state(CONF_SWITCH_ENTITY)
        return ConsumerReading(
            available=usable(state), active=is_on(state), power=self.power()
        )

    async def async_apply(
        self,
        decision: ConsumerDecision,
        reading: ConsumerReading,
        memory: ConsumerMemory,
    ) -> None:
        if (
            decision.target_active is not None
            and decision.target_active != reading.active
        ):
            await self._switch(self.data[CONF_SWITCH_ENTITY], decision.target_active)


class NumberAdapter(Adapter):
    """A consumer whose power is set through a number, with an optional enable switch."""

    @property
    def _watts_per_unit(self) -> float:
        return float(self.data.get(CONF_WATTS_PER_UNIT, DEFAULT_WATTS_PER_UNIT)) or 1.0

    def _entities(self) -> list[str | None]:
        return [
            self.data.get(CONF_NUMBER_ENTITY),
            self.data.get(CONF_SWITCH_ENTITY),
            *super()._entities(),
        ]

    def read(self, memory: ConsumerMemory, now: datetime) -> ConsumerReading:
        number = self.state(CONF_NUMBER_ENTITY)
        value = as_float(number)
        level = (value or 0.0) * self._watts_per_unit
        active = level > 0
        available = value is not None
        if self.data.get(CONF_SWITCH_ENTITY):
            switch = self.state(CONF_SWITCH_ENTITY)
            available = available and usable(switch)
            active = active and is_on(switch)
        return ConsumerReading(
            available=available,
            active=active,
            level=level if active else 0.0,
            power=self.power(),
        )

    async def async_apply(
        self,
        decision: ConsumerDecision,
        reading: ConsumerReading,
        memory: ConsumerMemory,
    ) -> None:
        if decision.target_active is None:
            return
        number_id = self.data[CONF_NUMBER_ENTITY]
        switch_id = self.data.get(CONF_SWITCH_ENTITY)
        number = self.hass.states.get(number_id)
        attributes = number.attributes if number else {}
        lowest = float(attributes.get("min", 0))
        highest = float(attributes.get("max", 1e9))
        step = float(attributes.get("step", 0)) or None

        if decision.target_active:
            value = (decision.target_level or 0) / self._watts_per_unit
            if step:
                # Down, never up: a step up would draw more than was handed out.
                value = math.floor(value / step + 1e-9) * step
            value = min(max(value, lowest), highest)
        else:
            value = max(lowest, 0.0)
        current = as_float(number)
        if current is None or abs(current - value) > 1e-6:
            domain = number_id.split(".", 1)[0]
            await self._call(domain, "set_value", number_id, value=value)
        if (
            switch_id
            and is_on(self.hass.states.get(switch_id)) != decision.target_active
        ):
            await self._switch(switch_id, decision.target_active)


class SgReadyAdapter(Adapter):
    """A heat pump with the two SG Ready contacts."""

    def _entities(self) -> list[str | None]:
        return [
            self.data.get(CONF_SG_CONTACT_1),
            self.data.get(CONF_SG_CONTACT_2),
            *super()._entities(),
        ]

    def read(self, memory: ConsumerMemory, now: datetime) -> ConsumerReading:
        one, two = self.state(CONF_SG_CONTACT_1), self.state(CONF_SG_CONTACT_2)
        contacts = (is_on(one), is_on(two))
        level = next(state for state, pair in SG_CONTACTS.items() if pair == contacts)
        return ConsumerReading(
            available=usable(one) and usable(two),
            active=level >= SgState.RECOMMENDED,
            level=level,
            power=self.power(),
        )

    async def async_apply(
        self,
        decision: ConsumerDecision,
        reading: ConsumerReading,
        memory: ConsumerMemory,
    ) -> None:
        if decision.target_level is None:
            return
        want = SG_CONTACTS[SgState(int(decision.target_level))]
        have = SG_CONTACTS[SgState(int(reading.level))]
        one, two = self.data[CONF_SG_CONTACT_1], self.data[CONF_SG_CONTACT_2]
        # Off before on, contact 1 off first and contact 2 on first: a step
        # between normal and forced passes through recommended, never through
        # the lock.
        if have[0] and not want[0]:
            await self._switch(one, False)
        if have[1] and not want[1]:
            await self._switch(two, False)
        if want[1] and not have[1]:
            await self._switch(two, True)
        if want[0] and not have[0]:
            await self._switch(one, True)


class ScriptAdapter(Adapter):
    """A consumer started and stopped by scripts, buttons or scenes."""

    def _entities(self) -> list[str | None]:
        return [self.data.get(CONF_STATE_ENTITY), *super()._entities()]

    def read(self, memory: ConsumerMemory, now: datetime) -> ConsumerReading:
        if self.data.get(CONF_STATE_ENTITY):
            state = self.state(CONF_STATE_ENTITY)
            return ConsumerReading(
                available=usable(state), active=is_on(state), power=self.power()
            )
        available = present(self.state(CONF_ON_ENTITY)) and present(
            self.state(CONF_OFF_ENTITY)
        )
        return ConsumerReading(
            available=available, active=memory.commanded, power=self.power()
        )

    async def async_apply(
        self,
        decision: ConsumerDecision,
        reading: ConsumerReading,
        memory: ConsumerMemory,
    ) -> None:
        if decision.target_active is None or decision.target_active == reading.active:
            return
        await self._run(
            self.data[CONF_ON_ENTITY]
            if decision.target_active
            else self.data[CONF_OFF_ENTITY]
        )
        memory.commanded = decision.target_active


class DeferrableAdapter(Adapter):
    """A consumer that waits to be started."""

    @property
    def _start_is_switch(self) -> bool:
        return self.data[CONF_START_ENTITY].split(".", 1)[0] in SWITCHED_DOMAINS

    def _entities(self) -> list[str | None]:
        return [
            self.data.get(CONF_READY_ENTITY),
            self.data.get(CONF_START_ENTITY) if self._start_is_switch else None,
            self.data.get(CONF_DEADLINE_ENTITY),
            *super()._entities(),
        ]

    def read(self, memory: ConsumerMemory, now: datetime) -> ConsumerReading:
        ready = self.state(CONF_READY_ENTITY)
        start = self.state(CONF_START_ENTITY)
        deadline = resolve_deadline(
            self.state(CONF_DEADLINE_ENTITY),
            self.data.get(CONF_DEADLINE_TIME, DEFAULT_DEADLINE_TIME),
            memory.ready_since or now,
        )
        return ConsumerReading(
            available=usable(ready)
            and (usable(start) if self._start_is_switch else present(start)),
            active=is_on(start) if self._start_is_switch else None,
            power=self.power(),
            ready=is_on(ready),
            deadline=deadline,
        )

    async def async_apply(
        self,
        decision: ConsumerDecision,
        reading: ConsumerReading,
        memory: ConsumerMemory,
    ) -> None:
        start_id = self.data[CONF_START_ENTITY]
        if decision.start:
            await self._run(start_id)
        if decision.finish:
            if self._start_is_switch and self.data.get(CONF_TURN_OFF_WHEN_DONE, True):
                await self._switch(start_id, False)
            ready_id = self.data[CONF_READY_ENTITY]
            if ready_id.startswith("input_boolean."):
                # Done is done: the next run is marked ready again by hand.
                await self._switch(ready_id, False)


class SignalAdapter(Adapter):
    """An energy signal that another integration follows. Nothing is switched.

    The state it tells is remembered rather than read from an entity: its own
    sensor shows it, and that sensor shows what is remembered here.
    """

    def read(self, memory: ConsumerMemory, now: datetime) -> ConsumerReading:
        return ConsumerReading(
            active=memory.signal >= SgState.RECOMMENDED,
            level=memory.signal,
            power=self.power(),
        )

    async def async_apply(
        self,
        decision: ConsumerDecision,
        reading: ConsumerReading,
        memory: ConsumerMemory,
    ) -> None:
        if decision.target_level is not None:
            memory.signal = int(decision.target_level)
