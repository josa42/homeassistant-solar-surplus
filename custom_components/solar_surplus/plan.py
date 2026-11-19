"""The plan: when each consumer is expected to run, from the forecast.

The allocation is carried out once per forecast period, with the surplus the
forecast leaves once the house is served: each consumer in priority order takes
what it would take in that period, and leaves the rest to the ones below it. A
deferrable consumer is planned at the start where its run gets the most solar
power, before its deadline, and the consumers below it see what that leaves.

With the battery's capacity known, the plan follows its charge as well. Below
its target it charges first, as the engine has it, and the consumers share
what is left; above it, it charges with what they leave, and it covers the
house when the sun does not, down to the charge it counts as empty at.

It is a forecast and no more: the hourly figures know nothing of clouds within
the hour or of what else the house draws beyond its base load. Like the engine,
nothing in here imports Home Assistant.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from .const import AdapterType, DeferrablePhase, Override, SgState
from .models import (
    ConsumerInput,
    ConsumerPlan,
    EngineMemory,
    ForecastPeriod,
    Inputs,
    PlanWindow,
)

HOUR = timedelta(hours=1)


def make_plan(
    inputs: Inputs,
    consumers: list[ConsumerInput],
    order: list[str],
    memory: EngineMemory,
) -> tuple[dict[str, ConsumerPlan], list[tuple[datetime, float]]]:
    """Each consumer's expected runs, in priority order, and the battery's charge.

    Both are empty without a forecast; the charge also without the battery's
    capacity or a reading of its charge.
    """
    now = inputs.now
    periods = [p for p in inputs.forecast if p.end > now]
    if not periods:
        return {}, []
    settings = inputs.settings
    budgets = [
        p.watts - inputs.base_load_at(p.start) - settings.reserve for p in periods
    ]
    _battery_first(inputs, periods, budgets)
    available = list(budgets)
    by_id = {consumer.spec.id: consumer for consumer in consumers}
    plans: dict[str, ConsumerPlan] = {}
    for consumer_id in order:
        consumer = by_id.get(consumer_id)
        if consumer is None or not consumer.reading.available:
            continue
        if consumer.spec.adapter is AdapterType.DEFERRABLE:
            plan = _deferrable(inputs, consumer, memory, periods, budgets)
        else:
            plan = _running(inputs, consumer, periods, budgets)
        plans[consumer_id] = plan
    used = [before - after for before, after in zip(available, budgets, strict=True)]
    return plans, _charge(inputs, periods, used)


def _battery(inputs: Inputs) -> tuple[float, float] | None:
    """The battery's capacity in Wh and its charge now, if both are known."""
    capacity = inputs.settings.battery_capacity
    if not capacity or inputs.soc is None:
        return None
    return capacity, inputs.soc


def _battery_first(
    inputs: Inputs, periods: list[ForecastPeriod], budgets: list[float]
) -> None:
    """Take what the battery charges with below its target off the budgets."""
    battery = _battery(inputs)
    if battery is None:
        return
    capacity, soc = battery
    settings = inputs.settings
    floor = min(settings.battery_min_soc, soc)
    for index, period in enumerate(periods):
        hours = _hours(period, inputs.now, period.end)
        if hours <= 0:
            continue
        spare = period.watts - inputs.base_load_at(period.start)
        if spare > 0 and soc < settings.battery_target_soc:
            needed = (settings.battery_target_soc - soc) / 100 * capacity / hours
            charge = min(spare, settings.battery_max_charge or spare, needed)
            budgets[index] -= charge
            soc += charge * hours / capacity * 100
        elif spare < 0:
            soc = max(soc + spare * hours / capacity * 100, floor)


def _charge(
    inputs: Inputs, periods: list[ForecastPeriod], used: list[float]
) -> list[tuple[datetime, float]]:
    """The battery's charge now and at the end of each period, once the
    consumers have taken what the plan gives them."""
    battery = _battery(inputs)
    if battery is None:
        return []
    capacity, soc = battery
    settings = inputs.settings
    # It does not go below where it counts as empty, or below where it is.
    floor = min(settings.battery_min_soc, soc)
    points = [(inputs.now, round(soc, 1))]
    for period, taken in zip(periods, used, strict=True):
        hours = _hours(period, inputs.now, period.end)
        net = period.watts - inputs.base_load_at(period.start) - taken
        if net > 0:
            net = min(net, settings.battery_max_charge or net)
        soc = min(max(soc + net * hours / capacity * 100, floor), 100.0)
        points.append((period.end, round(soc, 1)))
    return points


def _start(period: ForecastPeriod, now: datetime) -> datetime:
    return max(period.start, now)


def _hours(period: ForecastPeriod, start: datetime, end: datetime) -> float:
    """How many hours of a period lie between `start` and `end`."""
    overlap = min(period.end, end) - max(period.start, start)
    return max(overlap / HOUR, 0.0)


def _running(
    inputs: Inputs,
    consumer: ConsumerInput,
    periods: list[ForecastPeriod],
    budgets: list[float],
) -> ConsumerPlan:
    """A consumer that runs whenever its power fits."""
    spec = consumer.spec
    hours: list[tuple[int, float | None]] = []
    for index, budget in enumerate(budgets):
        taken, level = _takes(consumer, budget)
        if taken is None:
            continue
        budgets[index] -= taken
        hours.append((index, level))
    windows = _windows(inputs.now, periods, hours)
    if spec.adapter is AdapterType.NUMBER:
        windows = [PlanWindow(w.start, w.end) for w in _merge_all(windows)]
    return _plan(spec.id, windows)


