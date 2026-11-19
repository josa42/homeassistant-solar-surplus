"""The Solar Surplus integration."""

from __future__ import annotations

from pathlib import Path

from homeassistant.components import frontend, panel_custom
from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from . import websocket_api
from .const import (
    CARDS_ASSET_URL,
    DOMAIN,
    PANEL_ASSET_URL,
    PANEL_COMPONENT_NAME,
    PANEL_ICON,
    PANEL_TITLE,
    PANEL_URL_PATH,
    PANEL_VERSION,
)
from .coordinator import SolarSurplusConfigEntry, SolarSurplusCoordinator
from .energy_dashboard import async_preferences, hub_values
from .store import SolarSurplusStore

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

PLATFORMS: list[Platform] = [Platform.SELECT, Platform.SENSOR, Platform.SWITCH]

#: Whether the session already listens to the energy dashboard.
DASHBOARD_LISTENER = f"{DOMAIN}_energy_dashboard_listener"


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the websocket API, serve the panel and load the cards.

    Once per session.
    """
    websocket_api.async_register(hass)
    if hass.http is None:
        return True
    www = Path(__file__).parent / "www"
    await hass.http.async_register_static_paths(
        [
            StaticPathConfig(
                PANEL_ASSET_URL, str(www / "solar-surplus-panel.js"), cache_headers=False
            ),
            StaticPathConfig(
                CARDS_ASSET_URL, str(www / "solar-surplus-cards.js"), cache_headers=False
            ),
        ]
    )
    # The version is the cache-buster, as for the panel.
    add_extra_js_url(hass, f"{CARDS_ASSET_URL}?v={PANEL_VERSION}")
    return True


async def async_setup_entry(
    hass: HomeAssistant, entry: SolarSurplusConfigEntry
) -> bool:
    """Set up Solar Surplus from a config entry."""
    store = SolarSurplusStore(hass)
    await store.async_load(entry.subentries)
    dashboard = hub_values(await async_preferences(hass))
    coordinator = SolarSurplusCoordinator(hass, entry, store, dashboard)
    entry.runtime_data = coordinator
    coordinator.async_register_hub_device()
    await coordinator.async_config_entry_first_refresh()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    coordinator.async_start_watching()
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    await _async_follow_energy_dashboard(hass)
    await _async_register_panel(hass)
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: SolarSurplusConfigEntry
) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.async_shutdown()
        if frontend.async_panel_exists(hass, PANEL_URL_PATH):
            frontend.async_remove_panel(hass, PANEL_URL_PATH)
    return unloaded


async def _async_reload(hass: HomeAssistant, entry: SolarSurplusConfigEntry) -> None:
    """Reload when the options or the consumers change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def _async_follow_energy_dashboard(hass: HomeAssistant) -> None:
    """Reload when the energy dashboard changes what the hub takes from it.

    Its listeners cannot be removed again, so there is one for the session,
    and it finds the entry when it is called.
    """
    if hass.data.get(DASHBOARD_LISTENER) or "energy" not in hass.config.components:
        return
    from homeassistant.components.energy.data import (  # noqa: PLC0415
        async_get_manager,
    )

    async def _changed() -> None:
        dashboard = hub_values(await async_preferences(hass))
        for entry in hass.config_entries.async_loaded_entries(DOMAIN):
            if entry.runtime_data.dashboard != dashboard:
                hass.config_entries.async_schedule_reload(entry.entry_id)

    (await async_get_manager(hass)).async_listen_updates(_changed)
    hass.data[DASHBOARD_LISTENER] = True


async def _async_register_panel(hass: HomeAssistant) -> None:
    """Add the panel to the sidebar, unless it is there already."""
    if hass.http is None or frontend.async_panel_exists(hass, PANEL_URL_PATH):
        return
    language = (hass.config.language or "en").split("-")[0]
    await panel_custom.async_register_panel(
        hass,
        frontend_url_path=PANEL_URL_PATH,
        webcomponent_name=PANEL_COMPONENT_NAME,
        # The version is the cache-buster; bump PANEL_VERSION in const.py and in
        # the JS together.
        module_url=f"{PANEL_ASSET_URL}?v={PANEL_VERSION}",
        sidebar_title=PANEL_TITLE.get(language, PANEL_TITLE["en"]),
        sidebar_icon=PANEL_ICON,
        require_admin=False,
        embed_iframe=False,
    )
