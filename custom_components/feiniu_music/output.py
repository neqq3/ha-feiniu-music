"""Fixed HA output identity, standard actions and integration-local ownership."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.media_player import MediaPlayerEntityFeature as Feature
from homeassistant.core import Context, Event, EventStateChangedData, HomeAssistant, State, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_track_state_change_event

from .const import DOMAIN
from .support import private_id, safe_state

_LOGGER = logging.getLogger(__name__)


class OutputValidationError(ServiceValidationError):
    """A controlled translation key, without an entity name or exception payload."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class OutputBinding:
    """Registry UUID is stable through rename; unregistered entities explicitly are not."""

    key: str
    entity_id: str

    @classmethod
    def from_entity(cls, hass: HomeAssistant, entity_id: str) -> OutputBinding:
        if not entity_id.startswith("media_player."):
            _LOGGER.debug(
                "Output selection ref=%s reason=output_not_media_player", private_id(entity_id)
            )
            raise OutputValidationError("output_not_media_player")
        entry = er.async_get(hass).async_get(entity_id)
        if entry and entry.platform == DOMAIN:
            _LOGGER.debug("Output selection ref=%s reason=output_self", private_id(entity_id))
            raise OutputValidationError("output_self")
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
    """Report classified validation with privacy-safe context, retaining existing offline bindings."""
    try:
        _validate_output(hass, binding, existing=existing)
    except OutputValidationError as err:
        _LOGGER.debug(
            "Output validation existing=%s reason=%s context=%s",
            existing,
            err.reason,
            output_info(hass, binding),
        )
        raise
    _LOGGER.debug(
        "Output validation existing=%s reason=accepted context=%s",
        existing,
        output_info(hass, binding),
    )


def _validate_output(hass: HomeAssistant, binding: OutputBinding, *, existing: bool) -> None:
    """Reject known self/group wrapper cycles, without claiming physical-device deduplication."""
    entity_id = binding.resolve(hass)
    if entity_id is None:
        if existing:
            return
        raise OutputValidationError("output_missing_registry")
    if not entity_id.startswith("media_player."):
        raise OutputValidationError("output_not_media_player")
    visited: set[str] = set()

    def walk(candidate: str) -> None:
        if candidate in visited:
            raise OutputValidationError("output_wrapper_loop")
        visited.add(candidate)
        entry = er.async_get(hass).async_get(candidate)
        state = hass.states.get(candidate)
        if (entry and entry.platform == DOMAIN) or (state and state.attributes.get("feiniu_queue")):
            raise OutputValidationError(
                "output_self" if candidate == entity_id else "output_wrapped_feiniu"
            )
        # HA groups expose member entity IDs. Unknown third-party wrappers may not.
        children = state.attributes.get("entity_id") if state else None
        if isinstance(children, list):
            for child in children:
                if isinstance(child, str) and child.startswith("media_player."):
                    walk(child)
        visited.remove(candidate)

    walk(entity_id)
    state = hass.states.get(entity_id)
    if state is None or state.state in {"unavailable", "unknown"}:
        if existing:
            return
        raise OutputValidationError("output_unavailable")
    flags = state.attributes.get("supported_features", 0) if state else 0
    if not isinstance(flags, int) or isinstance(flags, bool) or not flags & Feature.PLAY_MEDIA:
        raise OutputValidationError("output_no_play_media")


def output_info(hass: HomeAssistant, binding: OutputBinding) -> dict[str, Any]:
    """Allowlisted shared context. Actual entity IDs never enter log arguments."""
    entity_id = binding.resolve(hass)
    registered = er.async_get(hass).async_get(entity_id) if entity_id else None
    state = hass.states.get(entity_id) if entity_id else None
    raw = state.attributes.get("supported_features", 0) if state else 0
    flags = raw if isinstance(raw, int) and not isinstance(raw, bool) else 0
    device_class = state.attributes.get("device_class") if state else None
    return {
        "binding": "registry" if binding.key.startswith("registry:") else "entity_id",
        "binding_ref": private_id(binding.key),
        "saved_entity_ref": private_id(binding.entity_id),
        "resolved_entity_ref": private_id(entity_id),
        "resolved": entity_id is not None,
        "renamed": entity_id is not None and entity_id != binding.entity_id,
        "registry_exists": registered is not None,
        "registry_disabled": registered.disabled_by is not None if registered else None,
        "platform": registered.platform if registered else None,
        "state": safe_state(state.state if state else None),
        "available": state is not None and state.state not in {"unavailable", "unknown"},
        "device_class": device_class
        if device_class is None
        or (isinstance(device_class, str) and device_class in {"speaker", "tv", "receiver"})
        else "other",
        "supported_features": flags,
        "features": {
            feature.name: bool(flags & feature)
            for feature in (
                Feature.PLAY_MEDIA,
                Feature.PLAY,
                Feature.PAUSE,
                Feature.STOP,
                Feature.SEEK,
                Feature.VOLUME_SET,
                Feature.VOLUME_MUTE,
            )
        },
    }


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
        # Dynamic capabilities (e.g. DLNA Pause disappearing at track end) do not
        # change the binding. Resubscribing here loses the pending state transition.
        if event.data["action"] == "update" and "entity_id" not in event.data["changes"]:
            return
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
