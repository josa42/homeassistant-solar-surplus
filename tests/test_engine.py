"""The allocation: who gets the surplus, in which order, and when."""

from __future__ import annotations

import json
from datetime import timedelta

from custom_components.solar_surplus.const import (
    AdapterType,
    ConsumerState,
    DeferrablePhase,
    Override,
    Reason,
    SgState,
)
from custom_components.solar_surplus.engine import next_occurrence
from custom_components.solar_surplus.models import ConsumerMemory, HubSettings

from .house import T0, House, forecast, spec

SECONDS = timedelta(seconds=1)
MINUTES = timedelta(minutes=1)

################################################################################
# Switching by priority
################################################################################


def test_a_consumer_switches_on_when_its_power_fits() -> None:
    house = House(spec("rod", 1000))
    decision = house.run(1500)

    rod = decision.consumer("rod")
    assert rod.state is ConsumerState.ON
    assert rod.reason is Reason.SURPLUS
    assert rod.target_active is True
    assert decision.allocated == 1000
    assert decision.remaining == 500


def test_too_little_surplus_leaves_it_off() -> None:
    house = House(spec("rod", 1000))
    rod = house.run(900).consumer("rod")

    assert rod.state is ConsumerState.OFF
    assert rod.reason is Reason.INSUFFICIENT_SURPLUS
    assert rod.target_active is False
    assert rod.details["needed"] == 1000
    assert rod.details["available"] == 900


def test_the_first_in_the_order_is_served_first() -> None:
    house = House(spec("big", 2000), spec("small", 1000))
    decision = house.run(2500)
    assert decision.consumer("big").target_active is True
    assert decision.consumer("small").target_active is False

    house = House(spec("big", 2000), spec("small", 1000))
    house.order = ["small", "big"]
    decision = house.run(2500)
    assert decision.consumer("small").target_active is True
    assert decision.consumer("big").target_active is False


def test_a_consumer_below_takes_what_is_left() -> None:
    house = House(spec("big", 2000), spec("small", 500))
    decision = house.run(2600)
    assert decision.consumer("big").target_active is True
    assert decision.consumer("small").target_active is True
    assert decision.remaining == 100


def test_a_consumer_that_is_on_stays_on_while_the_house_exports() -> None:
    house = House(spec("rod", 1000), settings=HubSettings(reserve=100))
    assert house.run(1050).consumer("rod").target_active is False, (
        "switching on leaves the reserve exported"
    )
    assert house.run(1100).consumer("rod").target_active is True

    assert house.run(1000).consumer("rod").target_active is True, (
        "exporting nothing, it keeps running"
    )
    assert house.run(950).consumer("rod").target_active is False, (
        "drawing from the grid, it goes"
    )


def test_the_last_in_the_order_loses_its_power_first() -> None:
    house = House(spec("first", 1000), spec("second", 1000))
    house.run(2000)
    assert house.readings["first"].active and house.readings["second"].active

    decision = house.run(1500)
    assert decision.consumer("first").target_active is True
    assert decision.consumer("second").target_active is False


def test_a_consumer_above_takes_over_from_one_below() -> None:
    house = House(spec("first", 2000), spec("second", 1000))
    house.run(1200)
    assert not house.readings["first"].active and house.readings["second"].active

    decision = house.run(2200)
    assert decision.consumer("first").target_active is True
    assert decision.consumer("second").target_active is False


def test_a_measured_consumer_counts_with_what_it_draws() -> None:
    # A heating rod whose thermostat has cut out draws nothing, so the surplus
    # it was given goes on to the next consumer.
    house = House(spec("rod", 2000, has_power_sensor=True), spec("pump", 1000))
    house.set("rod", active=True)
    house.measured["rod"] = 0

    decision = house.run(1200)
    assert decision.consumer("rod").target_active is True
    assert decision.consumer("rod").power == 0
    assert decision.consumer("pump").target_active is True


