"""The websocket API the panel talks to."""

from __future__ import annotations

from homeassistant.config_entries import ConfigSubentry
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.solar_surplus.const import DOMAIN, Override

from .conftest import HEAT_PUMP_SIGNAL_DATA, HEATING_ROD, HEATING_ROD_DATA, grid, hub


async def subscribe(client) -> dict:
    await client.send_json_auto_id({"type": "solar_surplus/subscribe"})
    assert (await client.receive_json())["success"]
    return (await client.receive_json())["event"]


async def test_subscribing_pushes_every_run(
    hass: HomeAssistant, setup_entry, entry: MockConfigEntry, hass_ws_client
) -> None:
    grid(hass, -3000)
    coordinator = await setup_entry(entry)
    rod = next(iter(entry.subentries))
    client = await hass_ws_client(hass)

    first = await subscribe(client)
    assert first["consumers"][rod] == {
        "title": "Heating rod",
        "adapter": "switch",
        "power": 2000,
        "override": "auto",
    }
    assert first["control_enabled"] is True
    assert first["has_forecast"] is False
    assert first["settings"]["reserve"] == 100
    assert first["decision"]["order"] == [rod]
    assert first["decision"]["consumers"][0]["state"] == "on"

    grid(hass, 0)
    await coordinator.async_refresh()
    pushed = await client.receive_json()
    assert pushed["event"]["decision"]["grid"] == 0


async def test_reordering(hass: HomeAssistant, setup_entry, hass_ws_client) -> None:
    entry = hub(HEATING_ROD_DATA, HEAT_PUMP_SIGNAL_DATA)
    entry.add_to_hass(hass)
    coordinator = await setup_entry(entry)
    rod, signal = entry.subentries
    client = await hass_ws_client(hass)

    await client.send_json_auto_id(
        {"type": "solar_surplus/reorder", "order": [signal, rod]}
    )
    result = await client.receive_json()
    assert result["success"]
    assert result["result"]["decision"]["order"] == [signal, rod]
    assert coordinator.store.order == [signal, rod]


async def test_an_unknown_consumer_cannot_be_ordered(
    hass: HomeAssistant, setup_entry, entry: MockConfigEntry, hass_ws_client
) -> None:
    await setup_entry(entry)
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": "solar_surplus/reorder", "order": ["nobody"]}
    )
    result = await client.receive_json()
    assert not result["success"]
    assert result["error"]["code"] == "invalid_format"


async def test_a_hand_from_the_panel(
    hass: HomeAssistant, setup_entry, entry: MockConfigEntry, hass_ws_client
) -> None:
    grid(hass, 500)
    coordinator = await setup_entry(entry)
    rod = next(iter(entry.subentries))
    client = await hass_ws_client(hass)

    await client.send_json_auto_id(
        {"type": "solar_surplus/set_override", "consumer_id": rod, "override": "on"}
    )
    result = await client.receive_json()
    assert result["success"]
    assert result["result"]["consumers"][rod]["override"] == "on"
    assert coordinator.store.override(rod) is Override.ON
    await hass.async_block_till_done()
    assert hass.states.get(HEATING_ROD).state == "on"
    assert hass.states.get("select.heating_rod_mode").state == "on"

    await client.send_json_auto_id(
        {
            "type": "solar_surplus/set_override",
            "consumer_id": "nobody",
            "override": "on",
        }
    )
    assert (await client.receive_json())["error"]["code"] == "not_found"


async def test_control_from_the_panel(
    hass: HomeAssistant, setup_entry, entry: MockConfigEntry, hass_ws_client
) -> None:
    coordinator = await setup_entry(entry)
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": "solar_surplus/set_control", "enabled": False}
    )
    result = await client.receive_json()
    assert result["result"]["control_enabled"] is False
    assert coordinator.control_enabled is False
    await hass.async_block_till_done()
    assert hass.states.get("switch.solar_surplus_control").state == "off"


async def test_writing_takes_an_admin(
    hass: HomeAssistant,
    setup_entry,
    entry: MockConfigEntry,
    hass_ws_client,
    hass_read_only_access_token,
) -> None:
    await setup_entry(entry)
    client = await hass_ws_client(hass, hass_read_only_access_token)

    await subscribe(client)
    await client.send_json_auto_id({"type": "solar_surplus/reorder", "order": []})
    msg = await client.receive_json()
    while msg.get("type") == "event":
        msg = await client.receive_json()
    assert msg["error"]["code"] == "unauthorized"


async def test_without_the_integration_there_is_nothing(
    hass: HomeAssistant, hass_ws_client
) -> None:
    assert await async_setup_component(hass, DOMAIN, {})
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "solar_surplus/subscribe"})
    assert (await client.receive_json())["error"]["code"] == "not_found"
    await client.send_json_auto_id({"type": "solar_surplus/reorder", "order": []})
    assert (await client.receive_json())["error"]["code"] == "not_found"


async def test_the_subscription_survives_a_reload(
    hass: HomeAssistant, setup_entry, entry: MockConfigEntry, hass_ws_client
) -> None:
    await setup_entry(entry)
    client = await hass_ws_client(hass)
    await subscribe(client)

    hass.config_entries.async_add_subentry(
        entry,
        ConfigSubentry(
            data={
                **HEATING_ROD_DATA,
                "name": "Pool pump",
                "switch_entity": "input_boolean.pool_pump",
            },
            subentry_type="consumer",
            title="Pool pump",
            unique_id=None,
        ),
    )
    await hass.async_block_till_done()
    await entry.runtime_data.async_refresh()

    msg = await client.receive_json()
    while len(msg["event"]["consumers"]) < 2:
        msg = await client.receive_json()
    assert {c["title"] for c in msg["event"]["consumers"].values()} == {
        "Heating rod",
        "Pool pump",
    }