def _takes(consumer: ConsumerInput, budget: float) -> tuple[float | None, float | None]:
    """What a consumer would take of a period's surplus, and at which level.

    None when it would not run at all.
    """
    spec = consumer.spec
    override = consumer.override
    if override is Override.OFF:
        return None, None
    forced = spec.power + (spec.forced_power or 0)
    if spec.adapter in (AdapterType.SG_READY, AdapterType.SIGNAL):
        if override is Override.ON or (
            spec.forced_power is not None and budget >= forced
        ):
            if override is Override.ON and spec.forced_power is None:
                return spec.power, SgState.RECOMMENDED
            return forced, SgState.FORCED
        if budget >= spec.power:
            return spec.power, SgState.RECOMMENDED
        return None, None
    if spec.adapter is AdapterType.NUMBER:
        minimum = (
            spec.min_power if spec.min_power > 0 else (spec.power_step or spec.power)
        )
        if override is Override.ON:
            return spec.power, spec.power
        if budget < minimum:
            return None, None
        level = min(budget, spec.power)
        if spec.power_step > 0:
            level = minimum + ((level - minimum) // spec.power_step) * spec.power_step
        return level, level
    if override is Override.ON or budget >= spec.power:
        return spec.power, None
    return None, None


def _deferrable(
    inputs: Inputs,
    consumer: ConsumerInput,
    memory: EngineMemory,
    periods: list[ForecastPeriod],
    budgets: list[float],
) -> ConsumerPlan:
    """A run in progress, or the best start for one that is ready."""
    spec = consumer.spec
    now = inputs.now
    state = memory.consumer(spec.id)
    if state.phase is DeferrablePhase.RUNNING:
        started = state.started_at or now
        end = max(started + spec.run_time, now)
        _book(periods, budgets, spec.power, now, end)
        return _plan(spec.id, [PlanWindow(now, end)])
    if (
        not consumer.reading.ready
        or state.phase is DeferrablePhase.DONE
        or consumer.override is Override.OFF
    ):
        return ConsumerPlan(id=spec.id)

    latest = None
    if consumer.reading.deadline is not None:
        latest = max(consumer.reading.deadline - spec.run_time, now)
    if consumer.override is Override.ON:
        candidates = [now]
    else:
        candidates = [now] + [
            p.start
            for p in periods
            if p.start > now and (latest is None or p.start <= latest)
        ]
        if latest is not None and latest not in candidates:
            candidates.append(latest)
    best, share = None, -1.0
    for start in candidates:
        solar = _solar_share(periods, budgets, spec.power, start, spec.run_time)
        if solar > share + 1e-9:
            best, share = start, solar
    if share <= 0 and consumer.override is not Override.ON:
        # No start brings solar, so the engine waits for the deadline, or
        # without one for a surplus the forecast does not see.
        if latest is None:
            return ConsumerPlan(id=spec.id)
        best = latest
    end = best + spec.run_time
    _book(periods, budgets, spec.power, best, end)
    plan = _plan(spec.id, [PlanWindow(best, end)])
    plan.recommended_start = best if share > 0 else None
    plan.solar_share = round(share, 2)
    return plan


def _solar_share(
    periods: list[ForecastPeriod],
    budgets: list[float],
    power: float,
    start: datetime,
    run_time: timedelta,
) -> float:
    """How much of a run starting at `start` the forecast surplus would cover."""
    if power <= 0 or run_time <= timedelta(0):
        return 0.0
    end = start + run_time
    solar = sum(
        _hours(period, start, end) * min(max(budget, 0.0), power)
        for period, budget in zip(periods, budgets, strict=True)
    )
    return solar / (power * (run_time / HOUR))


def _book(
    periods: list[ForecastPeriod],
    budgets: list[float],
    power: float,
    start: datetime,
    end: datetime,
) -> None:
    """Take a run's power off the periods it falls into, by how much of each."""
    for index, period in enumerate(periods):
        share = _hours(period, start, end) / ((period.end - period.start) / HOUR)
        budgets[index] -= power * min(share, 1.0)


def _windows(
    now: datetime,
    periods: list[ForecastPeriod],
    hours: list[tuple[int, float | None]],
) -> list[PlanWindow]:
    """Runs of consecutive periods at the same level, as windows."""
    windows: list[PlanWindow] = []
    previous = None
    for index, level in hours:
        period = periods[index]
        if (
            windows
            and previous == index - 1
            and windows[-1].level == level
            and windows[-1].end == period.start
        ):
            windows[-1].end = period.end
        else:
            windows.append(PlanWindow(_start(period, now), period.end, level))
        previous = index
    return windows


def _merge_all(windows: list[PlanWindow]) -> list[PlanWindow]:
    """Join touching windows whatever their level."""
    merged: list[PlanWindow] = []
    for window in windows:
        if merged and merged[-1].end == window.start:
            merged[-1].end = window.end
        else:
            merged.append(PlanWindow(window.start, window.end))
    return merged


def _plan(consumer_id: str, windows: list[PlanWindow]) -> ConsumerPlan:
    plan = ConsumerPlan(id=consumer_id, windows=windows)
    if windows:
        first = _merge_all(windows)[0]
        plan.expected_on = first.start
        plan.expected_off = first.end
    return plan
