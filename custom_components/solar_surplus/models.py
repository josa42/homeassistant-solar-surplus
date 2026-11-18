"""What the allocation reads, remembers and decides.

Nothing in here imports Home Assistant. The coordinator turns states into these
and back, so the engine can be tested with plain values.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any

from .const import (
    AdapterType,
    ConsumerState,
    DeferrablePhase,
    Override,
    Reason,
    SgState,
)


@dataclass(frozen=True, slots=True)
class HubSettings:
    """The hub's configuration, as the engine needs it."""

    battery_target_soc: float = 90
    battery_min_soc: float = 20
    battery_max_charge: float | None = None
    #: In Wh.
    battery_capacity: float | None = None
    reserve: float = 100
    base_load: float = 400
    signal_blocked: float = 500


@dataclass(frozen=True, slots=True)
class ConsumerSpec:
    """One consumer's configuration."""

    id: str
    name: str
    adapter: AdapterType
    power: float
    has_power_sensor: bool = False
    min_on_time: timedelta = timedelta(0)
    min_off_time: timedelta = timedelta(0)
    on_delay: timedelta = timedelta(0)
    off_delay: timedelta = timedelta(0)
    #: Number: the least it can run with, and the steps above that.
    min_power: float = 0
    power_step: float = 0
    #: SG Ready and signal: the surplus beyond its own power that makes it run
    #: forced, and whether it may be locked while the house draws from the
    #: grid.
    forced_power: float | None = None
    lock: bool = False
    #: Deferrable: how long a run takes, and when it counts as finished.
    run_time: timedelta = timedelta(hours=2)
    #: Deferrable: wait for the start the forecast gives the most solar power,
    #: rather than start on the first surplus that fits.
    wait_for_best: bool = True
    finish_power: float = 5
    finish_delay: timedelta = timedelta(minutes=5)


@dataclass(frozen=True, slots=True)
class ConsumerReading:
    """What a consumer's entities say right now."""

    available: bool = True
    #: On, running, or at SG Ready 3 or 4. None when nothing tells, such as a
    #: deferrable consumer started by a button.
    active: bool | None = False
    #: Number: the power it is set to. SG Ready and signal: the state it is in.
    level: float = 0
    #: What its power sensor measures, if it has one.
    power: float | None = None
    #: Deferrable: whether it waits to be started, and by when it has to be done.
    ready: bool = False
    deadline: datetime | None = None


@dataclass(frozen=True, slots=True)
class ConsumerInput:
    """A consumer as one run of the allocation sees it."""

    spec: ConsumerSpec
    reading: ConsumerReading
    override: Override = Override.AUTO


@dataclass(frozen=True, slots=True)
class ForecastPeriod:
    """The forecast for one stretch of time, as an average power."""

    start: datetime
    end: datetime
    watts: float


@dataclass(frozen=True, slots=True)
class Inputs:
    """The house as one run of the allocation sees it.

    Grid power is positive when drawing from the grid and battery power is
    positive when charging, whatever the sensors themselves report.
    """

    now: datetime
    grid: float | None
    battery: float | None = None
    soc: float | None = None
    forecast: tuple[ForecastPeriod, ...] = ()
    control_enabled: bool = True
    settings: HubSettings = field(default_factory=HubSettings)
    #: The base load learned for each hour of the day, local time. An hour not
    #: in it has the one from the settings.
    base_load: Mapping[int, float] = field(default_factory=dict)

    def base_load_at(self, time: datetime) -> float:
        """The base load expected at a time."""
        hour = time.astimezone(self.now.tzinfo).hour
        return self.base_load.get(hour, self.settings.base_load)


@dataclass(slots=True)
class ConsumerMemory:
    """What the engine remembers about one consumer from one run to the next."""

    active: bool | None = None
    since: datetime | None = None
    #: Whether it was seen turning on in this run, by whoever.
    turned_on: bool = False
    pending_since: datetime | None = None
    #: SG Ready: the second step, between recommended and forced.
    forced_pending_since: datetime | None = None
    lock_since: datetime | None = None
    lock_ended: datetime | None = None
    #: Script: what it was last told, when no entity says whether it is on.
    commanded: bool = False
    #: Signal: the state it tells, as an SG Ready state.
    signal: int = SgState.NORMAL
    #: Deferrable.
    phase: DeferrablePhase = DeferrablePhase.IDLE
    ready_since: datetime | None = None
    started_at: datetime | None = None
    low_since: datetime | None = None

    #: Kept across a restart. The timers are not: after a restart a consumer
    #: starts its minimum times afresh, which is the cautious choice.
    PERSISTED = ("commanded", "signal", "phase", "ready_since", "started_at")

    def to_dict(self) -> dict[str, Any]:
        """The part worth storing."""
        return {key: _plain(getattr(self, key)) for key in self.PERSISTED}

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> ConsumerMemory:
        """Read a stored memory back, forgiving anything malformed."""
        memory = cls()
        if not isinstance(raw, dict):
            return memory
        memory.commanded = bool(raw.get("commanded", False))
        signal = raw.get("signal")
        if signal in tuple(SgState):
            memory.signal = int(signal)
        try:
            memory.phase = DeferrablePhase(raw.get("phase", DeferrablePhase.IDLE))
        except ValueError:
            memory.phase = DeferrablePhase.IDLE
        memory.ready_since = _parse_datetime(raw.get("ready_since"))
        memory.started_at = _parse_datetime(raw.get("started_at"))
        return memory