def test_an_unavailable_consumer_is_left_alone() -> None:
    house = House(spec("rod", 1000), spec("pump", 500))
    house.set("rod", available=False)
    decision = house.run(1200)

    rod = decision.consumer("rod")
    assert rod.state is ConsumerState.UNAVAILABLE
    assert rod.target_active is None
    assert decision.consumer("pump").target_active is True


def test_a_hand_on_a_consumer_wins() -> None:
    house = House(spec("rod", 1000), spec("pump", 500))
    house.overrides = {"rod": Override.ON, "pump": Override.OFF}
    decision = house.run(0)

    assert decision.consumer("rod").target_active is True
    assert decision.consumer("rod").reason is Reason.OVERRIDE_ON
    assert decision.consumer("pump").target_active is False
    assert decision.consumer("pump").reason is Reason.OVERRIDE_OFF


def test_a_consumer_switched_on_by_hand_is_counted_as_ours() -> None:
    house = House(spec("rod", 1000))
    house.set("rod", active=True)
    # Exporting 300 with the rod on: it is part of the surplus.
    decision = house.run(1300)
    assert decision.surplus == 1300
    assert decision.consumer("rod").target_active is True


################################################################################
# Delays and minimum times
################################################################################


def test_enough_surplus_has_to_hold_before_switching_on() -> None:
    house = House(spec("rod", 1000, on_delay=60 * SECONDS))

    rod = house.run(1500).consumer("rod")
    assert rod.state is ConsumerState.WAITING
    assert rod.reason is Reason.ON_DELAY
    assert rod.details["until"] == T0 + 60 * SECONDS

    assert house.run(1500, after=30 * SECONDS).consumer("rod").target_active is False
    assert house.run(1500, after=30 * SECONDS).consumer("rod").target_active is True


def test_waiting_to_switch_on_holds_the_power_for_it() -> None:
    # The heat pump above waits out its delay; the wallbox below must not take
    # its power meanwhile, or both run once the delay is over.
    house = House(
        spec("heat_pump", 1200, on_delay=10 * SECONDS),
        spec("wallbox", 3000, AdapterType.NUMBER, min_power=1000, power_step=100),
    )
    decision = house.run(1500)
    assert decision.consumer("heat_pump").reason is Reason.ON_DELAY
    assert decision.consumer("heat_pump").details["reserved"] == 1200
    assert decision.consumer("wallbox").target_active is False
    assert decision.remaining == 300

    decision = house.run(1500, after=10 * SECONDS)
    assert decision.consumer("heat_pump").target_active is True
    assert decision.consumer("wallbox").target_active is False


def test_the_on_delay_starts_over_when_the_surplus_drops() -> None:
    house = House(spec("rod", 1000, on_delay=60 * SECONDS))
    house.run(1500)
    house.run(500, after=40 * SECONDS)
    rod = house.run(1500, after=40 * SECONDS).consumer("rod")
    assert rod.reason is Reason.ON_DELAY
    assert rod.details["until"] == house.now + 60 * SECONDS


def test_too_little_surplus_has_to_hold_before_switching_off() -> None:
    house = House(spec("rod", 1000, off_delay=120 * SECONDS))
    house.run(1500)

    rod = house.run(500, after=10 * SECONDS).consumer("rod")
    assert rod.state is ConsumerState.ON
    assert rod.reason is Reason.OFF_DELAY
    assert rod.power == 1000, "it is still booked while it runs"

    assert house.run(500, after=60 * SECONDS).consumer("rod").target_active is True
    assert house.run(500, after=60 * SECONDS).consumer("rod").target_active is False


def test_a_consumer_keeps_its_minimum_on_time() -> None:
    house = House(spec("rod", 1000, min_on_time=10 * MINUTES))
    house.run(1500)

    rod = house.run(0, after=MINUTES).consumer("rod")
    assert rod.target_active is True
    assert rod.reason is Reason.MIN_ON_TIME
    assert rod.details["until"] == T0 + 10 * MINUTES

    assert house.run(0, after=9 * MINUTES).consumer("rod").target_active is False


