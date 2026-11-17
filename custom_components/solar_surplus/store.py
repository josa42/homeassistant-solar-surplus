"""What the panel changes, and what a run has to survive a restart.

The priority order and the hands on consumers are not configuration in the
config entry sense: they change in daily life, from the panel or a select, and
should not reload anything. They live here, next to the parts of the engine's
memory a restart must not lose, such as a washing machine halfway through.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.storage import Store

from .const import SIGNAL_ID, STORAGE_KEY, STORAGE_VERSION, Override

#: Saving is delayed, so a burst of changes is written once.
SAVE_DELAY = 5


class SolarSurplusStore:
    """The priority order, the overrides, and the remembered runs."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._listeners: list[Callable[[], None]] = []
        self.order: list[str] = []
        self.overrides: dict[str, Override] = {}
        self.memories: dict[str, dict[str, Any]] = {}

    async def async_load(self, consumer_ids: Iterable[str]) -> None:
        """Read what was stored, and forget consumers that no longer exist."""
        raw = await self._store.async_load() or {}
        known = set(consumer_ids)
        order = raw.get("order")
        self.order = (
            [item for item in order if item in known or item == SIGNAL_ID]
            if isinstance(order, list)
            else []
        )
        self.overrides = {}
        for consumer_id, value in (raw.get("overrides") or {}).items():
            if consumer_id in known:
                try:
                    self.overrides[consumer_id] = Override(value)
                except ValueError:
                    continue
        memories = raw.get("memories") or {}
        self.memories = {
            key: value
            for key, value in memories.items()
            if key in known and isinstance(value, dict)
        }

    def _data(self) -> dict[str, Any]:
        return {
            "order": self.order,
            "overrides": {
                key: value.value
                for key, value in self.overrides.items()
                if value is not Override.AUTO
            },
            "memories": self.memories,
        }

    @callback
    def async_schedule_save(self) -> None:
        self._store.async_delay_save(self._data, SAVE_DELAY)

    async def async_save(self) -> None:
        await self._store.async_save(self._data())

    @callback
    def async_add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Call `listener` when the order or an override changes."""
        self._listeners.append(listener)

        @callback
        def remove() -> None:
            self._listeners.remove(listener)

        return remove

    @callback
    def _changed(self) -> None:
        self.async_schedule_save()
        for listener in list(self._listeners):
            listener()

    @callback
    def async_set_order(self, order: list[str]) -> None:
        self.order = list(dict.fromkeys(order))
        self._changed()

    @callback
    def async_set_override(self, consumer_id: str, override: Override) -> None:
        if self.overrides.get(consumer_id, Override.AUTO) is override:
            return
        self.overrides[consumer_id] = override
        self._changed()

    def override(self, consumer_id: str) -> Override:
        return self.overrides.get(consumer_id, Override.AUTO)

    @callback
    def async_set_memories(self, memories: dict[str, dict[str, Any]]) -> None:
        """Keep the engine's memory, saved only when it changed."""
        if memories != self.memories:
            self.memories = memories
            self.async_schedule_save()
