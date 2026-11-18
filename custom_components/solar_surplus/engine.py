"""The allocation: who gets the surplus, and why.

One run takes the house as it is (`Inputs`), the consumers in priority order and
what was remembered from the run before, and returns a `Decision`. It does not
call anything; the coordinator writes what it decided.

The surplus is what the house exports, plus what the consumers under control
draw, since that would be exported if they were off. Its rises are smoothed. It
is walked through in priority order: each consumer takes what it needs, if it
fits, and leaves the rest to the ones below it. A consumer that is on keeps
running until the house would draw from the grid. It switches on only once
enough surplus has held for its delay, and off once too little has held for its
delay. Between switching, it keeps its minimum on and off times. A consumer
below another loses its power first, because the one above is served before it.

A signal consumer is decided like an SG Ready heat pump, but switches nothing:
its state is published for another integration to follow, which reacts to it
as the heat pump would.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta

from .const import (
    FINISH_GRACE,
    SG_LOCK_MAX,
    SG_LOCK_PAUSE,
    SMOOTHING,
    AdapterType,
    ConsumerState,
    DeferrablePhase,
    Override,
    Reason,
    SgState,
)
from .models import (
    ConsumerDecision,
    ConsumerInput,
    ConsumerMemory,
    ConsumerPlan,
    Decision,
    EngineMemory,
    HubMemory,
    Inputs,
)
from .plan import make_plan

#: The kinds decided as SG Ready: lock, normal, recommended or forced.
SG_KINDS = (AdapterType.SG_READY, AdapterType.SIGNAL)


def decide(
    inputs: Inputs,
    consumers: list[ConsumerInput],
    order: list[str],
    memory: EngineMemory,
) -> Decision:
    """Run the allocation once. `memory` is updated in place."""
    now = inputs.now
    by_id = {consumer.spec.id: consumer for consumer in consumers}
    ordered = _ordered(order, by_id)

    for consumer in consumers:
        _observe(consumer, memory.consumer(consumer.spec.id), now)
    plan, soc_forecast = make_plan(inputs, consumers, ordered, memory)

    if inputs.grid is None:
        decision = _without_data(inputs, consumers, ordered, memory)
        decision.plan = plan
        decision.soc_forecast = soc_forecast
        return decision

    raw = _surplus(inputs, consumers, memory)
    smoothed = _smooth(memory.hub, raw, now)
    import_blocked = _import_blocked(inputs, smoothed)

    budget = smoothed
    decisions: list[ConsumerDecision] = []
    for item in ordered:
        consumer = by_id[item]
        decision = _decide_consumer(
            consumer,
            memory.consumer(item),
            inputs,
            budget,
            import_blocked,
            plan.get(item),
        )
        budget -= decision.power + decision.reserved
        decisions.append(decision)

    allocated = sum(decision.power for decision in decisions)
    return Decision(
        now=now,
        control_enabled=inputs.control_enabled,
        grid=inputs.grid,
        battery=inputs.battery,
        soc=inputs.soc,
        surplus_raw=raw,
        surplus=smoothed,
        allocated=allocated,
        remaining=budget,
        consumers=decisions,
        order=ordered,
        forecast=inputs.forecast,
        plan=plan,
        soc_forecast=soc_forecast,
    )


def _ordered(order: list[str], by_id: dict[str, ConsumerInput]) -> list[str]:
    """The priority order: as stored, then anything new.

    A consumer added since the order was last saved goes to the end, below
    everything the user has placed.
    """
    known = list(dict.fromkeys(item for item in order if item in by_id))
    return known + [consumer_id for consumer_id in by_id if consumer_id not in known]


def _observe(consumer: ConsumerInput, memory: ConsumerMemory, now: datetime) -> None:
    """Note when a consumer turned on or off, whoever did it.

    The minimum times count from the change, so a consumer switched by hand
    gets them too and is not switched back at once. The first sight of a
    consumer also starts them: after a restart nothing is known about how long
    it has been in its state.
    """
    reading = consumer.reading
    memory.turned_on = False
    if not reading.available or reading.active is None:
        return
    if memory.active is None or memory.active != reading.active:
        memory.turned_on = memory.active is False and reading.active
        memory.active = reading.active
        memory.since = now
        memory.pending_since = None


def drawn(consumer: ConsumerInput) -> float:
    """What a consumer draws: measured if it can be, else what it should."""
    reading = consumer.reading
    if consumer.spec.has_power_sensor and reading.power is not None:
        return max(reading.power, 0.0)
    if consumer.spec.adapter is AdapterType.NUMBER:
        return reading.level
    if consumer.spec.adapter in SG_KINDS and reading.level == SgState.FORCED:
        # Forced, it draws more than its nominal power; without a sensor the
        # forced threshold is the best guess of how much.
        return consumer.spec.power + (consumer.spec.forced_power or 0)
    return consumer.spec.power


def _is_drawing(consumer: ConsumerInput, memory: ConsumerMemory) -> bool:
    """Whether a consumer's power is in the grid reading as ours."""
    if not consumer.reading.available:
        return False
    if consumer.spec.adapter is AdapterType.DEFERRABLE:
        return memory.phase is DeferrablePhase.RUNNING
    return bool(consumer.reading.active)