def test_with_control_off_nothing_starts_a_minimum_time() -> None:
    house = House(spec("rod", 1000, min_on_time=10 * MINUTES))
    decision = house.run(1500, control=False)
    assert decision.control_enabled is False
    assert decision.consumer("rod").target_active is True, (
        "it still says what it would do"
    )
    assert house.memory.consumer("rod").active is False


def test_a_consumer_keeps_its_minimum_off_time() -> None:
    house = House(spec("rod", 1000, min_off_time=5 * MINUTES))
    house.run(1500)
    house.run(0, after=MINUTES)

    rod = house.run(1500, after=MINUTES).consumer("rod")
    assert rod.target_active is False
    assert rod.reason is Reason.MIN_OFF_TIME

    assert house.run(1500, after=4 * MINUTES).consumer("rod").target_active is True


def test_switching_by_hand_starts_the_minimum_time_too() -> None:
    house = House(spec("rod", 1000, min_on_time=10 * MINUTES))
    house.run(0)
    house.set("rod", active=True)

    rod = house.run(0, after=MINUTES).consumer("rod")
    assert rod.target_active is True
    assert rod.reason is Reason.MIN_ON_TIME


def test_a_short_spike_does_not_switch_anything() -> None:
    house = House(spec("rod", 2000))
    house.smoothing = True
    house.run(0)

    decision = house.run(5000, after=10 * SECONDS)
    assert decision.surplus_raw == 5000
    assert decision.surplus < 2000
    assert decision.consumer("rod").target_active is False

    assert house.run(5000, after=60 * SECONDS).consumer("rod").target_active is True


def test_a_drop_in_the_surplus_counts_at_once() -> None:
    house = House(spec("rod", 2000))
    house.smoothing = True
    house.run(5000)
    assert house.run(-500, after=SECONDS).surplus == -500


################################################################################
# The battery
################################################################################


def test_a_full_battery_hands_out_what_it_charges_with() -> None:
    house = House(spec("rod", 1000))
    decision = house.run(0, battery=1500, soc=95)
    assert decision.consumer("rod").target_active is True


def test_a_battery_below_its_target_comes_first() -> None:
    house = House(spec("rod", 1000))
    decision = house.run(0, battery=1500, soc=50)
    assert decision.consumer("rod").target_active is False


def test_a_battery_without_charge_reading_comes_first() -> None:
    house = House(spec("rod", 1000))
    assert house.run(0, battery=1500).consumer("rod").target_active is False


def test_what_the_battery_feeds_the_house_is_never_surplus() -> None:
    house = House(spec("rod", 1000))
    house.set("rod", active=True)
    # The rod runs on the battery: the grid shows nothing.
    decision = house.run(0, grid=0, battery=-800, soc=95)
    assert decision.surplus == 200
    assert decision.consumer("rod").target_active is False


def test_a_known_charge_rate_is_held_back_for_the_battery() -> None:
    settings = HubSettings(reserve=0, battery_max_charge=3000)
    house = House(spec("rod", 1000), settings=settings)
    decision = house.run(1500, battery=1000, soc=50)
    assert decision.surplus == -500, "the battery could take 2000 more"
    assert decision.consumer("rod").target_active is False

    decision = house.run(1500, battery=3000, soc=50)
    assert decision.surplus == 1500, "charging at full rate, the export is surplus"
    assert decision.consumer("rod").target_active is True


################################################################################
# Variable consumers
################################################################################


def wallbox(**kwargs):
    return spec(
        "wallbox", 3000, AdapterType.NUMBER, min_power=1000, power_step=500, **kwargs
    )


def test_a_variable_consumer_takes_all_it_can_in_steps() -> None:
    house = House(wallbox())
    wb = house.run(2300).consumer("wallbox")
    assert wb.target_active is True
    assert wb.target_level == 2000
    assert wb.power == 2000


