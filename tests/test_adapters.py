"""Reading consumers' entities and switching them."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from homeassistant.core import HomeAssistant, State
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_mock_service

from custom_components.solar_surplus.adapters import (
    as_watts,
    build_adapter,
    build_spec,
    resolve_deadline,
)
from custom_components.solar_surplus.const import (
    CONF_ADAPTER,
    CONF_NAME,
    CONF_NUMBER_ENTITY,
    CONF_OFF_ENTITY,
    CONF_ON_ENTITY,
    CONF_POWER,
    CONF_READY_ENTITY,
    CONF_SG_CONTACT_1,
    CONF_SG_CONTACT_2,
    CONF_START_ENTITY,
    CONF_SWITCH_ENTITY,
    CONF_WATTS_PER_UNIT,
    AdapterType,
    ConsumerState,
    Reason,
    SgState,
)
from custom_components.solar_surplus.models import ConsumerDecision, ConsumerMemory


def adapter(hass: HomeAssistant, kind: AdapterType, **data):
    data = {CONF_NAME: "Thing", CONF_ADAPTER: kind.value, CONF_POWER: 1000, **data}
    return build_adapter(hass, build_spec("thing", data), data)


def decision(kind: AdapterType, **kwargs) -> ConsumerDecision:
    return ConsumerDecision(
        id="thing",
        name="Thing",
        adapter=kind,
        state=ConsumerState.ON,
        reason=Reason.SURPLUS,
        **kwargs,
    )


def test_power_is_read_in_watts() -> None:
    assert as_watts(State("sensor.p", "1.5", {"unit_of_measurement": "kW"})) == 1500
    assert as_watts(State("sensor.p", "750", {"unit_of_measurement": "W"})) == 750
    assert as_watts(State("sensor.p", "unavailable")) is None
    assert as_watts(State("sensor.p", "lots")) is None
    assert as_watts(None) is None


################################################################################
# Deadlines
################################################################################


@pytest.fixture
def ready_at(hass: HomeAssistant) -> datetime:
    return dt_util.as_local(
        datetime(2026, 6, 15, 10, 0, tzinfo=dt_util.get_default_time_zone())
    )


def test_the_default_deadline_is_the_next_evening(ready_at: datetime) -> None:
    assert resolve_deadline(None, "18:00:00", ready_at) == ready_at.replace(hour=18)
    late = ready_at.replace(hour=19)
    assert resolve_deadline(None, "18:00:00", late) == ready_at.replace(
        hour=18
    ) + timedelta(days=1)


def test_a_deadline_from_a_date_and_time(ready_at: datetime) -> None:
    state = State(
        "input_datetime.d", "2026-06-16 07:30:00", {"has_date": True, "has_time": True}
    )
    assert resolve_deadline(state, "18:00:00", ready_at) == ready_at.replace(
        day=16, hour=7, minute=30
    )

    state = State("datetime.d", "2026-06-15T15:00:00+00:00")
    assert resolve_deadline(state, "18:00:00", ready_at) == datetime(
        2026, 6, 15, 15, tzinfo=dt_util.UTC
    )


def test_a_deadline_from_a_time_of_day(ready_at: datetime) -> None:
    state = State("time.d", "16:15:00")
    assert resolve_deadline(state, "18:00:00", ready_at) == ready_at.replace(
        hour=16, minute=15
    )
    state = State("input_datetime.d", "08:00:00", {"has_date": False, "has_time": True})
    assert resolve_deadline(state, "18:00:00", ready_at) == ready_at.replace(
        hour=8
    ) + timedelta(days=1)


def test_an_unusable_deadline_falls_back_to_the_time(ready_at: datetime) -> None:
    for state in (
        State("sensor.d", "unknown"),
        State("sensor.d", "soon"),
        State("input_datetime.d", "2026-06-16", {"has_date": True, "has_time": False}),
    ):
        assert resolve_deadline(state, "17:00:00", ready_at) == ready_at.replace(
            hour=17
        )


################################################################################
# Adapters
################################################################################


async def test_a_switch_is_only_switched_when_it_has_to(hass: HomeAssistant) -> None:
    calls = async_mock_service(hass, "switch", "turn_on")
    hass.states.async_set("switch.rod", "on")
    thing = adapter(hass, AdapterType.SWITCH, **{CONF_SWITCH_ENTITY: "switch.rod"})
    reading = thing.read(ConsumerMemory(), dt_util.now())
    assert reading.active is True

    await thing.async_apply(
        decision(AdapterType.SWITCH, target_active=True), reading, ConsumerMemory()
    )
    assert calls == []


async def test_a_number_is_set_in_its_own_unit(hass: HomeAssistant) -> None:
    set_value = async_mock_service(hass, "number", "set_value")
    turn_on = async_mock_service(hass, "switch", "turn_on")
    hass.states.async_set("number.current", "0", {"min": 6, "max": 16, "step": 1})
    hass.states.async_set("switch.charge", "off")
    thing = adapter(
        hass,
        AdapterType.NUMBER,
        **{
            CONF_NUMBER_ENTITY: "number.current",
            CONF_SWITCH_ENTITY: "switch.charge",
            CONF_WATTS_PER_UNIT: 230,
        },
    )
    reading = thing.read(ConsumerMemory(), dt_util.now())
    assert reading.active is False

    await thing.async_apply(
        decision(AdapterType.NUMBER, target_active=True, target_level=2000),
        reading,
        ConsumerMemory(),
    )
    assert set_value[0].data["value"] == 8, (
        "2000 W at 230 W per ampere, in whole amperes, rounded down"
    )
    assert turn_on[0].data["entity_id"] == "switch.charge"


async def test_a_number_without_a_switch_is_off_at_zero(hass: HomeAssistant) -> None:
    hass.states.async_set(
        "input_number.rod", "1500", {"min": 0, "max": 3000, "step": 100}
    )
    thing = adapter(
        hass, AdapterType.NUMBER, **{CONF_NUMBER_ENTITY: "input_number.rod"}
    )
    reading = thing.read(ConsumerMemory(), dt_util.now())
    assert reading.active is True
    assert reading.level == 1500

    set_value = async_mock_service(hass, "input_number", "set_value")
    await thing.async_apply(
        decision(AdapterType.NUMBER, target_active=False, target_level=0),
        reading,
        ConsumerMemory(),
    )
    assert set_value[0].data["value"] == 0


@pytest.mark.parametrize(
    ("contacts", "level"),
    [
        (("on", "off"), SgState.LOCK),
        (("off", "off"), SgState.NORMAL),
        (("off", "on"), SgState.RECOMMENDED),
        (("on", "on"), SgState.FORCED),
    ],
)
async def test_the_sg_ready_state_is_read_from_its_contacts(
    hass: HomeAssistant, contacts, level
) -> None:
    hass.states.async_set("switch.sg_1", contacts[0])
    hass.states.async_set("switch.sg_2", contacts[1])
    thing = adapter(
        hass,
        AdapterType.SG_READY,
        **{CONF_SG_CONTACT_1: "switch.sg_1", CONF_SG_CONTACT_2: "switch.sg_2"},
    )
    reading = thing.read(ConsumerMemory(), dt_util.now())
    assert reading.level == level
    assert reading.active is (level >= SgState.RECOMMENDED)


async def test_sg_ready_passes_through_recommended_not_the_lock(
    hass: HomeAssistant,
) -> None:
    order: list[tuple[str, str]] = []

    async def record(call) -> None:
        order.append((call.service, call.data["entity_id"]))

    hass.services.async_register("switch", "turn_on", record)
    hass.services.async_register("switch", "turn_off", record)
    hass.states.async_set("switch.sg_1", "off")
    hass.states.async_set("switch.sg_2", "off")
    thing = adapter(
        hass,
        AdapterType.SG_READY,
        **{CONF_SG_CONTACT_1: "switch.sg_1", CONF_SG_CONTACT_2: "switch.sg_2"},
    )

    reading = thing.read(ConsumerMemory(), dt_util.now())
    await thing.async_apply(
        decision(AdapterType.SG_READY, target_level=SgState.FORCED),
        reading,
        ConsumerMemory(),
    )
    assert order == [("turn_on", "switch.sg_2"), ("turn_on", "switch.sg_1")]

    order.clear()
    hass.states.async_set("switch.sg_1", "on")
    hass.states.async_set("switch.sg_2", "on")
    reading = thing.read(ConsumerMemory(), dt_util.now())
    await thing.async_apply(
        decision(AdapterType.SG_READY, target_level=SgState.NORMAL),
        reading,
        ConsumerMemory(),
    )
    assert order == [("turn_off", "switch.sg_1"), ("turn_off", "switch.sg_2")]


async def test_scripts_without_a_state_remember_what_they_were_told(
    hass: HomeAssistant,
) -> None:
    pressed = async_mock_service(hass, "button", "press")
    hass.states.async_set("button.on", "unknown")
    hass.states.async_set("button.off", "unknown")
    thing = adapter(
        hass,
        AdapterType.SCRIPT,
        **{CONF_ON_ENTITY: "button.on", CONF_OFF_ENTITY: "button.off"},
    )
    memory = ConsumerMemory()

    reading = thing.read(memory, dt_util.now())
    assert reading.available, "a button never pressed can be pressed"
    assert reading.active is False

    await thing.async_apply(
        decision(AdapterType.SCRIPT, target_active=True), reading, memory
    )
    assert pressed[0].data["entity_id"] == "button.on"
    assert thing.read(memory, dt_util.now()).active is True


async def test_a_deferrable_consumer_started_by_a_button(hass: HomeAssistant) -> None:
    pressed = async_mock_service(hass, "button", "press")
    hass.states.async_set("binary_sensor.washer_ready", "on")
    hass.states.async_set("button.washer_start", "unknown")
    thing = adapter(
        hass,
        AdapterType.DEFERRABLE,
        **{
            CONF_READY_ENTITY: "binary_sensor.washer_ready",
            CONF_START_ENTITY: "button.washer_start",
        },
    )
    reading = thing.read(ConsumerMemory(), dt_util.now())
    assert reading.available and reading.ready
    assert reading.active is None, "a button does not say whether it runs"

    await thing.async_apply(
        decision(AdapterType.DEFERRABLE, start=True), reading, ConsumerMemory()
    )
    assert pressed[0].data["entity_id"] == "button.washer_start"
