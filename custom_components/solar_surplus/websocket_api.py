"""The websocket API the panel talks to.

One subscription pushes every run; the rest are writes, for admins only. The
subscription follows the integration through a reload, since adding a consumer
reloads the entry and makes a new coordinator.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from functools import wraps
from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .const import DOMAIN, AdapterType, Override
from .coordinator import SIGNAL_UPDATE, SolarSurplusCoordinator


class NotLoaded(Exception):
    """Solar Surplus is not set up."""


def _coordinator(hass: HomeAssistant) -> SolarSurplusCoordinator:
    entries = hass.config_entries.async_loaded_entries(DOMAIN)
    if not entries:
        raise NotLoaded("Solar Surplus is not set up")
    return entries[0].runtime_data


def panel_state(coordinator: SolarSurplusCoordinator) -> dict[str, Any]:
    """Everything the panel shows."""
    settings = coordinator.settings
    decision = coordinator.data
    registry = er.async_get(coordinator.hass)

    def entity_id(consumer_id: str, key: str) -> str | None:
        return registry.async_get_entity_id("sensor", DOMAIN, f"{consumer_id}_{key}")

    return {
        "decision": decision.to_dict() if decision else None,
        "control_enabled": coordinator.control_enabled,
        "test_mode": coordinator.test_mode,
        "has_forecast": coordinator.forecast.configured,
        "consumers": {
            consumer_id: {
                "title": consumer.title,
                "adapter": consumer.spec.adapter.value,
                "power": consumer.spec.power,
                "override": coordinator.store.override(consumer_id).value,
                # For the panel to read the past from the history.
                "status_entity": entity_id(consumer_id, "status"),
                "signal_entity": entity_id(consumer_id, "energy_signal")
                if consumer.spec.adapter is AdapterType.SIGNAL
                else None,
            }
            for consumer_id, consumer in coordinator.consumers.items()
        },
        "settings": {
            "reserve": settings.reserve,
            "base_load": settings.base_load,
        },
    }


def _with_coordinator(
    handler: Callable[
        [HomeAssistant, websocket_api.ActiveConnection, dict, SolarSurplusCoordinator],
        Awaitable[None],
    ],
):
    @wraps(handler)
    async def wrapper(
        hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict
    ) -> None:
        try:
            coordinator = _coordinator(hass)
        except NotLoaded as err:
            connection.send_error(msg["id"], websocket_api.ERR_NOT_FOUND, str(err))
            return
        await handler(hass, connection, msg, coordinator)

    return wrapper


@callback
def async_register(hass: HomeAssistant) -> None:
    """Register the commands. Once per session."""
    for handler in (
        handle_subscribe,
        handle_reorder,
        handle_set_override,
        handle_set_control,
        handle_set_test_mode,
    ):
        websocket_api.async_register_command(hass, handler)


@websocket_api.websocket_command({vol.Required("type"): "solar_surplus/subscribe"})
@callback
def handle_subscribe(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict
) -> None:
    """Push the state now and after every run."""
    try:
        _coordinator(hass)
    except NotLoaded as err:
        connection.send_error(msg["id"], websocket_api.ERR_NOT_FOUND, str(err))
        return

    @callback
    def forward() -> None:
        try:
            state = panel_state(_coordinator(hass))
        except NotLoaded:
            return
        connection.send_message(websocket_api.event_message(msg["id"], state))

    connection.subscriptions[msg["id"]] = async_dispatcher_connect(
        hass, SIGNAL_UPDATE, forward
    )
    connection.send_result(msg["id"])
    forward()


@websocket_api.websocket_command(
    {
        vol.Required("type"): "solar_surplus/reorder",
        vol.Required("order"): [str],
    }
)
@websocket_api.require_admin
@websocket_api.async_response
@_with_coordinator
async def handle_reorder(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
    coordinator: SolarSurplusCoordinator,
) -> None:
    """Set the priority order: consumer ids, first first."""
    known = set(coordinator.consumers)
    unknown = [item for item in msg["order"] if item not in known]
    if unknown:
        connection.send_error(
            msg["id"],
            websocket_api.ERR_INVALID_FORMAT,
            f"Unknown: {', '.join(unknown)}",
        )
        return
    coordinator.store.async_set_order(msg["order"])
    await coordinator.async_refresh()
    connection.send_result(msg["id"], panel_state(coordinator))


@websocket_api.websocket_command(
    {
        vol.Required("type"): "solar_surplus/set_override",
        vol.Required("consumer_id"): str,
        vol.Required("override"): vol.In([override.value for override in Override]),
    }
)
@websocket_api.require_admin
@websocket_api.async_response
@_with_coordinator
async def handle_set_override(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
    coordinator: SolarSurplusCoordinator,
) -> None:
    """Put a hand on a consumer, or take it off."""
    if msg["consumer_id"] not in coordinator.consumers:
        connection.send_error(
            msg["id"], websocket_api.ERR_NOT_FOUND, "Unknown consumer"
        )
        return
    coordinator.store.async_set_override(msg["consumer_id"], Override(msg["override"]))
    await coordinator.async_refresh()
    connection.send_result(msg["id"], panel_state(coordinator))


@websocket_api.websocket_command(
    {
        vol.Required("type"): "solar_surplus/set_control",
        vol.Required("enabled"): bool,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
@_with_coordinator
async def handle_set_control(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
    coordinator: SolarSurplusCoordinator,
) -> None:
    """Let the allocation write, or only show what it would do."""
    await coordinator.async_set_control_now(msg["enabled"])
    connection.send_result(msg["id"], panel_state(coordinator))


@websocket_api.websocket_command(
    {
        vol.Required("type"): "solar_surplus/set_test_mode",
        vol.Required("enabled"): bool,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
@_with_coordinator
async def handle_set_test_mode(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
    coordinator: SolarSurplusCoordinator,
) -> None:
    """Only send notifications of what would be switched, or switch again."""
    await coordinator.async_set_test_mode_now(msg["enabled"])
    connection.send_result(msg["id"], panel_state(coordinator))
