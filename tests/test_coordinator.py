"""Running the allocation inside Home Assistant, against helpers as devices."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.solar_surplus.const import (
    CONF_ADAPTER,
    CONF_BATTERY_DISCHARGE_POSITIVE,
    CONF_BATTERY_POWER,
    CONF_BATTERY_SOC,
    CONF_GRID_EXPORT_POSITIVE,
    CONF_MIN_POWER,
    CONF_NAME,
    CONF_NUMBER_ENTITY,
    CONF_OFF_ENTITY,
    CONF_ON_ENTITY,
    CONF_POWER,
    CONF_POWER_STEP,
    CONF_READY_ENTITY,
    CONF_RUN_TIME,
    CONF_SG_CONTACT_1,
    CONF_SG_CONTACT_2,
    CONF_START_ENTITY,
    CONF_STATE_ENTITY,
    SIGNAL_ID,
    STORAGE_KEY,
    AdapterType,
    ConsumerState,
    DeferrablePhase,
    EnergySignal,
    Override,
    Reason,
)

from .conftest import HEATING_ROD, HEATING_ROD_DATA, grid, hub

NO_TIMINGS = {"min_on_time": 0, "min_off_time": 0, "on_delay": 0, "off_delay": 0}

POOL_PUMP_DATA = {
    **HEATING_ROD_DATA,
    CONF_NAME: "Pool pump",
    CONF_POWER: 500,
    "switch_entity": "input_boolean.pool_pump",
}
WALLBOX_DATA = {
    CONF_NAME: "Wallbox",
    CONF_ADAPTER: AdapterType.NUMBER.value,
    CONF_POWER: 3000,
    CONF_MIN_POWER: 1000,
    CONF_POWER_STEP: 500,
    CONF_NUMBER_ENTITY: "input_number.wallbox",
    **NO_TIMINGS,
}
HEAT_PUMP_DATA = {
    CONF_NAME: "Heat pump",
    CONF_ADAPTER: AdapterType.SG_READY.value,
    CONF_POWER: 1000,
    CONF_SG_CONTACT_1: "input_boolean.sg_1",
    CONF_SG_CONTACT_2: "input_boolean.sg_2",
    **NO_TIMINGS,
}
AC_DATA = {
    CONF_NAME: "Air conditioner",
    CONF_ADAPTER: AdapterType.SCRIPT.value,
    CONF_POWER: 800,
    CONF_ON_ENTITY: "script.ac_on",
    CONF_OFF_ENTITY: "script.ac_off",
    CONF_STATE_ENTITY: "input_boolean.ac",
    **NO_TIMINGS,
}
WASHER_DATA = {
    CONF_NAME: "Washer",
    CONF_ADAPTER: AdapterType.DEFERRABLE.value,
    CONF_POWER: 500,
    CONF_READY_ENTITY: "input_boolean.washer_ready",
    CONF_START_ENTITY: "input_boolean.washer_plug",
    CONF_RUN_TIME: 120,
    "on_delay": 0,
}


def on(hass: HomeAssistant, entity_id: str) -> bool:
    return hass.states.get(entity_id).state == "on"


async def start(
    hass: HomeAssistant, setup_entry, *consumers: dict[str, Any], **data: Any
):
    entry = hub(*consumers, **data)
    entry.add_to_hass(hass)
    return entry, await setup_entry(entry)


def ids(entry: MockConfigEntry) -> dict[str, str]:
    """The subentry id of each consumer, by name."""
    return {
        subentry.title: subentry_id
        for subentry_id, subentry in entry.subentries.items()
    }


async def test_the_first_run_only_reads(
    hass: HomeAssistant, setup_entry, entry
) -> None:
    grid(hass, -3000)
    coordinator = await setup_entry(entry)
    assert coordinator.data.consumers[0].target_active is True
    assert not on(hass, HEATING_ROD), "nothing is written before the state is known"

    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert on(hass, HEATING_ROD)


async def test_consumers_follow_the_surplus(hass: HomeAssistant, setup_entry) -> None:
    grid(hass, -2600)
    entry, coordinator = await start(
        hass, setup_entry, HEATING_ROD_DATA, POOL_PUMP_DATA
    )
    await coordinator.async_refresh()
    assert on(hass, HEATING_ROD) and on(hass, "input_boolean.pool_pump")

    # Both run; the house now exports only 100 W, until a cloud comes.
    grid(hass, -100)
    await coordinator.async_refresh()
    assert on(hass, HEATING_ROD) and on(hass, "input_boolean.pool_pump")

    grid(hass, 300)
    await coordinator.async_refresh()
    assert on(hass, HEATING_ROD), "the first in the order stays"
    assert not on(hass, "input_boolean.pool_pump"), "the last goes first"


async def test_control_off_writes_nothing(
    hass: HomeAssistant, setup_entry, entry
) -> None:
    grid(hass, -3000)
    coordinator = await setup_entry(entry)
    coordinator.async_set_control(False)
    await coordinator.async_refresh()

    assert not on(hass, HEATING_ROD)
    assert coordinator.data.control_enabled is False
    assert coordinator.data.consumers[0].target_active is True, (
        "it still says what it would do"
    )


async def test_without_a_grid_reading_nothing_changes(
    hass: HomeAssistant, setup_entry, entry
) -> None:
    coordinator = await setup_entry(entry)
    hass.states.async_set("input_boolean.heating_rod", "on")
    hass.states.async_set("sensor.grid", "unavailable")
    await coordinator.async_refresh()

    assert on(hass, HEATING_ROD)
    assert coordinator.data.consumers[0].reason is Reason.NO_DATA
    assert coordinator.data.signal.state is None


async def test_meters_are_read_in_any_sign_and_unit(
    hass: HomeAssistant, setup_entry
) -> None:
    grid(hass, 2.5, "kW")
    hass.states.async_set("sensor.battery", "1000", {"unit_of_measurement": "W"})
    hass.states.async_set("sensor.soc", "95", {"unit_of_measurement": "%"})
    _, coordinator = await start(
        hass,
        setup_entry,
        HEATING_ROD_DATA,
        **{
            CONF_GRID_EXPORT_POSITIVE: True,
            CONF_BATTERY_POWER: "sensor.battery",
            CONF_BATTERY_DISCHARGE_POSITIVE: True,
            CONF_BATTERY_SOC: "sensor.soc",
        },
    )
    decision = coordinator.data
    assert decision.grid == -2500, "2.5 kW exported"
    assert decision.battery == -1000, "1 kW discharged"
    assert decision.soc == 95
    assert decision.surplus == 2500 - 1000 - 100


async def test_a_variable_consumer_is_set(hass: HomeAssistant, setup_entry) -> None:
    grid(hass, -2400)
    _, coordinator = await start(hass, setup_entry, WALLBOX_DATA)
    await coordinator.async_refresh()
    assert float(hass.states.get("input_number.wallbox").state) == 2000

    grid(hass, 2000 - 1200)  # the wallbox draws 2000 of 1200 W surplus
    await coordinator.async_refresh()
    assert float(hass.states.get("input_number.wallbox").state) == 1000


async def test_an_sg_ready_heat_pump_is_set_through_its_contacts(
    hass: HomeAssistant, setup_entry
) -> None:
    grid(hass, -1500)
    _, coordinator = await start(hass, setup_entry, HEAT_PUMP_DATA)
    await coordinator.async_refresh()

    assert not on(hass, "input_boolean.sg_1")
    assert on(hass, "input_boolean.sg_2"), "recommended"


async def test_a_consumer_is_switched_through_scripts(
    hass: HomeAssistant, setup_entry
) -> None:
    grid(hass, -1000)
    _, coordinator = await start(hass, setup_entry, AC_DATA)
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert on(hass, "input_boolean.ac")

    grid(hass, 800 + 500)
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert not on(hass, "input_boolean.ac")


async def test_a_washer_runs_once_it_is_ready(
    hass: HomeAssistant, setup_entry, hass_storage
) -> None:
    grid(hass, -800)
    entry, coordinator = await start(
        hass, setup_entry, {**WASHER_DATA, CONF_RUN_TIME: 0}
    )
    washer_id = ids(entry)["Washer"]
    await coordinator.async_refresh()
    assert not on(hass, "input_boolean.washer_plug"), "not before it is ready"

    await hass.services.async_call(
        "input_boolean",
        "turn_on",
        {"entity_id": "input_boolean.washer_ready"},
        blocking=True,
    )
    await coordinator.async_refresh()
    assert on(hass, "input_boolean.washer_plug")
    assert coordinator.memory.consumer(washer_id).phase is DeferrablePhase.RUNNING
    assert coordinator.store.memories[washer_id]["phase"] == "running", (
        "kept for a restart"
    )

    # A run time of zero: it is done at the next run.
    await coordinator.async_refresh()
    assert coordinator.data.consumer(washer_id).state is ConsumerState.DONE
    assert not on(hass, "input_boolean.washer_plug"), "turned off when done"
    assert not on(hass, "input_boolean.washer_ready"), "and no longer ready"


async def test_a_running_washer_survives_a_restart(
    hass: HomeAssistant, setup_entry, hass_storage
) -> None:
    entry = hub(WASHER_DATA)
    entry.add_to_hass(hass)
    washer_id = ids(entry)["Washer"]
    hass_storage[STORAGE_KEY] = {
        "version": 1,
        "minor_version": 1,
        "key": STORAGE_KEY,
        "data": {
            "memories": {
                washer_id: {
                    "phase": "running",
                    "started_at": "2026-06-15T11:30:00-07:00",
                }
            }
        },
    }
    hass.states.async_set("input_boolean.washer_plug", "on")
    grid(hass, 2000)

    coordinator = await setup_entry(entry)
    await coordinator.async_refresh()

    washer = coordinator.data.consumer(washer_id)
    assert washer.state is ConsumerState.RUNNING
    assert on(hass, "input_boolean.washer_plug"), (
        "it is not stopped for lack of surplus"
    )


async def test_the_order_and_the_hands_come_from_the_store(
    hass: HomeAssistant, setup_entry, hass_storage
) -> None:
    entry = hub(HEATING_ROD_DATA, POOL_PUMP_DATA)
    entry.add_to_hass(hass)
    rod, pump = ids(entry)["Heating rod"], ids(entry)["Pool pump"]
    hass_storage[STORAGE_KEY] = {
        "version": 1,
        "minor_version": 1,
        "key": STORAGE_KEY,
        "data": {
            "order": [pump, SIGNAL_ID, rod, "gone"],
            "overrides": {rod: "off", "gone": "on"},
        },
    }
    grid(hass, -3000)
    coordinator = await setup_entry(entry)
    await coordinator.async_refresh()

    assert coordinator.data.order == [pump, SIGNAL_ID, rod]
    assert coordinator.store.overrides == {rod: Override.OFF}
    assert on(hass, "input_boolean.pool_pump")
    assert not on(hass, HEATING_ROD)
    assert coordinator.data.signal.state is EnergySignal.FORCED, (
        "2500 W left after the pump"
    )


async def test_changing_a_hand_runs_again(
    hass: HomeAssistant, setup_entry, entry
) -> None:
    grid(hass, 1000)
    coordinator = await setup_entry(entry)
    rod = next(iter(entry.subentries))
    coordinator.store.async_set_override(rod, Override.ON)
    await coordinator.async_refresh()
    assert on(hass, HEATING_ROD)


async def test_unloading_keeps_what_was_remembered(
    hass: HomeAssistant, setup_entry, entry, hass_storage
) -> None:
    coordinator = await setup_entry(entry)
    rod = next(iter(entry.subentries))
    coordinator.store.async_set_order([rod, SIGNAL_ID])
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert hass_storage[STORAGE_KEY]["data"]["order"] == [rod, SIGNAL_ID]


async def test_adding_a_consumer_reloads(
    hass: HomeAssistant, setup_entry, entry
) -> None:
    from homeassistant.config_entries import ConfigSubentry

    await setup_entry(entry)
    hass.config_entries.async_add_subentry(
        entry,
        ConfigSubentry(
            data=POOL_PUMP_DATA,
            subentry_type="consumer",
            title="Pool pump",
            unique_id=None,
        ),
    )
    await hass.async_block_till_done()
    assert len(entry.runtime_data.consumers) == 2