def test_a_variable_consumer_stays_off_below_its_minimum() -> None:
    house = House(wallbox())
    wb = house.run(900).consumer("wallbox")
    assert wb.target_active is False
    assert wb.target_level == 0


def test_a_variable_consumer_takes_no_more_than_its_power() -> None:
    house = House(wallbox())
    assert house.run(5000).consumer("wallbox").target_level == 3000


def test_a_variable_consumer_follows_the_surplus_down() -> None:
    house = House(wallbox())
    house.run(2000)
    assert house.readings["wallbox"].level == 2000

    wb = house.run(1600).consumer("wallbox")
    assert wb.target_level == 1500
    wb = house.run(800).consumer("wallbox")
    assert wb.target_active is False


def test_a_variable_consumer_on_by_hand_runs_at_full_power() -> None:
    house = House(wallbox())
    house.overrides["wallbox"] = Override.ON
    assert house.run(0).consumer("wallbox").target_level == 3000


################################################################################
# SG Ready
################################################################################


def heat_pump(**kwargs):
    return spec("heat_pump", 1000, AdapterType.SG_READY, **kwargs)


def test_sg_ready_is_recommended_when_its_power_fits() -> None:
    house = House(heat_pump())
    hp = house.run(1500).consumer("heat_pump")
    assert hp.state is ConsumerState.ON
    assert hp.target_level == SgState.RECOMMENDED

    hp = house.run(0).consumer("heat_pump")
    assert hp.state is ConsumerState.OFF
    assert hp.target_level == SgState.NORMAL


def test_sg_ready_is_forced_with_plenty_of_surplus() -> None:
    house = House(heat_pump(forced_power=2000))
    hp = house.run(3500).consumer("heat_pump")
    assert hp.target_level == SgState.FORCED
    assert hp.reason is Reason.FORCED_SURPLUS
    assert hp.power == 3000, (
        "without a sensor it is booked with the forced threshold on top"
    )

    assert house.run(3500).consumer("heat_pump").target_level == SgState.FORCED, (
        "it stays forced"
    )
    assert house.run(1500).consumer("heat_pump").target_level == SgState.RECOMMENDED


def test_sg_ready_without_a_forced_threshold_is_never_forced() -> None:
    house = House(heat_pump())
    assert house.run(10000).consumer("heat_pump").target_level == SgState.RECOMMENDED


def test_sg_ready_is_locked_while_drawing_from_the_grid() -> None:
    house = House(heat_pump(lock=True))
    hp = house.run(-1000).consumer("heat_pump")
    assert hp.state is ConsumerState.LOCKED
    assert hp.target_level == SgState.LOCK
    assert hp.reason is Reason.GRID_IMPORT

    hp = house.run(-1000, soc=80).consumer("heat_pump")
    assert hp.target_level == SgState.NORMAL, "the battery covers it"


def test_sg_ready_is_locked_for_two_hours_at_most() -> None:
    house = House(heat_pump(lock=True))
    house.run(-1000)
    assert (
        house.run(-1000, after=119 * MINUTES).consumer("heat_pump").target_level
        == SgState.LOCK
    )

    hp = house.run(-1000, after=MINUTES).consumer("heat_pump")
    assert hp.target_level == SgState.NORMAL
    assert hp.reason is Reason.LOCK_LIMIT

    assert (
        house.run(-1000, after=59 * MINUTES).consumer("heat_pump").target_level
        == SgState.NORMAL
    )
    assert (
        house.run(-1000, after=MINUTES).consumer("heat_pump").target_level
        == SgState.LOCK
    )


def test_sg_ready_is_not_locked_unless_asked_to() -> None:
    house = House(heat_pump())
    assert house.run(-1000).consumer("heat_pump").target_level == SgState.NORMAL


################################################################################
# Deferrable consumers
################################################################################

DEADLINE = T0.replace(hour=18)


def washer(**kwargs):
    kwargs.setdefault("run_time", timedelta(hours=2))
    return spec("washer", 500, AdapterType.DEFERRABLE, **kwargs)


