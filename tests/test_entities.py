"""The entities: what the hub and each consumer show, and what can be set."""

from __future__ import annotations

from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    mock_restore_cache,
)

from custom_components.solar_surplus.const import DOMAIN

from .conftest import HEATING_ROD, grid

SIGNAL = "sensor.solar_surplus_energy_signal"
STATUS = "sensor.heating_rod_status"
MODE = "select.heating_rod_mode"
CONTROL = "switch.solar_surplus_control"


def on(hass: HomeAssistant, entity_id: str) -> bool:
    return hass.states.get(entity_id).state == "on"


async def test_the_hub_shows_the_surplus(
    hass: HomeAssistant, setup_entry, entry: MockConfigEntry
) -> None:
    grid(hass, -1500)
    coordinator = await setup_entry(entry)
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert float(hass.states.get("sensor.solar_surplus_surplus").state) == 1500 - 100
    assert float(hass.states.get("sensor.solar_surplus_allocated_power").state) == 0
    assert (
        float(hass.states.get("sensor.solar_surplus_remaining_surplus").state) == 1400
    )
    assert (
        hass.states.get("sensor.solar_surplus_surplus").attributes[
            "unit_of_measurement"
        ]
        == "W"
    )
    assert hass.states.get("sensor.solar_surplus_forecast_power") is None, (
        "only with a forecast"
    )


async def test_the_energy_signal(
    hass: HomeAssistant, setup_entry, entry: MockConfigEntry
) -> None:
    grid(hass, -3000)
    await setup_entry(entry)

    state = hass.states.get(SIGNAL)
    assert state.attributes["device_class"] == "enum"
    assert state.attributes["options"] == ["blocked", "normal", "recommended", "forced"]
    # The heating rod comes first and takes 2000 W of it; 900 W are left.
    assert state.state == "recommended"
    assert state.attributes["reason"] == "pv_surplus"
    assert state.attributes["since"]
    assert "until" not in state.attributes, "without a forecast nobody knows"


async def test_without_a_grid_reading_the_signal_is_unavailable(
    hass: HomeAssistant, setup_entry, entry: MockConfigEntry
) -> None:
    coordinator = await setup_entry(entry)
    hass.states.async_set("sensor.grid", "unavailable")
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(SIGNAL).state == "unavailable"


async def test_each_consumer_says_what_it_does_and_why(
    hass: HomeAssistant, setup_entry, entry: MockConfigEntry
) -> None:
    grid(hass, -800)
    coordinator = await setup_entry(entry)
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    state = hass.states.get(STATUS)
    assert state.state == "off"
    assert state.attributes["reason"] == "insufficient_surplus"
    assert state.attributes["needed"] == 2000
    assert state.attributes["available"] == 700


async def test_each_consumer_has_its_own_device(
    hass: HomeAssistant, setup_entry, entry: MockConfigEntry
) -> None:
    await setup_entry(entry)
    registry = dr.async_get(hass)
    rod = registry.async_get_device_by_identifier(
        (DOMAIN, next(iter(entry.subentries))), entry.entry_id
    )
    hub = registry.async_get_device_by_identifier(
        (DOMAIN, entry.entry_id), entry.entry_id
    )
    assert rod.name == "Heating rod"
    assert rod.via_device_id == hub.id


async def test_a_hand_on_a_consumer(
    hass: HomeAssistant, setup_entry, entry: MockConfigEntry
) -> None:
    grid(hass, 500)
    coordinator = await setup_entry(entry)
    assert hass.states.get(MODE).state == "auto"

    await hass.services.async_call(
        "select", "select_option", {"entity_id": MODE, "option": "on"}, blocking=True
    )
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert hass.states.get(MODE).state == "on"
    assert on(hass, HEATING_ROD)
    assert hass.states.get(STATUS).attributes["reason"] == "override_on"


async def test_control_off_switches_nothing(
    hass: HomeAssistant, setup_entry, entry: MockConfigEntry
) -> None:
    grid(hass, -3000)
    coordinator = await setup_entry(entry)
    assert on(hass, CONTROL)

    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": CONTROL}, blocking=True
    )
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert not on(hass, CONTROL)
    assert not on(hass, HEATING_ROD)
    assert hass.states.get(STATUS).state == "on", "it shows what it would do"


async def test_control_stays_off_across_a_restart(
    hass: HomeAssistant, setup_entry, entry: MockConfigEntry
) -> None:
    mock_restore_cache(hass, [State(CONTROL, "off")])
    grid(hass, -3000)
    coordinator = await setup_entry(entry)
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert coordinator.control_enabled is False
    assert not on(hass, HEATING_ROD)
