"""Test mode's simulated house, against the engine and without Home Assistant.

The real house never changes here: nothing is switched in test mode, so the
grid reading and the consumers' entities stay where they are, and only the
simulation moves.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

from custom_components.solar_surplus.const import (
    AdapterType,
    ConsumerState,
    DeferrablePhase,
    Reason,
    SgState,
)
from custom_components.solar_surplus.engine import decide
from custom_components.solar_surplus.models import (
    ConsumerInput,
    ConsumerReading,
    ConsumerSpec,
    Decision,
    EngineMemory,
    Inputs,
)
from custom_components.solar_surplus.simulation import Simulation

from .house import NO_MARGINS, T0, spec


class Paper:
    """A real house that stays put, and a simulation of it that does not."""

    def __init__(self, *specs: ConsumerSpec) -> None:
        self.specs = list(specs)
        self.readings = {s.id: self._initial(s) for s in specs}
        self.simulation = Simulation()
        self.memory = EngineMemory()
        self.now = T0
        self.actions = []

    @staticmethod
    def _initial(consumer: ConsumerSpec) -> ConsumerReading:
        if consumer.adapter is AdapterType.SG_READY:
            return ConsumerReading(level=SgState.NORMAL)
        if consumer.adapter is AdapterType.DEFERRABLE:
            return ConsumerReading(active=False)
        return ConsumerReading()

    def set(self, consumer_id: str, **changes) -> None:
        """Change a consumer for real, as someone at the house would."""
        self.readings[consumer_id] = replace(self.readings[consumer_id], **changes)

    def run(
        self,
        grid: float,
        *,
        after: timedelta = timedelta(0),
        control: bool = True,
    ) -> Decision:
        self.now += after
        self.memory.hub.smoothed = None
        inputs = Inputs(
            now=self.now, grid=grid, control_enabled=control, settings=NO_MARGINS
        )
        consumers = [
            ConsumerInput(spec=s, reading=self.readings[s.id]) for s in self.specs
        ]
        inputs, consumers = self.simulation.inputs(inputs, consumers)
        self.grid = inputs.grid
        decision = decide(inputs, consumers, [s.id for s in self.specs], self.memory)
        self.actions = self.simulation.apply(decision)
        return decision


def test_a_consumer_switched_on_stays_on() -> None:
    house = Paper(spec("rod", 2000))
    decision = house.run(-3000)
    assert decision.consumer("rod").state is ConsumerState.ON
    assert [(a.id, a.state, a.reason) for a in house.actions] == [
        ("rod", ConsumerState.ON, Reason.SURPLUS)
    ]

    decision = house.run(-3000, after=timedelta(seconds=10))
    assert decision.consumer("rod").state is ConsumerState.ON
    assert house.actions == [], "it is on already, nothing more to tell"


def test_the_grid_reading_counts_what_the_simulation_draws() -> None:
    house = Paper(spec("rod", 2000), spec("pump", 1500))
    house.run(-3000)
    assert [a.id for a in house.actions] == ["rod"]

    decision = house.run(-3000, after=timedelta(seconds=10))
    assert house.grid == -1000, "the rod would draw 2000 W of the 3000 W"
    assert decision.consumer("pump").state is ConsumerState.OFF, (
        "the real meter still shows 3000 W, but that is not left for the pump"
    )


def test_a_consumer_switched_off_by_a_cloud() -> None:
    house = Paper(spec("rod", 2000))
    house.run(-3000)
    house.run(-500, after=timedelta(seconds=10))
    assert house.grid == 1500
    assert [(a.id, a.state) for a in house.actions] == [("rod", ConsumerState.OFF)]


def test_switching_by_hand_is_taken_over() -> None:
    house = Paper(spec("rod", 2000), spec("pump", 1500))
    house.set("rod", active=True)
    # The rod really draws now: the meter shows its 2000 W.
    decision = house.run(-1000)
    assert house.grid == -1000, "what it really draws is not counted twice"
    assert decision.consumer("rod").state is ConsumerState.ON
    assert house.actions == []


def test_a_number_is_set_to_what_it_gets() -> None:
    house = Paper(
        spec("wallbox", 3000, AdapterType.NUMBER, min_power=1000, power_step=100)
    )
    house.run(-2350)
    assert [(a.id, a.level) for a in house.actions] == [("wallbox", 2300)]

    house.run(-2350, after=timedelta(seconds=10))
    assert house.grid == -50
    assert house.actions == []


def test_sg_ready_reports_its_state() -> None:
    house = Paper(spec("heat_pump", 1000, AdapterType.SG_READY, forced_power=1500))
    house.run(-3000)
    assert [(a.id, a.level) for a in house.actions] == [("heat_pump", SgState.FORCED)]

    house.run(-3000, after=timedelta(seconds=10))
    assert house.grid == -500, "forced, it would draw its power and the step"
    assert house.actions == []


def test_a_deferrable_run_starts_and_finishes() -> None:
    house = Paper(
        spec("washer", 500, AdapterType.DEFERRABLE, run_time=timedelta(hours=2))
    )
    house.set("washer", ready=True)
    house.run(-1000)
    assert [(a.id, a.state) for a in house.actions] == [
        ("washer", ConsumerState.RUNNING)
    ]
    assert house.memory.consumer("washer").phase is DeferrablePhase.RUNNING

    house.run(-1000, after=timedelta(hours=1))
    assert house.grid == -500
    assert house.actions == []

    decision = house.run(-1000, after=timedelta(hours=1))
    assert [(a.id, a.state) for a in house.actions] == [("washer", ConsumerState.DONE)]
    assert decision.consumer("washer").finish

    decision = house.run(-1000, after=timedelta(minutes=10))
    assert decision.consumer("washer").state is ConsumerState.IDLE, (
        "a finished run clears its ready entity, so it does not start again"
    )
    assert house.actions == []


def test_a_cleared_ready_entity_counts_again_once_it_really_went_off() -> None:
    house = Paper(
        spec("washer", 500, AdapterType.DEFERRABLE, run_time=timedelta(hours=1))
    )
    house.set("washer", ready=True)
    house.run(-1000)
    house.run(-1000, after=timedelta(hours=1))
    house.run(-1000, after=timedelta(minutes=1))

    house.set("washer", ready=False)
    house.run(-1000, after=timedelta(minutes=1))
    house.set("washer", ready=True)
    house.run(-1000, after=timedelta(minutes=1))
    assert [(a.id, a.state) for a in house.actions] == [
        ("washer", ConsumerState.RUNNING)
    ]


def test_without_control_nothing_is_reported() -> None:
    house = Paper(spec("rod", 2000))
    decision = house.run(-3000, control=False)
    assert decision.consumer("rod").target_active is True
    assert house.actions == []
    house.run(-3000, after=timedelta(seconds=10))
    assert [a.id for a in house.actions] == ["rod"], "nothing was pretended before"


def test_a_number_following_the_surplus_is_not_news() -> None:
    house = Paper(
        spec("wallbox", 3000, AdapterType.NUMBER, min_power=1000, power_step=100)
    )
    house.run(-1500)
    assert [(a.id, a.level) for a in house.actions] == [("wallbox", 1500)]

    # The sun comes out further: the meter, where the wallbox is still off,
    # shows 2500 W.
    decision = house.run(-2500, after=timedelta(seconds=10))
    assert decision.consumer("wallbox").target_level == 2500
    assert house.actions == [], "it would be set to more, but it is on already"
    assert house.simulation.consumers["wallbox"].level == 2500


def test_a_consumer_left_where_it_is_is_not_corrected() -> None:
    house = Paper(
        spec("washer", 500, AdapterType.DEFERRABLE),
        spec("rod", 2000, has_power_sensor=True),
    )
    # A finished washer whose plug is still on, and a rod someone turned on:
    # what they draw is in the meter, and the simulation leaves them be.
    house.set("washer", active=True)
    house.set("rod", active=True, power=1900)
    house.run(-100)
    assert house.grid == -100
