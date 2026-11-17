"""Shared fixtures: a configured hub over a faked house."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from freezegun import freeze_time
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.solar_surplus.const import (
    CONF_ADAPTER,
    CONF_GRID_POWER,
    CONF_MIN_OFF_TIME,
    CONF_MIN_ON_TIME,
    CONF_NAME,
    CONF_OFF_DELAY,
    CONF_ON_DELAY,
    CONF_POWER,
    CONF_SWITCH_ENTITY,
    DOMAIN,
    SUBENTRY_TYPE_CONSUMER,
    TITLE,
    AdapterType,
)

pytest_plugins = "pytest_homeassistant_custom_component"

GRID = "sensor.grid"
HEATING_ROD = "input_boolean.heating_rod"

HUB_DATA: dict[str, Any] = {CONF_GRID_POWER: GRID}

HEATING_ROD_DATA: dict[str, Any] = {
    CONF_NAME: "Heating rod",
    CONF_ADAPTER: AdapterType.SWITCH.value,
    CONF_POWER: 2000,
    CONF_SWITCH_ENTITY: HEATING_ROD,
    CONF_MIN_ON_TIME: 0,
    CONF_MIN_OFF_TIME: 0,
    CONF_ON_DELAY: 0,
    CONF_OFF_DELAY: 0,
}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Make the custom integration loadable in every test."""
    return


@pytest.fixture(autouse=True)
def midday() -> Iterator[None]:
    """Start the clock at a summer noon in the test time zone (US/Pacific).

    Deadlines are times of day, so a suite run in the evening would find every
    washing machine past its deadline. The clock keeps ticking, since a frozen
    one stalls the event loop. A test that needs another time moves it itself.
    """
    with freeze_time("2026-06-15 12:00:00-07:00", tick=True):
        yield


def consumer(data: dict[str, Any], title: str | None = None) -> ConfigSubentryData:
    """A consumer subentry, for `MockConfigEntry(subentries_data=...)`."""
    return ConfigSubentryData(
        data=data,
        subentry_type=SUBENTRY_TYPE_CONSUMER,
        title=title or data[CONF_NAME],
        unique_id=None,
    )


#: The fake devices: helpers, so a service call really changes their state.
BOOLEANS = (
    "heating_rod",
    "pool_pump",
    "sg_1",
    "sg_2",
    "washer_ready",
    "washer_plug",
    "ac",
)


@pytest.fixture
async def devices(hass: HomeAssistant) -> None:
    """Helpers that stand in for the devices, with a grid meter exporting nothing."""
    assert await async_setup_component(
        hass, "input_boolean", {"input_boolean": {name: {} for name in BOOLEANS}}
    )
    assert await async_setup_component(
        hass,
        "input_number",
        {
            "input_number": {
                "wallbox": {
                    "min": 0,
                    "max": 3000,
                    "step": 100,
                    "unit_of_measurement": "W",
                }
            }
        },
    )
    assert await async_setup_component(
        hass,
        "script",
        {
            "script": {
                "ac_on": {
                    "sequence": [
                        {
                            "action": "input_boolean.turn_on",
                            "target": {"entity_id": "input_boolean.ac"},
                        }
                    ]
                },
                "ac_off": {
                    "sequence": [
                        {
                            "action": "input_boolean.turn_off",
                            "target": {"entity_id": "input_boolean.ac"},
                        }
                    ]
                },
            }
        },
    )
    grid(hass, 0)


def grid(hass: HomeAssistant, watts: float, unit: str = "W") -> None:
    """Set the grid meter: positive draws from the grid."""
    hass.states.async_set(
        GRID, str(watts), {"unit_of_measurement": unit, "device_class": "power"}
    )


@pytest.fixture
def setup_entry(hass: HomeAssistant, devices):
    """Set an entry up over the fake devices, and return its coordinator."""

    async def _setup(mock_entry: MockConfigEntry):
        assert await hass.config_entries.async_setup(mock_entry.entry_id)
        await hass.async_block_till_done()
        return mock_entry.runtime_data

    return _setup


def hub(*consumers: dict[str, Any], **data: Any) -> MockConfigEntry:
    """A hub entry with the given consumers, not yet added."""
    return MockConfigEntry(
        domain=DOMAIN,
        title=TITLE,
        data={**HUB_DATA, **data},
        subentries_data=[consumer(c) for c in consumers],
    )


@pytest.fixture
def entry(hass: HomeAssistant) -> MockConfigEntry:
    """A hub with one heating rod."""
    mock_entry = MockConfigEntry(
        domain=DOMAIN,
        title=TITLE,
        data=HUB_DATA,
        subentries_data=[consumer(HEATING_ROD_DATA)],
    )
    mock_entry.add_to_hass(hass)
    return mock_entry
