"""The plan: when each consumer is expected to run, from the forecast."""

from __future__ import annotations

from datetime import timedelta

from custom_components.solar_surplus.const import AdapterType, Override, SgState
from custom_components.solar_surplus.models import HubSettings

from .house import T0, House, forecast, spec

HOUR = timedelta(hours=1)
#: Base load and reserve out of the way: the forecast is the surplus.
PLAIN = HubSettings(reserve=0, base_load=0)


def windows(plan) -> list[tuple[int, int, float | None]]:
    """The windows as hours after noon."""
    return [
        ((w.start - T0) // HOUR, (w.end - T0) // HOUR, w.level) for w in plan.windows
    ]


def test_without_a_forecast_there_is_no_plan() -> None:
    assert House(spec("rod", 1000), settings=PLAIN).run(2000).plan == {}


def test_a_consumer_runs_when_its_power_fits() -> None:
    house = House(spec("rod", 1000), settings=PLAIN)
    plan = house.run(0, forecast=forecast(500, 1200, 1500, 800, 1100)).plan["rod"]
    assert windows(plan) == [(1, 3, None), (4, 5, None)]
    assert plan.expected_on == T0 + HOUR
    assert plan.expected_off == T0 + 3 * HOUR


def test_the_priority_order_holds_in_the_plan() -> None:
    house = House(spec("rod", 1000), spec("pump", 1000), settings=PLAIN)
    plan = house.run(0, forecast=forecast(1500, 2500)).plan
    assert windows(plan["rod"]) == [(0, 2, None)]
    assert windows(plan["pump"]) == [(1, 2, None)], "only once the rod is served"


def test_sg_ready_and_signals_are_planned_by_level() -> None:
    house = House(
        spec("signal", 1000, AdapterType.SIGNAL, forced_power=1000), settings=PLAIN
    )
    plan = house.run(0, forecast=forecast(1200, 2500, 2500, 500)).plan["signal"]
    assert windows(plan) == [
        (0, 1, SgState.RECOMMENDED),
        (1, 3, SgState.FORCED),
    ]


def test_a_hand_on_a_consumer_is_planned_as_it_is() -> None:
    house = House(spec("rod", 1000), settings=PLAIN)
    house.overrides["rod"] = Override.OFF
    assert house.run(0, forecast=forecast(5000)).plan["rod"].windows == []
    house.overrides["rod"] = Override.ON
    assert windows(house.run(0, forecast=forecast(0, 0)).plan["rod"]) == [(0, 2, None)]


def test_the_current_period_starts_now() -> None:
    house = House(spec("rod", 1000), settings=PLAIN)
    house.run(0)
    plan = house.run(0, after=HOUR / 2, forecast=forecast(2000)).plan["rod"]
    assert plan.expected_on == T0 + HOUR / 2


def washer(**kwargs):
    kwargs.setdefault("run_time", 2 * HOUR)
    return spec("washer", 1000, AdapterType.DEFERRABLE, **kwargs)


def ready(house: House, deadline_hours: int = 8) -> House:
    house.set("washer", ready=True, deadline=T0 + deadline_hours * HOUR, active=False)
    return house


def test_a_deferrable_is_planned_where_the_sun_covers_it_most() -> None:
    house = ready(House(washer(), settings=PLAIN))
    plan = house.run(0, forecast=forecast(600, 1200, 900, 1500, 1500, 0)).plan["washer"]
    assert plan.recommended_start == T0 + 3 * HOUR
    assert plan.solar_share == 1.0
    assert windows(plan) == [(3, 5, None)]


def test_a_deferrable_is_planned_before_its_deadline() -> None:
    house = ready(House(washer(), settings=PLAIN), deadline_hours=4)
    plan = house.run(0, forecast=forecast(600, 1200, 900, 1500, 1500, 0)).plan["washer"]
    assert plan.recommended_start == T0 + HOUR, "it has to be done by 16:00"
    assert plan.solar_share == 0.95


def test_what_a_deferrable_takes_is_not_there_for_those_below() -> None:
    house = ready(House(washer(), spec("rod", 1000), settings=PLAIN))
    plan = house.run(0, forecast=forecast(0, 1500, 1500, 0)).plan
    assert windows(plan["washer"]) == [(1, 3, None)]
    assert plan["rod"].windows == []


def test_without_any_solar_there_is_no_recommended_start() -> None:
    house = ready(House(washer(), settings=PLAIN))
    plan = house.run(0, forecast=forecast(0, 0, 0)).plan["washer"]
    assert plan.recommended_start is None
    assert plan.solar_share == 0


def test_a_deferrable_that_is_not_ready_is_not_planned() -> None:
    house = House(washer(), settings=PLAIN)
    assert house.run(0, forecast=forecast(5000)).plan["washer"].windows == []


def test_a_running_deferrable_is_planned_until_it_ends() -> None:
    house = ready(House(washer(), settings=PLAIN))
    house.run(2000, forecast=forecast(2000, 2000))
    plan = house.run(0, after=HOUR / 2, forecast=forecast(2000, 2000)).plan["washer"]
    assert plan.expected_on == T0 + HOUR / 2
    assert plan.expected_off == T0 + 2 * HOUR
