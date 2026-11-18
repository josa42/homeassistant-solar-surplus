"""Setting the hub up, changing it, and adding consumers to it."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest
from homeassistant.config_entries import SOURCE_RECONFIGURE, SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.solar_surplus.config_flow import forecast_entry_options
from custom_components.solar_surplus.const import (
    CONF_ADAPTER,
    CONF_BATTERY_POWER,
    CONF_DEADLINE_TIME,
    CONF_FORECAST_ENTRIES,
    CONF_GRID_POWER,
    CONF_MIN_POWER,
    CONF_NAME,
    CONF_NUMBER_ENTITY,
    CONF_OFF_ENTITY,
    CONF_ON_ENTITY,
    CONF_POWER,
    CONF_READY_ENTITY,
    CONF_RESERVE,
    CONF_SG_CONTACT_1,
    CONF_SG_CONTACT_2,
    CONF_START_ENTITY,
    CONF_SWITCH_ENTITY,
    DOMAIN,
    SUBENTRY_TYPE_CONSUMER,
    AdapterType,
)

from .conftest import GRID, HEATING_ROD, HUB_DATA


async def test_setting_the_hub_up(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(result["flow_id"], HUB_DATA)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_GRID_POWER] == GRID
    assert CONF_BATTERY_POWER not in result["data"], "a field left empty is not stored"
    assert result["data"][CONF_RESERVE] == 100, "the defaults are stored"


async def test_only_one_hub(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"


async def test_a_forecast_integration_can_be_chosen(hass: HomeAssistant) -> None:
    forecast = MockConfigEntry(domain="forecast_solar", title="Roof")
    forecast.add_to_hass(hass)
    unrelated = MockConfigEntry(domain="sun", title="Sun")
    unrelated.add_to_hass(hass)

    options = await forecast_entry_options(hass)

    assert [option["value"] for option in options] == [forecast.entry_id]
    assert options[0]["label"] == "Roof (Forecast.Solar)"


async def test_without_a_forecast_integration_the_field_is_left_out(
    hass: HomeAssistant,
) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert CONF_FORECAST_ENTRIES not in {
        str(key) for key in result["data_schema"].schema
    }


async def test_clearing_an_option_removes_it(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN, data={**HUB_DATA, CONF_BATTERY_POWER: "sensor.battery"}
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.MENU
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "inputs"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_GRID_POWER: "sensor.other"}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    values = {**entry.data, **entry.options}
    assert values[CONF_GRID_POWER] == "sensor.other"
    assert CONF_BATTERY_POWER not in values


async def _add(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    adapter: AdapterType,
    data: dict[str, Any],
):
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_TYPE_CONSUMER), context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {CONF_ADAPTER: adapter.value}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == adapter.value
    return await hass.config_entries.subentries.async_configure(result["flow_id"], data)


@pytest.mark.parametrize(
    ("adapter", "data"),
    [
        (AdapterType.SWITCH, {CONF_SWITCH_ENTITY: "switch.pool_pump"}),
        (
            AdapterType.NUMBER,
            {CONF_NUMBER_ENTITY: "number.wallbox_current", CONF_MIN_POWER: 1400},
        ),
        (
            AdapterType.SG_READY,
            {CONF_SG_CONTACT_1: "switch.sg_1", CONF_SG_CONTACT_2: "switch.sg_2"},
        ),
        (
            AdapterType.SCRIPT,
            {CONF_ON_ENTITY: "script.ac_on", CONF_OFF_ENTITY: "script.ac_off"},
        ),
        (
            AdapterType.DEFERRABLE,
            {
                CONF_READY_ENTITY: "input_boolean.washer_ready",
                CONF_START_ENTITY: "switch.washer",
            },
        ),
        (AdapterType.SIGNAL, {}),
    ],
)
async def test_adding_a_consumer_of_each_kind(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    adapter: AdapterType,
    data: dict[str, Any],
) -> None:
    result = await _add(
        hass, entry, adapter, {CONF_NAME: "New", CONF_POWER: 3000, **data}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    subentry = next(s for s in entry.subentries.values() if s.title == "New")
    assert subentry.data[CONF_ADAPTER] == adapter.value
    assert subentry.data[CONF_POWER] == 3000


async def test_a_deferrable_consumer_defaults_to_a_deadline_in_the_evening(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    await _add(
        hass,
        entry,
        AdapterType.DEFERRABLE,
        {
            CONF_NAME: "Washer",
            CONF_POWER: 500,
            CONF_READY_ENTITY: "input_boolean.washer_ready",
            CONF_START_ENTITY: "switch.washer",
        },
    )
    subentry = next(s for s in entry.subentries.values() if s.title == "Washer")
    assert subentry.data[CONF_DEADLINE_TIME] == "18:00:00"


async def test_one_entity_switches_one_consumer(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    result = await _add(
        hass,
        entry,
        AdapterType.SWITCH,
        {CONF_NAME: "Twin", CONF_POWER: 1000, CONF_SWITCH_ENTITY: HEATING_ROD},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_SWITCH_ENTITY: "already_controlled"}


async def test_the_two_contacts_have_to_differ(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    result = await _add(
        hass,
        entry,
        AdapterType.SG_READY,
        {
            CONF_NAME: "Heat pump",
            CONF_POWER: 1000,
            CONF_SG_CONTACT_1: "switch.sg",
            CONF_SG_CONTACT_2: "switch.sg",
        },
    )
    assert result["errors"] == {CONF_SG_CONTACT_2: "same_contact"}


async def test_the_minimum_power_fits_the_power(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    result = await _add(
        hass,
        entry,
        AdapterType.NUMBER,
        {
            CONF_NAME: "Wallbox",
            CONF_POWER: 1000,
            CONF_NUMBER_ENTITY: "number.wallbox",
            CONF_MIN_POWER: 1400,
        },
    )
    assert result["errors"] == {CONF_MIN_POWER: "min_above_power"}


async def test_changing_a_consumer_keeps_its_kind(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    subentry_id = next(iter(entry.subentries))
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_TYPE_CONSUMER),
        context={"source": SOURCE_RECONFIGURE, "subentry_id": subentry_id},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == AdapterType.SWITCH.value

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {CONF_NAME: "Hot water", CONF_POWER: 3000, CONF_SWITCH_ENTITY: HEATING_ROD},
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    subentry = entry.subentries[subentry_id]
    assert subentry.title == "Hot water"
    assert subentry.data[CONF_POWER] == 3000
    assert subentry.data[CONF_ADAPTER] == AdapterType.SWITCH.value


async def test_the_grid_power_is_needed_from_somewhere(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_GRID_POWER: "no_grid_power"}


async def test_the_grid_power_can_come_from_the_energy_dashboard(
    hass: HomeAssistant,
) -> None:
    prefs = {"energy_sources": [{"type": "grid", "stat_rate": GRID}]}
    with patch(
        "custom_components.solar_surplus.config_flow.async_preferences",
        return_value=prefs,
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert CONF_GRID_POWER not in result["data"], "it is read when set up"
