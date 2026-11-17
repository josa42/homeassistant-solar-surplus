"""Shared fixtures: a configured hub over a faked house."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from freezegun import freeze_time
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import HomeAssistant
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
HEATING_ROD = "switch.heating_rod"

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