def _surplus(
    inputs: Inputs, consumers: list[ConsumerInput], memory: EngineMemory
) -> float:
    """What could be handed out right now, before smoothing."""
    settings = inputs.settings
    own = sum(
        drawn(consumer)
        for consumer in consumers
        if _is_drawing(consumer, memory.consumer(consumer.spec.id))
    )
    battery = inputs.battery or 0.0
    charge = max(battery, 0.0)
    discharge = max(-battery, 0.0)
    # What the battery feeds the house is never surplus. What it charges with is
    # only handed out once it is full enough; below that, if its charge rate is
    # known, the part it does not use yet is held back for it as well.
    if inputs.battery is not None and (
        inputs.soc is None or inputs.soc < settings.battery_target_soc
    ):
        headroom = (
            max(settings.battery_max_charge - charge, 0.0)
            if settings.battery_max_charge
            else 0.0
        )
        battery_term = -discharge - headroom
    else:
        battery_term = charge - discharge
    return -inputs.grid + own + battery_term - settings.reserve


def _smooth(hub: HubMemory, raw: float, now: datetime) -> float:
    """The surplus, slow to rise and quick to fall.

    A rise is an exponential moving average over time, so a passing gap in the
    clouds does not switch anything on. A fall is taken at once: drawing from
    the grid should not wait, and the off delays already keep a kettle from
    switching anything off.
    """
    if hub.smoothed is None or hub.smoothed_at is None or raw <= hub.smoothed:
        hub.smoothed = raw
    elif now > hub.smoothed_at:
        elapsed = (now - hub.smoothed_at).total_seconds()
        alpha = 1 - math.exp(-elapsed / SMOOTHING.total_seconds())
        hub.smoothed += (raw - hub.smoothed) * alpha
    hub.smoothed_at = now
    return hub.smoothed


def _import_blocked(inputs: Inputs, smoothed: float) -> bool:
    """Whether the house draws from the grid with no battery to cover it."""
    settings = inputs.settings
    importing = -(smoothed + settings.reserve) >= settings.signal_blocked
    return importing and _battery_low(inputs)


def _battery_low(inputs: Inputs) -> bool:
    return inputs.soc is None or inputs.soc <= inputs.settings.battery_min_soc


def _without_data(
    inputs: Inputs,
    consumers: list[ConsumerInput],
    ordered: list[str],
    memory: EngineMemory,
) -> Decision:
    """Without a grid reading nothing can be decided, so nothing is changed."""
    decisions = []
    by_id = {consumer.spec.id: consumer for consumer in consumers}
    for item in ordered:
        consumer = by_id[item]
        state = ConsumerState.ON if consumer.reading.active else ConsumerState.OFF
        if not consumer.reading.available:
            state = ConsumerState.UNAVAILABLE
        decisions.append(_decision(consumer, state, Reason.NO_DATA))
    return Decision(
        now=inputs.now,
        control_enabled=inputs.control_enabled,
        grid=None,
        battery=inputs.battery,
        soc=inputs.soc,
        surplus_raw=None,
        surplus=None,
        allocated=0,
        remaining=None,
        consumers=decisions,
        order=ordered,
        forecast=inputs.forecast,
    )