@dataclass(slots=True)
class HubMemory:
    """What the engine remembers about the house from one run to the next."""

    smoothed: float | None = None
    smoothed_at: datetime | None = None


@dataclass(slots=True)
class EngineMemory:
    """Everything the engine carries over. It changes it in place."""

    hub: HubMemory = field(default_factory=HubMemory)
    consumers: dict[str, ConsumerMemory] = field(default_factory=dict)

    def consumer(self, consumer_id: str) -> ConsumerMemory:
        """The memory of one consumer, made on first use."""
        return self.consumers.setdefault(consumer_id, ConsumerMemory())


@dataclass(slots=True)
class ConsumerDecision:
    """What one consumer should do, and why."""

    id: str
    name: str
    adapter: AdapterType
    state: ConsumerState
    reason: Reason
    override: Override = Override.AUTO
    #: What to bring it to. None leaves it alone.
    target_active: bool | None = None
    #: Number: the power to set. SG Ready and signal: the state to set.
    target_level: float | None = None
    #: Deferrable: start it now, or it just finished.
    start: bool = False
    finish: bool = False
    #: What it draws, or is expected to draw, from the surplus.
    power: float = 0
    #: Held back for it while it waits out its delay to switch on, so the
    #: consumers below do not take it in the meantime.
    reserved: float = 0
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """A JSON-friendly copy."""
        return _plain(asdict(self))


@dataclass(slots=True)
class PlanWindow:
    """A stretch of time a consumer is expected to run."""

    start: datetime
    end: datetime
    #: SG Ready and signal: the state it would be in.
    level: float | None = None


@dataclass(slots=True)
class ConsumerPlan:
    """When a consumer is expected to run, from the forecast."""

    id: str
    windows: list[PlanWindow] = field(default_factory=list)
    #: The first expected run.
    expected_on: datetime | None = None
    expected_off: datetime | None = None
    #: Deferrable: the start the forecast gives the most solar power, and how
    #: much of the run the forecast surplus would cover then.
    recommended_start: datetime | None = None
    solar_share: float | None = None

    def to_dict(self) -> dict[str, Any]:
        """A JSON-friendly copy."""
        return _plain(asdict(self))


@dataclass(slots=True)
class Decision:
    """One run of the allocation."""

    now: datetime
    control_enabled: bool
    grid: float | None
    battery: float | None
    soc: float | None
    #: What could be handed out, before and after smoothing.
    surplus_raw: float | None
    surplus: float | None
    #: Handed out to the consumers, and what is left after them.
    allocated: float
    remaining: float | None
    consumers: list[ConsumerDecision]
    order: list[str]
    forecast: tuple[ForecastPeriod, ...] = ()
    plan: dict[str, ConsumerPlan] = field(default_factory=dict)
    #: The battery's expected charge at the end of each forecast period ahead,
    #: starting with what it holds now.
    soc_forecast: list[tuple[datetime, float]] = field(default_factory=list)

    def consumer(self, consumer_id: str) -> ConsumerDecision | None:
        """The decision for one consumer, if it is part of this run."""
        return next((c for c in self.consumers if c.id == consumer_id), None)

    def to_dict(self) -> dict[str, Any]:
        """A JSON-friendly copy, for the panel and the diagnostics."""
        return {
            "now": _plain(self.now),
            "control_enabled": self.control_enabled,
            "grid": self.grid,
            "battery": self.battery,
            "soc": self.soc,
            "surplus_raw": _round(self.surplus_raw),
            "surplus": _round(self.surplus),
            "allocated": _round(self.allocated),
            "remaining": _round(self.remaining),
            "consumers": [consumer.to_dict() for consumer in self.consumers],
            "order": list(self.order),
            "plan": {key: plan.to_dict() for key, plan in self.plan.items()},
            "soc_forecast": [
                {"time": _plain(time), "soc": soc} for time, soc in self.soc_forecast
            ],
            "forecast": [
                {
                    "start": _plain(p.start),
                    "end": _plain(p.end),
                    "watts": round(p.watts),
                }
                for p in self.forecast
            ],
        }


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 1)


def _plain(value: Any) -> Any:
    """Turn datetimes, durations and enums into what JSON can carry."""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, timedelta):
        return value.total_seconds()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_plain(item) for item in value]
    if isinstance(value, float):
        return round(value, 1)
    return value


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None
