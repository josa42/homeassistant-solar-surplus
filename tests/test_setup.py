"""Setting the integration up and taking it down again."""

from __future__ import annotations

import re
from pathlib import Path

from homeassistant.components import frontend
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.solar_surplus.const import PANEL_URL_PATH, PANEL_VERSION

PANEL_JS = Path("custom_components/solar_surplus/www/solar-surplus-panel.js")


async def test_setup_adds_the_panel(
    hass: HomeAssistant, setup_entry, entry: MockConfigEntry
) -> None:
    await setup_entry(entry)
    assert frontend.async_panel_exists(hass, PANEL_URL_PATH)
    panel = hass.data[frontend.DATA_PANELS][PANEL_URL_PATH]
    assert panel.sidebar_title == "Solar Surplus"
    assert panel.config["_panel_custom"]["module_url"].endswith(f"?v={PANEL_VERSION}")


async def test_unloading_removes_the_panel(
    hass: HomeAssistant, setup_entry, entry: MockConfigEntry
) -> None:
    await setup_entry(entry)
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert not frontend.async_panel_exists(hass, PANEL_URL_PATH)


async def test_a_reload_keeps_the_panel(
    hass: HomeAssistant, setup_entry, entry: MockConfigEntry
) -> None:
    await setup_entry(entry)
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert frontend.async_panel_exists(hass, PANEL_URL_PATH)


async def test_the_panel_is_served(
    hass: HomeAssistant, setup_entry, entry: MockConfigEntry, hass_client
) -> None:
    await setup_entry(entry)
    client = await hass_client()
    response = await client.get("/solar_surplus/solar-surplus-panel.js")
    assert response.status == 200
    assert "solar-surplus-panel" in await response.text()


def test_the_panel_and_the_integration_agree_on_the_version() -> None:
    match = re.search(
        r'const PANEL_VERSION = "([^"]+)"', PANEL_JS.read_text(encoding="utf-8")
    )
    assert match and match.group(1) == PANEL_VERSION