def _decision(
    consumer: ConsumerInput, state: ConsumerState, reason: Reason, **kwargs
) -> ConsumerDecision:
    spec = consumer.spec
    return ConsumerDecision(
        id=spec.id,
        name=spec.name,
        adapter=spec.adapter,
        state=state,
        reason=reason,
        override=consumer.override,
        **kwargs,
    )


def _decide_consumer(
    consumer: ConsumerInput,
    memory: ConsumerMemory,
    inputs: Inputs,
    budget: float,
    import_blocked: bool,
    plan: ConsumerPlan | None,
) -> ConsumerDecision:
    if not consumer.reading.available:
        decision = _decision(consumer, ConsumerState.UNAVAILABLE, Reason.UNAVAILABLE)
        decision.details["available"] = round(budget)
        return decision
    adapter = consumer.spec.adapter
    if adapter is AdapterType.DEFERRABLE:
        decision = _deferrable(consumer, memory, inputs, budget, plan)
    elif adapter is AdapterType.NUMBER:
        decision = _number(consumer, memory, inputs, budget)
    elif adapter in SG_KINDS:
        decision = _sg_ready(consumer, memory, inputs, budget, import_blocked)
    else:
        decision = _on_off(consumer, memory, inputs, budget)
    decision.details.setdefault("available", round(budget))
    if decision.reason is Reason.ON_DELAY:
        decision.reserved = decision.details.get("needed", 0)
        decision.details["reserved"] = decision.reserved
    return decision


################################################################################
# Switching on and off
################################################################################


def _switching(
    consumer: ConsumerInput,
    memory: ConsumerMemory,
    inputs: Inputs,
    fits: bool,
    holds: bool,
) -> tuple[bool, Reason, dict]:
    """Whether a consumer should be on, under its delays and minimum times.

    `fits` says whether it would fit if it were off, `holds` whether it may
    stay on if it is. Returns the target, the reason and when the reason runs
    out, if it does.
    """
    spec = consumer.spec
    now = inputs.now
    active = bool(memory.active)

    if consumer.override is not Override.AUTO:
        target = consumer.override is Override.ON
        _switched(memory, inputs, target)
        return target, Reason.OVERRIDE_ON if target else Reason.OVERRIDE_OFF, {}

    wanted = holds if active else fits
    if wanted == active:
        memory.pending_since = None
        return active, Reason.SURPLUS if active else Reason.INSUFFICIENT_SURPLUS, {}

    if memory.pending_since is None:
        memory.pending_since = now
    delay = spec.off_delay if active else spec.on_delay
    delay_until = memory.pending_since + delay
    minimum = spec.min_on_time if active else spec.min_off_time
    since = memory.since or now
    minimum_until = since + minimum

    if now < minimum_until:
        reason = Reason.MIN_ON_TIME if active else Reason.MIN_OFF_TIME
        return active, reason, {"until": max(minimum_until, delay_until)}
    if now < delay_until:
        reason = Reason.OFF_DELAY if active else Reason.ON_DELAY
        return active, reason, {"until": delay_until}
    _switched(memory, inputs, wanted)
    return wanted, Reason.SURPLUS if wanted else Reason.INSUFFICIENT_SURPLUS, {}


def _switched(memory: ConsumerMemory, inputs: Inputs, target: bool) -> None:
    """Count the minimum time from the moment a consumer is switched.

    The entity reports the change a moment later, and the time would otherwise
    start then. With control off nothing is switched, so nothing starts.
    """
    if not inputs.control_enabled or memory.active == target:
        return
    memory.active = target
    memory.since = inputs.now
    memory.pending_since = None


