"""Diagnostics carry what is needed to tell why a consumer did what it did."""

from __future__ import annotations

import json

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.solar_surplus.diagnostics import (
    async_get_config_entry_diagnostics,
)

from .conftest import GRID, grid


async def test_diagnostics(
    hass: HomeAssistant, setup_entry, entry: MockConfigEntry
) -> None:
    grid(hass, -3000)
    await setup_entry(entry)
    rod = next(iter(entry.subentries))

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)

    assert json.loads(json.dumps(diagnostics)) == diagnostics, "it serializes as it is"
    assert diagnostics["config"]["grid_power"] == GRID
    assert diagnostics["consumers"][rod]["title"] == "Heating rod"
    assert diagnostics["control_enabled"] is True
    assert diagnostics["decision"]["consumers"][0]["reason"] == "surplus"
    assert diagnostics["store"]["order"] == []
