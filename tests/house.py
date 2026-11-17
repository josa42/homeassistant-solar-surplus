"""A make-believe house to run the engine against.

The house has a solar surplus of its own, before any consumer is switched, and
its grid reading follows from that and what the consumers draw. Each run
applies what the engine decided the way a perfect device would, so the next run
sees the consumers as they were left.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from custom_components.solar_surplus.const import (
    SIGNAL_ID,
    AdapterType,
    DeferrablePhase,
    Override,
    SgState,
)
from custom_components.solar_surplus.engine import decide
from custom_components.solar_surplus.models import (
    ConsumerInput,
    ConsumerReading,
    ConsumerSpec,
    Decision,
    EngineMemory,
    ForecastPeriod,
    HubSettings,
    Inputs,
)

T0 = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)
NO_MARGINS = HubSettings(reserve=0)


def spec(
    consumer_id: str,
    power: float = 1000,
    adapter: AdapterType = AdapterType.SWITCH,
    **kwargs,
) -> ConsumerSpec:
    """A consumer without delays or minimum times, unless asked for."""
    return ConsumerSpec(
        id=consumer_id, name=consumer_id.title(), adapter=adapter, power=power, **kwargs
    )


def forecast(*watts: float, start: datetime = T0) -> tuple[ForecastPeriod, ...]:
    """Hourly forecast periods from `start`, one per value."""
    return tuple(
        ForecastPeriod(
            start=start + timedelta(hours=i),
            end=start + timedelta(hours=i + 1),
            watts=w,
        )
        for i, w in enumerate(watts)
    )


class House:
    """Consumers in priority order, over a surplus the test sets."""

    def __init__(
        self, *specs: ConsumerSpec, settings: HubSettings = NO_MARGINS
    ) -> None:
        self.specs = {s.id: s for s in specs}
        self.order = [s.id for s in specs]
        self.settings = settings
        self.memory = EngineMemory()
        self.now = T0
        self.readings = {s.id: self._initial(s) for s in specs}
        self.overrides: dict[str, Override] = {}
        #: Measured power per consumer, for those with a sensor.
        self.measured: dict[str, float] = {}
        self.smoothing = False

    @staticmethod
    def _initial(consumer: ConsumerSpec) -> ConsumerReading:
        if consumer.adapter is AdapterType.SG_READY:
            return ConsumerReading(level=SgState.NORMAL)
        if consumer.adapter is AdapterType.DEFERRABLE:
            return ConsumerReading(active=None)
        return ConsumerReading()

    def draw(self, consumer_id: str) -> float:
        """What a consumer draws as it stands."""
        reading = self.readings[consumer_id]
        consumer = self.specs[consumer_id]
        if consumer_id in self.measured:
            return self.measured[consumer_id]
        if consumer.adapter is AdapterType.DEFERRABLE:
            running = self.memory.consumer(consumer_id).phase is DeferrablePhase.RUNNING
            return consumer.power if running else 0
        if consumer.adapter is AdapterType.NUMBER:
            return reading.level if reading.active else 0
        if consumer.adapter is AdapterType.SG_READY:
            if reading.level == SgState.FORCED:
                return consumer.power + (consumer.forced_power or 0)
            return consumer.power if reading.level == SgState.RECOMMENDED else 0
        return consumer.power if reading.active else 0

    def set(self, consumer_id: str, **changes) -> None:
        """Change what a consumer's entities say, as if from outside."""
        self.readings[consumer_id] = replace(self.readings[consumer_id], **changes)

    def run(
        self,
        surplus: float,
        *,
        after: timedelta = timedelta(0),
        battery: float | None = None,
        soc: float | None = None,
        followers: float = 0,
        forecast: tuple[ForecastPeriod, ...] = (),
        control: bool = True,
        grid: float | None | str = "derive",
    ) -> Decision:
        """One run, `after` the last, with the house exporting `surplus` on its own."""
        self.now += after
        if not self.smoothing:
            self.memory.hub.smoothed = None
        if grid == "derive":
            grid = -surplus + sum(self.draw(consumer_id) for consumer_id in self.specs)
        inputs = Inputs(
            now=self.now,
            grid=grid,
            battery=battery,
            soc=soc,
            followers=followers,
            forecast=forecast,
            control_enabled=control,
            settings=self.settings,
        )
        consumers = [
            ConsumerInput(
                spec=self.specs[consumer_id],
                reading=replace(
                    self.readings[consumer_id], power=self.measured.get(consumer_id)
                ),
                override=self.overrides.get(consumer_id, Override.AUTO),
            )
            for consumer_id in self.specs
        ]
        decision = decide(inputs, consumers, self.order, self.memory)
        if control:
            self._apply(decision)
        return decision

    def _apply(self, decision: Decision) -> None:
        for item in decision.consumers:
            reading = self.readings[item.id]
            if item.adapter is AdapterType.DEFERRABLE:
                if item.start and reading.active is not None:
                    self.set(item.id, active=True)
                if item.finish and reading.active is not None:
                    self.set(item.id, active=False)
                continue
            if item.target_active is None:
                continue
            changes: dict = {"active": item.target_active}
            if item.target_level is not None:
                changes["level"] = item.target_level
            self.set(item.id, **changes)

    def with_signal_at(self, index: int) -> None:
        """Place the energy signal in the order."""
        self.order = [i for i in self.order if i != SIGNAL_ID]
        self.order.insert(index, SIGNAL_ID)
