"""Test mode: a house in which every decision is carried out, on paper only.

Nothing is switched. Each consumer is taken to be wherever the decisions left
it, and the grid reading is corrected by what it would draw there, so the
allocation runs exactly as it would in control. What it would have switched is
handed back as `Action`s, for the coordinator to send as notifications.

Like the engine, nothing in here imports Home Assistant.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from .const import AdapterType, ConsumerState, Reason, SgState
from .engine import SG_KINDS, drawn
from .models import (
    ConsumerDecision,
    ConsumerInput,
    ConsumerReading,
    Decision,
    Inputs,
)


@dataclass(frozen=True, slots=True)
class Action:
    """Something the allocation would have switched."""

    id: str
    name: str
    adapter: AdapterType
    state: ConsumerState
    reason: Reason
    #: Number: the power it would be set to. SG Ready and signal: the state.
    level: float | None = None


@dataclass(slots=True)
class Pretended:
    """Where one consumer would be, had it been switched."""

    active: bool | None
    level: float
    #: The real reading last seen. When it changes, someone switched the
    #: consumer for real, and that is taken over.
    seen: ConsumerReading
    #: Deferrable: a run the simulation started, and so draws for.
    running: bool = False
    #: Deferrable: a finished run clears its ready entity. Until that entity
    #: really goes off, it counts as off.
    ready_cleared: bool = False


class Simulation:
    """The consumers as the allocation left them."""

    def __init__(self) -> None:
        self.consumers: dict[str, Pretended] = {}

    def inputs(
        self, inputs: Inputs, consumers: list[ConsumerInput]
    ) -> tuple[Inputs, list[ConsumerInput]]:
        """The house as it would be, from the house as it is."""
        pretended: list[ConsumerInput] = []
        correction = 0.0
        for consumer in consumers:
            state = self._follow(consumer.reading, consumer.spec.id)
            reading = replace(
                consumer.reading,
                active=state.active,
                level=state.level,
                # Its sensor measures it where it really is; where it would
                # be, it draws what it should.
                power=None,
                ready=consumer.reading.ready and not state.ready_cleared,
            )
            imagined = replace(consumer, reading=reading)
            correction += _correction(consumer, imagined, state)
            pretended.append(imagined)
        grid = None if inputs.grid is None else inputs.grid + correction
        return replace(inputs, grid=grid), pretended

    def _follow(self, real: ConsumerReading, consumer_id: str) -> Pretended:
        state = self.consumers.get(consumer_id)
        if state is None or _switched(state.seen, real):
            state = Pretended(active=real.active, level=real.level, seen=real)
            self.consumers[consumer_id] = state
        state.seen = real
        if not real.ready:
            state.ready_cleared = False
        return state

    def apply(self, decision: Decision) -> list[Action]:
        """Carry a decision out on paper, and say what it switched."""
        if not decision.control_enabled:
            return []
        actions: list[Action] = []
        for item in decision.consumers:
            state = self.consumers.get(item.id)
            if state is not None and _apply(item, state):
                actions.append(
                    Action(
                        id=item.id,
                        name=item.name,
                        adapter=item.adapter,
                        state=item.state,
                        reason=item.reason,
                        level=_level(item, state),
                    )
                )
        return actions


def _switched(before: ConsumerReading, now: ConsumerReading) -> bool:
    return (before.available, before.active, before.level) != (
        now.available,
        now.active,
        now.level,
    )


def _apply(item: ConsumerDecision, state: Pretended) -> bool:
    """Move one consumer where the decision wants it. True if that is news.

    A variable consumer that only changes its power is not: it would follow
    the surplus every few seconds, and so would the notifications.
    """
    if item.adapter is AdapterType.DEFERRABLE:
        if item.start:
            if state.active is not None:
                state.active = True
            state.running = True
            return True
        if item.finish:
            if state.active is not None:
                state.active = False
            state.running = False
            state.ready_cleared = True
            return True
        return False
    if item.adapter in SG_KINDS:
        if item.target_level is None or item.target_level == state.level:
            return False
        state.level = item.target_level
        state.active = item.target_level >= SgState.RECOMMENDED
        return True
    if item.target_active is None:
        return False
    if item.adapter is AdapterType.NUMBER:
        news = item.target_active != state.active
        state.active = item.target_active
        state.level = (item.target_level or 0.0) if item.target_active else 0.0
        return news
    if item.target_active == state.active:
        return False
    state.active = item.target_active
    return True


def _level(item: ConsumerDecision, state: Pretended) -> float | None:
    if item.adapter is AdapterType.NUMBER and state.active:
        return state.level
    if item.adapter in SG_KINDS:
        return state.level
    return None


def _correction(
    real: ConsumerInput, imagined: ConsumerInput, state: Pretended
) -> float:
    """What a consumer would draw beyond what it really does.

    Only where the simulation has it elsewhere than it really is: a consumer
    left where it is draws what it draws, and the meter shows that already.
    """
    if not real.reading.available:
        return 0.0
    if real.spec.adapter is AdapterType.DEFERRABLE:
        return real.spec.power - _measured(real) if state.running else 0.0
    if (state.active, state.level) == (real.reading.active, real.reading.level):
        return 0.0
    would = drawn(imagined) if imagined.reading.active else 0.0
    does = drawn(real) if real.reading.active else 0.0
    return would - (_measured(real) if _has_reading(real) else does)


def _has_reading(consumer: ConsumerInput) -> bool:
    return consumer.spec.has_power_sensor and consumer.reading.power is not None


def _measured(consumer: ConsumerInput) -> float:
    """What its power sensor says, or nothing without one."""
    return max(consumer.reading.power, 0.0) if _has_reading(consumer) else 0.0
