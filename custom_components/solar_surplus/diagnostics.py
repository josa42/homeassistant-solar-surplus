"""Diagnostics: the configuration, what is remembered, and the last decision."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from .coordinator import SolarSurplusConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: SolarSurplusConfigEntry
) -> dict[str, Any]:
    """Everything needed to tell why a consumer did what it did."""
    coordinator = entry.runtime_data
    decision = coordinator.data
    return {
        "config": {**entry.data, **entry.options},
        "consumers": {
            subentry_id: {"title": subentry.title, **subentry.data}
            for subentry_id, subentry in entry.subentries.items()
        },
        "control_enabled": coordinator.control_enabled,
        "test_mode": coordinator.test_mode,
        "store": {
            "order": coordinator.store.order,
            "overrides": {
                key: value.value for key, value in coordinator.store.overrides.items()
            },
            "memories": coordinator.store.memories,
        },
        "base_load_hours": coordinator.base_load.hours,
        "decision": decision.to_dict() if decision else None,
    }