def ready_washer(**kwargs) -> House:
    house = House(washer(**kwargs))
    house.set("washer", ready=True, deadline=DEADLINE, active=False)
    return house


def test_a_deferrable_consumer_waits_until_it_is_ready() -> None:
    house = House(washer())
    w = house.run(5000).consumer("washer")
    assert w.state is ConsumerState.IDLE
    assert w.reason is Reason.NOT_READY
    assert not w.start


def test_a_ready_consumer_starts_on_surplus() -> None:
    house = ready_washer()
    w = house.run(600).consumer("washer")
    assert w.state is ConsumerState.RUNNING
    assert w.reason is Reason.SURPLUS
    assert w.start is True
    assert house.memory.consumer("washer").phase is DeferrablePhase.RUNNING


def test_a_ready_consumer_waits_for_the_forecast_surplus() -> None:
    house = ready_washer()
    # Noon: 300 W expected now, 1500 W from 14:00 on. Base load is 400 W.
    w = house.run(0, forecast=forecast(300, 300, 1500, 1500)).consumer("washer")
    assert w.state is ConsumerState.WAITING
    assert w.reason is Reason.WAITING_FORECAST
    assert w.details["expected_start"] == T0 + timedelta(hours=2)
    assert w.details["latest_start"] == DEADLINE - timedelta(hours=2)


def test_the_latest_start_can_be_the_best() -> None:
    house = ready_washer()
    w = house.run(0, forecast=forecast(300, 300, 300, 300, 1500, 1500, 1500)).consumer(
        "washer"
    )
    assert w.reason is Reason.WAITING_FORECAST
    assert w.details["expected_start"] == DEADLINE - timedelta(hours=2)
    assert w.details["solar_share"] == 1.0


def test_without_a_forecast_surplus_it_waits_for_its_deadline() -> None:
    house = ready_washer()
    w = house.run(0, forecast=forecast(*[300] * 8)).consumer("washer")
    assert w.reason is Reason.WAITING_DEADLINE
    assert w.details["until"] == DEADLINE - timedelta(hours=2)


def test_it_waits_for_the_best_window() -> None:
    house = ready_washer()
    # The sun is out now, but the forecast leaves only 400 of its 500 W at
    # noon, and all of it from 13:00.
    sky = forecast(800, 1500, 1500, 300, 300, 300)
    w = house.run(1000, forecast=sky).consumer("washer")
    assert w.state is ConsumerState.WAITING
    assert w.details["expected_start"] == T0 + timedelta(hours=1)

    w = house.run(1000, after=timedelta(hours=1), forecast=sky).consumer("washer")
    assert w.start is True, "the best window has come"


def test_it_can_start_on_the_first_surplus_instead() -> None:
    house = ready_washer(wait_for_best=False)
    sky = forecast(800, 1500, 1500, 300, 300, 300)
    w = house.run(1000, forecast=sky).consumer("washer")
    assert w.start is True
    assert w.reason is Reason.SURPLUS


def test_it_starts_in_time_for_its_deadline() -> None:
    house = ready_washer()
    house.run(0)
    w = house.run(0, after=timedelta(hours=4)).consumer("washer")
    assert w.state is ConsumerState.RUNNING
    assert w.reason is Reason.DEADLINE
    assert w.start is True


def test_a_running_consumer_is_never_stopped() -> None:
    house = House(washer(), spec("rod", 1000))
    house.set("washer", ready=True, deadline=DEADLINE, active=False)
    house.run(600)

    decision = house.run(-2000, after=MINUTES)
    w = decision.consumer("washer")
    assert w.state is ConsumerState.RUNNING
    assert w.power == 500
    assert not w.start, "it is started once"
    assert decision.consumer("rod").target_active is False


