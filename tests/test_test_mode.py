"""Test mode inside Home Assistant: notifications instead of switching."""

from __future__ import annotations

from unittest.mock import patch

from homeassistant.core import HomeAssistant, State
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_mock_service,
    mock_restore_cache,
)

from custom_components.solar_surplus.const import CONF_NOTIFY_TARGET, ConsumerState

from .conftest import HEATING_ROD, HEATING_ROD_DATA, grid, hub

TEST_MODE = "switch.solar_surplus_test_mode"
CREATE = (
    "custom_components.solar_surplus.coordinator.persistent_notification.async_create"
)


def on(hass: HomeAssistant, entity_id: str) -> bool:
    return hass.states.get(entity_id).state == "on"


async def test_test_mode_notifies_instead_of_switching(
    hass: HomeAssistant, setup_entry, entry
) -> None:
    grid(hass, -3000)
    coordinator = await setup_entry(entry)
    with patch(CREATE) as create:
        await coordinator.async_set_test_mode_now(True)
        await hass.async_block_till_done()

    assert not on(hass, HEATING_ROD), "nothing is switched"
    message, title = create.call_args.args[1:]
    assert title == "Solar Surplus: Test mode"
    assert message == "Heating rod: On (Enough surplus)"


async def test_it_goes_on_as_if_it_had_switched(
    hass: HomeAssistant, setup_entry, entry
) -> None:
    grid(hass, -3000)
    coordinator = await setup_entry(entry)
    with patch(CREATE) as create:
        await coordinator.async_set_test_mode_now(True)
        await coordinator.async_refresh()
        await coordinator.async_refresh()

    assert create.call_count == 1, "only a change is told"
    assert coordinator.data.consumers[0].state is ConsumerState.ON
    assert coordinator.data.allocated == 2000
    assert coordinator.data.remaining == 900, "the meter's 3000 W, less the rod"
    assert hass.states.get("sensor.heating_rod_status").state == "on"
    assert not on(hass, HEATING_ROD)

    with patch(CREATE) as create:
        grid(hass, 500)
        await coordinator.async_refresh()
    assert create.call_args.args[1] == "Heating rod: Off (Not enough surplus)"


async def test_notifications_go_to_a_notify_action(
    hass: HomeAssistant, setup_entry
) -> None:
    calls = async_mock_service(hass, "notify", "phone")
    entry = hub(HEATING_ROD_DATA, **{CONF_NOTIFY_TARGET: "notify.phone"})
    entry.add_to_hass(hass)
    grid(hass, -3000)
    coordinator = await setup_entry(entry)
    await coordinator.async_set_test_mode_now(True)

    assert [call.data for call in calls] == [
        {
            "title": "Solar Surplus: Test mode",
            "message": "Heating rod: On (Enough surplus)",
        }
    ]


async def test_notifications_go_to_a_notify_entity(
    hass: HomeAssistant, setup_entry
) -> None:
    calls = async_mock_service(hass, "notify", "send_message")
    hass.states.async_set("notify.phone", "unknown")
    entry = hub(HEATING_ROD_DATA, **{CONF_NOTIFY_TARGET: "notify.phone"})
    entry.add_to_hass(hass)
    grid(hass, -3000)
    coordinator = await setup_entry(entry)
    await coordinator.async_set_test_mode_now(True)

    assert [call.data for call in calls] == [
        {
            "entity_id": "notify.phone",
            "title": "Solar Surplus: Test mode",
            "message": "Heating rod: On (Enough surplus)",
        }
    ]


async def test_a_missing_notify_target_falls_back_to_a_notification(
    hass: HomeAssistant, setup_entry
) -> None:
    entry = hub(HEATING_ROD_DATA, **{CONF_NOTIFY_TARGET: "notify.gone"})
    entry.add_to_hass(hass)
    grid(hass, -3000)
    coordinator = await setup_entry(entry)
    with patch(CREATE) as create:
        await coordinator.async_set_test_mode_now(True)
    assert create.call_count == 1


async def test_notifications_are_in_the_language_of_the_house(
    hass: HomeAssistant, setup_entry, entry
) -> None:
    await hass.config.async_update(language="de")
    grid(hass, -3000)
    coordinator = await setup_entry(entry)
    with patch(CREATE) as create:
        await coordinator.async_set_test_mode_now(True)
    message, title = create.call_args.args[1:]
    assert title == "Solar Surplus: Testmodus"
    assert message == "Heating rod: Ein (Genug Überschuss)"


async def test_after_test_mode_it_switches_again(
    hass: HomeAssistant, setup_entry, entry
) -> None:
    grid(hass, -3000)
    coordinator = await setup_entry(entry)
    with patch(CREATE):
        await coordinator.async_set_test_mode_now(True)
        await coordinator.async_refresh()
    assert not on(hass, HEATING_ROD)

    await coordinator.async_set_test_mode_now(False)
    await hass.async_block_till_done()
    assert on(hass, HEATING_ROD), "the real house is read again, and switched"


async def test_with_control_off_test_mode_tells_nothing(
    hass: HomeAssistant, setup_entry, entry
) -> None:
    grid(hass, -3000)
    coordinator = await setup_entry(entry)
    await coordinator.async_set_control_now(False)
    with patch(CREATE) as create:
        await coordinator.async_set_test_mode_now(True)
    assert create.call_count == 0
    assert not on(hass, HEATING_ROD)


async def test_the_switch_turns_test_mode_on(
    hass: HomeAssistant, setup_entry, entry
) -> None:
    coordinator = await setup_entry(entry)
    assert hass.states.get(TEST_MODE).state == "off"
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": TEST_MODE}, blocking=True
    )
    assert coordinator.test_mode is True
    assert hass.states.get(TEST_MODE).state == "on"


async def test_test_mode_stays_on_across_a_restart(
    hass: HomeAssistant, setup_entry, entry
) -> None:
    mock_restore_cache(hass, [State(TEST_MODE, "on")])
    coordinator = await setup_entry(entry)
    assert coordinator.test_mode is True


async def test_test_mode_from_the_panel(
    hass: HomeAssistant, setup_entry, entry, hass_ws_client
) -> None:
    coordinator = await setup_entry(entry)
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": "solar_surplus/set_test_mode", "enabled": True}
    )
    result = await client.receive_json()
    assert result["result"]["test_mode"] is True
    assert coordinator.test_mode is True
    await hass.async_block_till_done()
    assert hass.states.get(TEST_MODE).state == "on"


async def test_the_notify_target_is_set_in_the_options(
    hass: HomeAssistant, setup_entry, entry: MockConfigEntry
) -> None:
    async_mock_service(hass, "notify", "phone")
    await setup_entry(entry)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "test_mode"}
    )
    assert result["type"] is FlowResultType.FORM
    options = result["data_schema"].schema[CONF_NOTIFY_TARGET].config["options"]
    assert {"value": "notify.phone", "label": "notify.phone"} in options

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_NOTIFY_TARGET: "notify.phone"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_NOTIFY_TARGET] == "notify.phone"