def _on_off(
    consumer: ConsumerInput,
    memory: ConsumerMemory,
    inputs: Inputs,
    budget: float,
) -> ConsumerDecision:
    """A consumer that is either on or off: a switch or a pair of scripts."""
    need = consumer.spec.power
    power_now = drawn(consumer)
    fits = budget >= need
    # The reserve is the hysteresis: switched on, it leaves at least the reserve
    # exported; it is only switched off once the house draws from the grid.
    holds = budget + inputs.settings.reserve >= power_now
    target, reason, details = _switching(consumer, memory, inputs, fits, holds)
    details["needed"] = round(need)
    if target:
        power = power_now if consumer.reading.active else need
        state = ConsumerState.ON
    else:
        power = 0.0
        state = (
            ConsumerState.WAITING if reason is Reason.ON_DELAY else ConsumerState.OFF
        )
    return _decision(
        consumer, state, reason, target_active=target, power=power, details=details
    )


def _number(
    consumer: ConsumerInput,
    memory: ConsumerMemory,
    inputs: Inputs,
    budget: float,
) -> ConsumerDecision:
    """A consumer whose power can be set: it takes all it can get, in steps."""
    spec = consumer.spec
    minimum = spec.min_power if spec.min_power > 0 else (spec.power_step or spec.power)
    fits = budget >= minimum
    holds = budget + inputs.settings.reserve >= minimum
    target, reason, details = _switching(consumer, memory, inputs, fits, holds)
    details["needed"] = round(minimum)
    if not target:
        state = (
            ConsumerState.WAITING if reason is Reason.ON_DELAY else ConsumerState.OFF
        )
        return _decision(
            consumer,
            state,
            reason,
            target_active=False,
            target_level=0,
            details=details,
        )

    if reason is Reason.OVERRIDE_ON:
        level = spec.power
    else:
        level = _stepped(budget, minimum, spec.power, spec.power_step)
    details["level"] = round(level)
    return _decision(
        consumer,
        ConsumerState.ON,
        reason,
        target_active=True,
        target_level=level,
        power=level,
        details=details,
    )


def _stepped(budget: float, minimum: float, maximum: float, step: float) -> float:
    """The most of `budget` that fits between the limits, in whole steps."""
    if budget <= minimum:
        return minimum
    level = min(budget, maximum)
    if step > 0:
        level = minimum + math.floor((level - minimum) / step) * step
    return max(minimum, min(level, maximum))


def _sg_ready(
    consumer: ConsumerInput,
    memory: ConsumerMemory,
    inputs: Inputs,
    budget: float,
    import_blocked: bool,
) -> ConsumerDecision:
    """An SG Ready heat pump or a signal: locked, normal, recommended or forced.

    Recommended is its "on", and switches like any other consumer. Forced is a
    second step above it, for when the surplus beyond its own power reaches the
    forced threshold. A lock is only set when the house draws from the grid with
    the battery empty. A heat pump is locked for at most two hours at a time, as
    SG Ready allows; a signal says blocked for as long as it lasts.
    """
    spec = consumer.spec
    now = inputs.now
    need = spec.power
    power_now = drawn(consumer)
    fits = budget >= need
    # Forced, it may drop to recommended rather than off.
    holds = budget + inputs.settings.reserve >= min(power_now, need)
    target, reason, details = _switching(consumer, memory, inputs, fits, holds)
    details["needed"] = round(need)
    current = (
        SgState(int(consumer.reading.level))
        if consumer.reading.level in (1, 2, 3, 4)
        else SgState.NORMAL
    )

    if target:
        memory.lock_since = None
        level = SgState.RECOMMENDED
        if consumer.override is Override.ON:
            level = (
                SgState.FORCED if spec.forced_power is not None else SgState.RECOMMENDED
            )
        elif spec.forced_power is not None and reason is Reason.SURPLUS:
            level = _forced_step(consumer, memory, inputs, budget, current)
            if level is SgState.FORCED:
                reason = Reason.FORCED_SURPLUS
        expected = need + (spec.forced_power or 0) if level is SgState.FORCED else need
        if spec.has_power_sensor and consumer.reading.active:
            booked = power_now
        else:
            booked = expected
        details["level"] = int(level)
        return _decision(
            consumer,
            ConsumerState.ON,
            reason,
            target_active=True,
            target_level=level,
            power=booked,
            details=details,
        )

    memory.forced_pending_since = None
    level = SgState.NORMAL
    if spec.lock and import_blocked and consumer.override is Override.AUTO:
        if spec.adapter is AdapterType.SIGNAL:
            level = SgState.LOCK
            reason = Reason.GRID_IMPORT
        elif memory.lock_ended is not None and now < memory.lock_ended + SG_LOCK_PAUSE:
            reason = Reason.LOCK_LIMIT
            details["until"] = memory.lock_ended + SG_LOCK_PAUSE
        else:
            memory.lock_since = memory.lock_since or now
            if now - memory.lock_since >= SG_LOCK_MAX:
                memory.lock_ended = now
                memory.lock_since = None
                reason = Reason.LOCK_LIMIT
                details["until"] = now + SG_LOCK_PAUSE
            else:
                level = SgState.LOCK
                reason = Reason.GRID_IMPORT
                details["until"] = memory.lock_since + SG_LOCK_MAX
    elif memory.lock_since is not None:
        memory.lock_ended = now
        memory.lock_since = None

    details["level"] = int(level)
    if level is SgState.LOCK:
        state = ConsumerState.LOCKED
    elif reason is Reason.ON_DELAY:
        state = ConsumerState.WAITING
    else:
        state = ConsumerState.OFF
    return _decision(
        consumer,
        state,
        reason,
        target_active=False,
        target_level=level,
        details=details,
    )