def test_it_takes_its_power_from_those_below_it() -> None:
    house = House(washer(), spec("rod", 1000))
    house.set("washer", ready=True, deadline=DEADLINE, active=False)
    decision = house.run(1200)
    assert decision.consumer("washer").start is True
    assert decision.consumer("rod").target_active is False


def test_without_a_power_sensor_it_is_done_after_its_run_time() -> None:
    house = ready_washer()
    house.run(600)
    assert (
        house.run(600, after=119 * MINUTES).consumer("washer").state
        is ConsumerState.RUNNING
    )

    w = house.run(600, after=MINUTES).consumer("washer")
    assert w.state is ConsumerState.DONE
    assert w.finish is True

    w = house.run(600, after=MINUTES).consumer("washer")
    assert w.state is ConsumerState.DONE, (
        "it is not started again while still marked ready"
    )
    assert not w.start and not w.finish

    house.set("washer", ready=False)
    assert house.run(600, after=MINUTES).consumer("washer").state is ConsumerState.IDLE
    house.set("washer", ready=True)
    assert house.run(600, after=MINUTES).consumer("washer").start is True


def test_with_a_power_sensor_it_is_done_once_its_power_drops() -> None:
    house = ready_washer(
        has_power_sensor=True, finish_power=5, finish_delay=5 * MINUTES
    )
    house.run(600)
    house.measured["washer"] = 1
    assert (
        house.run(600, after=MINUTES).consumer("washer").state is ConsumerState.RUNNING
    ), "not while filling"

    house.measured["washer"] = 2000
    assert house.run(600, after=30 * MINUTES).consumer("washer").power == 2000

    house.measured["washer"] = 1
    assert (
        house.run(600, after=MINUTES).consumer("washer").state is ConsumerState.RUNNING
    )
    assert (
        house.run(600, after=5 * MINUTES).consumer("washer").state is ConsumerState.DONE
    )


def test_a_consumer_started_by_hand_runs() -> None:
    house = ready_washer()
    house.run(0)
    house.set("washer", active=True)
    w = house.run(0, after=MINUTES).consumer("washer")
    assert w.state is ConsumerState.RUNNING
    assert not w.start


def test_switched_off_while_running_it_is_done() -> None:
    house = ready_washer()
    house.run(600)
    house.set("washer", active=False)
    assert (
        house.run(600, after=MINUTES).consumer("washer").state is ConsumerState.RUNNING
    ), "not while the switch may not have reported yet"
    assert (
        house.run(600, after=5 * MINUTES).consumer("washer").state is ConsumerState.DONE
    )


def test_a_switch_left_on_does_not_count_as_a_start() -> None:
    house = House(washer())
    house.set("washer", active=True)
    house.run(0)
    house.set("washer", ready=True, deadline=DEADLINE)
    w = house.run(0, after=MINUTES).consumer("washer")
    assert w.state is ConsumerState.WAITING


def test_with_control_off_it_is_not_started() -> None:
    house = ready_washer()
    w = house.run(600, control=False).consumer("washer")
    assert w.state is ConsumerState.WAITING
    assert w.reason is Reason.SURPLUS, "it says why it would start"
    assert not w.start
    assert house.memory.consumer("washer").phase is DeferrablePhase.READY


def test_a_hand_on_a_deferrable_consumer() -> None:
    house = ready_washer()
    house.overrides["washer"] = Override.OFF
    assert (
        house.run(5000, after=timedelta(hours=5)).consumer("washer").reason
        is Reason.OVERRIDE_OFF
    )
    house.overrides["washer"] = Override.ON
    w = house.run(0).consumer("washer")
    assert w.start is True
    assert w.reason is Reason.OVERRIDE_ON


################################################################################
# Signals
################################################################################


def signal(**kwargs):
    return spec("signal", 1000, AdapterType.SIGNAL, **kwargs)


def test_a_signal_is_decided_like_sg_ready() -> None:
    house = House(signal(forced_power=1000))
    s = house.run(1500).consumer("signal")
    assert s.target_level == SgState.RECOMMENDED
    assert s.state is ConsumerState.ON
    assert house.run(2500).consumer("signal").target_level == SgState.FORCED


