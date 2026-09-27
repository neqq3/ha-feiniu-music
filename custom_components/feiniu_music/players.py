"""Account lifecycle for fixed outputs, incremental options and persistent queues."""

from __future__ import annotations

import asyncio
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .media_player import FeiNiuPlayer
from .output import OutputBinding, OutputLeases, validate_output
from .queue import QueueModel
from .runtime import FeiNiuConfigEntry
from .session import OutputProfile
from .storage import QueueStorage, SavedSession

CONF_OUTPUTS = "outputs"
CONF_LEGACY = "legacy_output_key"


def bindings(options: dict[str, Any]) -> dict[str, OutputBinding]:
    """Options contain entity-level identities, not mutable names or device IDs."""
    return {item.key: item for item in map(OutputBinding.restore, options.get(CONF_OUTPUTS, []))}


def migrate_options(hass: HomeAssistant, entry: FeiNiuConfigEntry) -> dict[str, Any]:
    """Preserve the one old entity's unique ID only on its explicitly saved output."""
    options = dict(entry.options)
    if CONF_OUTPUTS not in options:
        old = options.get("output_player")
        options[CONF_OUTPUTS] = []
        if isinstance(old, str) and old.startswith("media_player."):
            try:
                binding = OutputBinding.from_entity(hass, old)
                validate_output(hass, binding, existing=True)
            except HomeAssistantError, ValueError:
                binding = None
            if binding:
                options[CONF_OUTPUTS] = [binding.snapshot()]
                options[CONF_LEGACY] = binding.key
        options.pop("output_player", None)
    return options


class AccountPlayers:
    """One account's selected sessions; removing one output leaves the others intact."""

    def __init__(
        self, hass: HomeAssistant, entry: FeiNiuConfigEntry, add_entities: AddEntitiesCallback
    ) -> None:
        self.hass, self.entry, self.add_entities = hass, entry, add_entities
        self.storage = QueueStorage(hass, entry.entry_id)
        self.restored: dict[str, SavedSession] = {}
        self.entities: dict[str, FeiNiuPlayer] = {}
        self.leases = hass.data[DOMAIN].setdefault("leases", OutputLeases())
        self._options_lock = asyncio.Lock()
        self.closed = False

    async def setup(self) -> None:
        self.restored = await self.storage.load()
        if self.storage.corrupt:
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                f"queue_storage_{self.entry.entry_id}",
                is_fixable=False,
                severity=ir.IssueSeverity.ERROR,
                translation_key="queue_storage",
            )
        await self.update(self.hass, self.entry)
        self.entry.async_on_unload(self.entry.add_update_listener(self.update))

    def persist(self, saved: SavedSession) -> None:
        if not self.storage.corrupt:
            self.storage.stage(saved)

    async def update(self, hass: HomeAssistant, entry: FeiNiuConfigEntry) -> None:
        async with self._options_lock:
            if self.closed:
                return
            selected = bindings(dict(entry.options))
            issue = f"select_outputs_{entry.entry_id}"
            if selected:
                ir.async_delete_issue(hass, DOMAIN, issue)
            else:
                ir.async_create_issue(
                    hass,
                    DOMAIN,
                    issue,
                    is_fixable=False,
                    severity=ir.IssueSeverity.WARNING,
                    translation_key="select_outputs",
                )
            for key in set(self.entities) - selected.keys():
                entity = self.entities.pop(key)
                self.restored[key] = entity.saved
                if entity.session is not None:
                    await entity.async_remove()
            new = []
            for key, binding in selected.items():
                if key in self.entities:
                    continue
                validate_output(hass, binding, existing=True)
                saved = self.restored.get(key) or SavedSession(
                    binding, QueueModel(), OutputProfile()
                )
                entity = FeiNiuPlayer(
                    entry.runtime_data,
                    saved,
                    self.leases,
                    self.persist,
                    legacy=key == entry.options.get(CONF_LEGACY),
                )
                self.entities[key] = entity
                new.append(entity)
            if new:
                self.add_entities(new)
            await self.storage.flush()

    async def close(self) -> None:
        self.closed = True
        for entity in self.entities.values():
            if entity.session is not None:
                await entity.async_will_remove_from_hass()
        await self.storage.flush()