def _forced_step(
    consumer: ConsumerInput,
    memory: ConsumerMemory,
    inputs: Inputs,
    budget: float,
    current: SgState,
) -> SgState:
    """Recommended or forced, with the consumer's own delays between them.

    Like switching on and off: forced once its power and the forced threshold
    fit, and back to recommended once the house draws from the grid.
    """
    spec = consumer.spec
    forced_now = current is SgState.FORCED
    need = spec.power + (spec.forced_power or 0)
    reserve = inputs.settings.reserve
    wanted = budget + reserve >= need if forced_now else budget >= need
    if wanted == forced_now:
        memory.forced_pending_since = None
        return (
            current
            if current in (SgState.RECOMMENDED, SgState.FORCED)
            else SgState.RECOMMENDED
        )
    if memory.forced_pending_since is None:
        memory.forced_pending_since = inputs.now
    delay = spec.off_delay if forced_now else spec.on_delay
    if inputs.now - memory.forced_pending_since >= delay:
        memory.forced_pending_since = None
        return SgState.FORCED if wanted else SgState.RECOMMENDED
    return (
        current
        if current in (SgState.RECOMMENDED, SgState.FORCED)
        else SgState.RECOMMENDED
    )


################################################################################
# Deferrable consumers
################################################################################


def _deferrable(
    consumer: ConsumerInput,
    memory: ConsumerMemory,
    inputs: Inputs,
    budget: float,
    plan: ConsumerPlan | None,
) -> ConsumerDecision:
    """A consumer that waits to be started, such as a washing machine.

    Once ready it is started when its power fits the surplus: from the start
    the forecast gives the most solar power on, or at once if it is not to wait
    for that. At the latest it is started so that it is done by its deadline.
    Once started it runs until it is done: stopping a washing machine halfway
    helps no one.
    """
    spec = consumer.spec
    reading = consumer.reading
    now = inputs.now

    if memory.phase is DeferrablePhase.RUNNING:
        return _deferrable_running(consumer, memory, inputs)

    if not reading.ready:
        memory.phase = DeferrablePhase.IDLE
        memory.ready_since = None
        memory.pending_since = None
        return _decision(consumer, ConsumerState.IDLE, Reason.NOT_READY)
    if memory.phase is DeferrablePhase.DONE:
        return _decision(consumer, ConsumerState.DONE, Reason.FINISHED)
    if memory.phase is DeferrablePhase.IDLE:
        memory.phase = DeferrablePhase.READY
        memory.ready_since = now
        memory.pending_since = None

    if memory.turned_on:
        # Started by hand, or by something else: it runs now. A switch that is
        # simply still on from the last run does not count.
        return _start(consumer, memory, inputs, Reason.RUNNING, command=False)

    details: dict = {"needed": round(spec.power)}
    latest_start = None
    if reading.deadline is not None:
        latest_start = reading.deadline - spec.run_time
        details["deadline"] = reading.deadline
        details["latest_start"] = latest_start

    if consumer.override is Override.OFF:
        memory.pending_since = None
        return _decision(
            consumer, ConsumerState.WAITING, Reason.OVERRIDE_OFF, details=details
        )
    if consumer.override is Override.ON:
        return _start(consumer, memory, inputs, Reason.OVERRIDE_ON, details=details)
    if latest_start is not None and now >= latest_start:
        return _start(consumer, memory, inputs, Reason.DEADLINE, details=details)

    recommended = plan.recommended_start if plan else None
    waits = spec.wait_for_best and recommended is not None and now < recommended
    if budget >= spec.power and not waits:
        if memory.pending_since is None:
            memory.pending_since = now
        if now - memory.pending_since >= spec.on_delay:
            return _start(consumer, memory, inputs, Reason.SURPLUS, details=details)
        details["until"] = memory.pending_since + spec.on_delay
        return _decision(
            consumer, ConsumerState.WAITING, Reason.ON_DELAY, details=details
        )
    memory.pending_since = None

    if recommended is not None:
        details["expected_start"] = recommended
        details["solar_share"] = plan.solar_share
        return _decision(
            consumer, ConsumerState.WAITING, Reason.WAITING_FORECAST, details=details
        )
    if latest_start is not None:
        details["until"] = latest_start
    return _decision(
        consumer, ConsumerState.WAITING, Reason.WAITING_DEADLINE, details=details
    )