def test_a_signal_sees_what_is_left_at_its_place() -> None:
    house = House(spec("rod", 1000), signal())
    decision = house.run(1500)
    assert decision.consumer("rod").target_active is True
    assert decision.consumer("signal").target_level == SgState.NORMAL, (
        "500 W are left after the rod"
    )

    house = House(signal(), spec("rod", 1000))
    decision = house.run(1500)
    assert decision.consumer("signal").target_level == SgState.RECOMMENDED
    assert decision.consumer("rod").target_active is False, "first come, first served"


def test_what_follows_a_signal_does_not_switch_it_off() -> None:
    house = House(signal(has_power_sensor=True))
    house.run(1200)
    # The heat pump followed the signal and now draws 1100 W of the surplus.
    house.measured["signal"] = 1100
    assert house.run(1200).consumer("signal").target_level == SgState.RECOMMENDED


def test_a_signal_is_blocked_for_as_long_as_the_grid_is_drawn_from() -> None:
    house = House(signal(lock=True))
    s = house.run(-1000).consumer("signal")
    assert s.target_level == SgState.LOCK
    assert s.reason is Reason.GRID_IMPORT
    s = house.run(-1000, after=3 * timedelta(hours=1)).consumer("signal")
    assert s.target_level == SgState.LOCK, "unlike a heat pump, no two hour limit"

    s = house.run(-1000, soc=80).consumer("signal")
    assert s.target_level == SgState.NORMAL, "the battery covers it"


def test_without_a_grid_reading_nothing_is_decided() -> None:
    house = House(spec("rod", 1000))
    house.run(1500)
    decision = house.run(1500, grid=None)
    assert decision.surplus is None
    rod = decision.consumer("rod")
    assert rod.reason is Reason.NO_DATA
    assert rod.target_active is None
    assert rod.state is ConsumerState.ON


################################################################################
# Order and memory
################################################################################


def test_a_new_consumer_joins_at_the_end() -> None:
    house = House(spec("a"), spec("b"), spec("c"))
    house.order = ["b", "gone"]
    assert house.run(0).order == ["b", "a", "c"]

    house.order = []
    assert house.run(0).order == ["a", "b", "c"]


def test_a_run_survives_a_restart() -> None:
    memory = ConsumerMemory(
        phase=DeferrablePhase.RUNNING,
        started_at=T0,
        commanded=True,
        signal=SgState.FORCED,
    )
    restored = ConsumerMemory.from_dict(json.loads(json.dumps(memory.to_dict())))
    assert restored.phase is DeferrablePhase.RUNNING
    assert restored.started_at == T0
    assert restored.commanded is True
    assert restored.signal == SgState.FORCED


def test_a_broken_memory_is_forgotten() -> None:
    restored = ConsumerMemory.from_dict(
        {"phase": "flying", "started_at": "yesterday", "signal": 7}
    )
    assert restored.phase is DeferrablePhase.IDLE
    assert restored.signal == SgState.NORMAL
    assert restored.started_at is None
    assert ConsumerMemory.from_dict(None).phase is DeferrablePhase.IDLE


def test_a_decision_can_be_sent_as_json() -> None:
    house = House(spec("rod", 1000), washer())
    house.set("washer", ready=True, deadline=DEADLINE, active=False)
    decision = house.run(2000, forecast=forecast(1000, 2000))
    data = json.loads(json.dumps(decision.to_dict()))
    assert data["consumers"][0]["state"] == "on"
    assert data["consumers"][1]["details"]["started_at"] == T0.isoformat()
    assert data["forecast"][1]["watts"] == 2000


def test_the_next_time_of_day() -> None:
    assert next_occurrence(T0, 18, 0) == T0.replace(hour=18)
    assert next_occurrence(T0, 8, 30) == T0.replace(hour=8, minute=30) + timedelta(
        days=1
    )
