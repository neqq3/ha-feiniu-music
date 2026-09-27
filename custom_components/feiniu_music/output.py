"""Fixed HA output identity, standard actions and integration-local ownership."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.media_player import MediaPlayerEntityFeature as Feature
from homeassistant.core import Context, Event, EventStateChangedData, HomeAssistant, State, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_track_state_change_event

from .const import DOMAIN


@dataclass(frozen=True, slots=True)
class OutputBinding:
    """Registry UUID is stable through rename; unregistered entities explicitly are not."""

    key: str
    entity_id: str

    @classmethod
    def from_entity(cls, hass: HomeAssistant, entity_id: str) -> OutputBinding:
        if not entity_id.startswith("media_player."):
            raise ServiceValidationError("Choose a media player output")
        entry = er.async_get(hass).async_get(entity_id)
        if entry and entry.platform == DOMAIN:
            raise ServiceValidationError("A FeiNiu player cannot be its own output")
        return cls(f"registry:{entry.id}" if entry else f"entity:{entity_id}", entity_id)

    def resolve(self, hass: HomeAssistant) -> str | None:
        if self.key.startswith("registry:"):
            entry = er.async_get(hass).async_get(self.key.removeprefix("registry:"))
            return entry.entity_id if entry else None
        # No guessing by friendly name, device, IP or the next available speaker.
        return self.entity_id if self.key == f"entity:{self.entity_id}" else None

    def snapshot(self) -> dict[str, str]:
        return {"key": self.key, "entity_id": self.entity_id}

    @classmethod
    def restore(cls, data: Any) -> OutputBinding:
        if (
            not isinstance(data, dict)
            or not isinstance(data.get("key"), str)
            or not isinstance(data.get("entity_id"), str)
            or not data["entity_id"].startswith("media_player.")
            or not data["key"].startswith(("registry:", "entity:"))
        ):
            raise ValueError("Invalid saved output binding")
        return cls(data["key"], data["entity_id"])


def validate_output(hass: HomeAssistant, binding: OutputBinding, *, existing: bool = False) -> None:
    """Reject known self/group wrapper cycles, without claiming physical-device deduplication."""
    entity_id = binding.resolve(hass)
    if entity_id is None:
        if existing:
            return
        raise ServiceValidationError("Output registry entry is missing")
    visited: set[str] = set()

    def walk(candidate: str) -> None:
        if candidate in visited:
            raise ServiceValidationError("Output contains a wrapper loop")
        visited.add(candidate)
        entry = er.async_get(hass).async_get(candidate)
        state = hass.states.get(candidate)
        if (entry and entry.platform == DOMAIN) or (state and state.attributes.get("feiniu_queue")):
            raise ServiceValidationError("FeiNiu players cannot be used as wrapped outputs")
        # HA groups expose member entity IDs. Unknown third-party wrappers may not.
        children = state.attributes.get("entity_id") if state else None
        if isinstance(children, list):
            for child in children:
                if isinstance(child, str) and child.startswith("media_player."):
                    walk(child)
        visited.remove(candidate)

    walk(entity_id)
    state = hass.states.get(entity_id)
    if existing and (state is None or state.state in {"unavailable", "unknown"}):
        return
    flags = state.attributes.get("supported_features", 0) if state else 0
    if not isinstance(flags, int) or isinstance(flags, bool) or not flags & Feature.PLAY_MEDIA:
        raise ServiceValidationError("Output does not advertise PLAY_MEDIA")


class OutputLeases:
    """Coordinate only FeiNiu sessions, not external apps or physical speaker aliases."""

    def __init__(self) -> None:
        self._owners: dict[str, tuple[object, Callable[[], None]]] = {}

    def claim(self, key: str, owner: object, displaced: Callable[[], None]) -> None:
        previous = self._owners.get(key)
        self._owners[key] = (owner, displaced)
        if previous is not None and previous[0] is not owner:
            previous[1]()

    def owns(self, key: str, owner: object) -> bool:
        current = self._owners.get(key)
        return current is not None and current[0] is owner

    def release(self, key: str, owner: object) -> None:
        if self.owns(key, owner):
            self._owners.pop(key)


class OutputAdapter:
    """Subscribe to every observation; commands use HA's supported public services."""

    def __init__(self, hass: HomeAssistant, binding: OutputBinding) -> None:
        self.hass = hass
        self.binding = binding
        self._listener: Callable[[State | None, State | None], None] | None = None
        self._unsub_state: Callable[[], None] | None = None
        self._unsub_registry: Callable[[], None] | None = None
        self._watched_entity_id: str | None = None

    @property
    def entity_id(self) -> str | None:
        return self.binding.resolve(self.hass)

    @property
    def state(self) -> State | None:
        entity_id = self.entity_id
        return self.hass.states.get(entity_id) if entity_id else None

    @property
    def features(self) -> Feature:
        state = self.state
        value = state.attributes.get("supported_features", 0) if state else 0
        return (
            Feature(value) if isinstance(value, int) and not isinstance(value, bool) else Feature(0)
        )

    @property
    def available(self) -> bool:
        return self.state is not None and self.state.state not in {"unavailable", "unknown"}

    def subscribe(self, listener: Callable[[State | None, State | None], None]) -> None:
        self.close()
        self._listener = listener
        self._listen_state()
        self._unsub_registry = self.hass.bus.async_listen(
            er.EVENT_ENTITY_REGISTRY_UPDATED, self._registry_changed
        )

    def _listen_state(self) -> None:
        if self._unsub_state:
            self._unsub_state()
            self._unsub_state = None
        self._watched_entity_id = self.entity_id
        if entity_id := self._watched_entity_id:
            self._unsub_state = async_track_state_change_event(
                self.hass, [entity_id], self._state_changed
            )

    @callback
    def _registry_changed(self, event: Event[er.EventEntityRegistryUpdatedData]) -> None:
        # Registry rename events carry the new entity_id and changes with its old value.
        candidates = {
            event.data.get("entity_id"),
            event.data["changes"].get("entity_id") if event.data["action"] == "update" else None,
        }
        if self._watched_entity_id in candidates or self.entity_id in candidates:
            self._listen_state()
            if self._listener:
                self._listener(None, self.state)

    @callback
    def _state_changed(self, event: Event[EventStateChangedData]) -> None:
        if self._listener:
            self._listener(event.data.get("old_state"), event.data.get("new_state"))

    async def send(
        self, service: str, data: dict[str, Any] | None = None, *, context: Context | None = None
    ) -> None:
        if not self.available:
            raise ServiceValidationError("Output is offline or its binding is missing")
        await self.hass.services.async_call(
            "media_player",
            service,
            {"entity_id": self.entity_id, **(data or {})},
            blocking=True,
            context=context,
        )

    def close(self) -> None:
        if self._unsub_state:
            self._unsub_state()
        if self._unsub_registry:
            self._unsub_registry()
        self._unsub_state = self._unsub_registry = None
        self._listener = None