def _start(
    consumer: ConsumerInput,
    memory: ConsumerMemory,
    inputs: Inputs,
    reason: Reason,
    *,
    command: bool = True,
    details: dict | None = None,
) -> ConsumerDecision:
    """Start a deferrable consumer, unless control is off."""
    details = details or {}
    if command and not inputs.control_enabled:
        # Nothing is written, so it has not started: it waits, and says why it
        # would have started.
        return _decision(consumer, ConsumerState.WAITING, reason, details=details)
    memory.phase = DeferrablePhase.RUNNING
    memory.started_at = inputs.now
    memory.low_since = None
    memory.pending_since = None
    details["started_at"] = inputs.now
    details["expected_end"] = inputs.now + consumer.spec.run_time
    return _decision(
        consumer,
        ConsumerState.RUNNING,
        reason,
        start=command,
        power=consumer.spec.power,
        details=details,
    )


def _deferrable_running(
    consumer: ConsumerInput,
    memory: ConsumerMemory,
    inputs: Inputs,
) -> ConsumerDecision:
    """A run in progress, until its power drops or its run time is over."""
    spec = consumer.spec
    reading = consumer.reading
    now = inputs.now
    started = memory.started_at or now
    details: dict = {"started_at": started, "expected_end": started + spec.run_time}

    finished = False
    if reading.active is False and now - started >= FINISH_GRACE:
        # Its switch went off: someone stopped it, or it stopped itself. Not
        # right after the start, while the switch may not have reported yet.
        finished = True
    elif spec.has_power_sensor and reading.power is not None:
        if now - started >= FINISH_GRACE and reading.power < spec.finish_power:
            memory.low_since = memory.low_since or now
            finished = now - memory.low_since >= spec.finish_delay
        else:
            memory.low_since = None
    elif now - started >= spec.run_time:
        finished = True

    if finished:
        memory.phase = DeferrablePhase.DONE
        memory.low_since = None
        details["finished_at"] = now
        return _decision(
            consumer,
            ConsumerState.DONE,
            Reason.FINISHED,
            finish=inputs.control_enabled,
            details=details,
        )
    return _decision(
        consumer,
        ConsumerState.RUNNING,
        Reason.RUNNING,
        power=drawn(consumer),
        details=details,
    )


def next_occurrence(
    after: datetime, hour: int, minute: int, second: int = 0
) -> datetime:
    """The first time of day at or after `after`, in its time zone."""
    candidate = after.replace(hour=hour, minute=minute, second=second, microsecond=0)
    if candidate < after:
        candidate += timedelta(days=1)
    return candidate
