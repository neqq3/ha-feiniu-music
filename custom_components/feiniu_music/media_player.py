"""Account-local queues which play through existing Home Assistant media players."""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Callable
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

from homeassistant.components.media_player import (
    BrowseMedia,
    MediaPlayerEntity,
    MediaPlayerState,
    MediaType,
    RepeatMode,
    SearchMedia,
    SearchMediaQuery,
)
from homeassistant.components.media_player import (
    MediaPlayerEntityFeature as Feature,
)
from homeassistant.components.media_source import MediaSourceItem
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, State, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.util import dt as dt_util

from .client import FeiNiuError
from .const import DOMAIN
from .media import valid_id
from .media_source import FeiNiuMediaSource
from .runtime import FeiNiuConfigEntry, FeiNiuRuntime

_LOGGER = logging.getLogger(__name__)
CONF_OUTPUT = "output_player"
_BASE_FEATURES = (
    Feature.PLAY_MEDIA
    | Feature.BROWSE_MEDIA
    | Feature.SEARCH_MEDIA
    | Feature.SELECT_SOURCE
    | Feature.MEDIA_ENQUEUE
    | Feature.PLAY
    | Feature.STOP
    | Feature.CLEAR_PLAYLIST
    | Feature.NEXT_TRACK
    | Feature.PREVIOUS_TRACK
    | Feature.REPEAT_SET
    | Feature.SHUFFLE_SET
)


async def async_setup_entry(
    hass: HomeAssistant, entry: FeiNiuConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Create one queue controller per music account; output selection never autoplays."""
    async_add_entities([FeiNiuPlayer(entry.runtime_data)])


class FeiNiuPlayer(MediaPlayerEntity):
    """Own queue order and metadata, while the selected entity owns device control."""

    _attr_should_poll = False
    _attr_icon = "mdi:music-circle"
    _attr_media_content_type = MediaType.MUSIC

    def __init__(self, runtime: FeiNiuRuntime) -> None:
        self.runtime = runtime
        self._attr_unique_id = f"{runtime.entry.entry_id}_player"
        self._attr_name = runtime.entry.title
        self._attr_state = MediaPlayerState.IDLE
        self._attr_repeat = RepeatMode.OFF
        self._attr_shuffle = False
        self._output: str | None = runtime.entry.options.get(CONF_OUTPUT)
        self._queue: list[str] = []
        self._order: list[int] = []
        self._position = 0
        self._expected_url: str | None = None
        self._active = False
        self._seen_playing = False
        self._playback_ready = asyncio.Event()
        self._changing = False
        self._generation = 0
        self._lock = asyncio.Lock()
        self._unsubscribe: Callable[[], None] | None = None
        self._advance_task: asyncio.Task | None = None
        self._last_error: str | None = None

    async def async_added_to_hass(self) -> None:
        """Subscribe to the selected output, without taking over existing playback."""
        self._listen()

    async def async_will_remove_from_hass(self) -> None:
        """Do not leave callbacks that could start another song after unload."""
        self._active = False
        self._generation += 1
        if self._unsubscribe:
            self._unsubscribe()
            self._unsubscribe = None
        if self._advance_task:
            self._advance_task.cancel()
            await asyncio.gather(self._advance_task, return_exceptions=True)

    def _outputs(self) -> dict[str, str]:
        registry = er.async_get(self.hass)
        result = {}
        for state in self.hass.states.async_all("media_player"):
            registered = registry.async_get(state.entity_id)
            if state.entity_id == self.entity_id or (registered and registered.platform == DOMAIN):
                continue
            if state.attributes.get("feiniu_queue"):
                continue
            if int(state.attributes.get("supported_features", 0)) & Feature.PLAY_MEDIA:
                name = state.attributes.get("friendly_name", state.entity_id)
                result[f"{name} ({state.entity_id})"] = state.entity_id
        return result

    @property
    def source_list(self) -> list[str]:
        return list(self._outputs())

    @property
    def source(self) -> str | None:
        return next(
            (label for label, entity in self._outputs().items() if entity == self._output), None
        )

    @property
    def supported_features(self) -> Feature:
        target = self._target()
        flags = Feature(target.attributes.get("supported_features", 0)) if target else Feature(0)
        return _BASE_FEATURES | (
            flags & (Feature.PAUSE | Feature.SEEK | Feature.VOLUME_SET | Feature.VOLUME_MUTE)
        )

    @property
    def volume_level(self) -> float | None:
        target = self._target()
        return target.attributes.get("volume_level") if target else None

    @property
    def is_volume_muted(self) -> bool | None:
        target = self._target()
        return target.attributes.get("is_volume_muted") if target else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "feiniu_queue": True,
            "output_player": self._output,
            "queue_length": len(self._order),
            "queue_position": self._position + 1 if self._order else 0,
            "queue_active": self._active,
            "last_queue_error": self._last_error,
        }

    def _target(self) -> State | None:
        return self.hass.states.get(self._output) if self._output else None

    def _listen(self) -> None:
        if self._unsubscribe:
            self._unsubscribe()
            self._unsubscribe = None
        if self._output:
            self._unsubscribe = async_track_state_change_event(
                self.hass, [self._output], self._target_changed
            )

    async def async_select_source(self, source: str) -> None:
        target = self._outputs().get(source)
        if target is None:
            raise ServiceValidationError("Select an available output media player")
        async with self._lock:
            # Changing the output never starts/stops an unrelated device.
            self._active = False
            self._generation += 1
            self._output = target
            self._attr_state = MediaPlayerState.IDLE
            self.hass.config_entries.async_update_entry(
                self.runtime.entry, options={**self.runtime.entry.options, CONF_OUTPUT: target}
            )
            self._listen()
            self.async_write_ha_state()

    def _identifier(self, media_id: str) -> str:
        prefix = f"media-source://{DOMAIN}/{self.runtime.entry.entry_id}"
        if media_id == prefix:
            return self.runtime.entry.entry_id
        if not media_id.startswith(prefix + "/"):
            raise ServiceValidationError("Select media from this FeiNiu account")
        identifier = media_id[len(f"media-source://{DOMAIN}/") :]
        for part in identifier.split("/"):
            valid_id(part)
        return identifier

    async def async_browse_media(
        self, media_content_type: str | None = None, media_content_id: str | None = None
    ) -> BrowseMedia:
        """Attach list context to each track, so selecting a song can continue its list."""
        identifier = (
            self._identifier(media_content_id) if media_content_id else self.runtime.entry.entry_id
        )
        result = await FeiNiuMediaSource(self.hass).async_browse_media(
            MediaSourceItem(self.hass, DOMAIN, identifier, self.entity_id)
        )
        parts = identifier.split("/")[1:]
        track_list = (
            parts == ["track"]
            or (len(parts) == 2 and parts[0] in {"album", "playlist"})
            or (len(parts) == 3 and parts[0] == "artist" and parts[2] == "tracks")
        )
        if track_list:
            result.can_play = bool(result.children)
            for index, child in enumerate(result.children or []):
                # Keep the selected ID as well as its position; fail if the list changed.
                guid = child.media_content_id.rsplit("/", 1)[-1]
                child.media_content_id = f"{result.media_content_id}/queue/{index}/{guid}"
        for child in result.children or []:
            if child.media_content_type in {"album", "playlist"}:
                child.can_play = True
        return result

    async def async_search_media(self, query: SearchMediaQuery) -> SearchMedia:
        return await FeiNiuMediaSource(self.hass).async_search_media(
            MediaSourceItem(self.hass, DOMAIN, self.runtime.entry.entry_id, self.entity_id), query
        )

    async def _items(self, media_id: str) -> tuple[list[str], int]:
        parts = self._identifier(media_id).split("/")[1:]
        position = 0
        selected = None
        if len(parts) >= 4 and parts[-3] == "queue":
            if not parts[-2].isdigit():
                raise ServiceValidationError("Invalid queue position")
            position, selected = int(parts[-2]), parts[-1]
            parts = parts[:-3]
        if len(parts) == 2 and parts[0] == "track":
            rows = [{"guid": parts[1]}]
        elif parts == ["track"]:
            rows = await self.runtime.collection("track")
        elif len(parts) == 2 and parts[0] in {"album", "playlist", "artist"}:
            rows = await self.runtime.related(parts[0], parts[1])
        elif len(parts) == 3 and parts[0] == "artist" and parts[2] == "tracks":
            rows = await self.runtime.related("artist", parts[1])
        else:
            raise ServiceValidationError("Select a track, album, playlist or artist track list")
        guids = [valid_id(row["guid"]) for row in rows]
        if not guids:
            raise ServiceValidationError("This selection has no accessible tracks")
        if position >= len(guids) or (selected is not None and guids[position] != selected):
            raise ServiceValidationError("The music list changed; browse it again")
        return guids, position

    async def async_play_media(self, media_type: str, media_id: str, **kwargs: Any) -> None:
        if kwargs.get("announce"):
            raise ServiceValidationError("Announcements are not supported by this queue")
        mode = kwargs.get("enqueue") or "replace"
        if mode not in {"replace", "add", "next", "play"}:
            raise ServiceValidationError("Unsupported queue mode")
        async with self._lock:
            try:
                guids, start = await self._items(media_id)
                if mode == "replace" or not self._queue:
                    self._queue = guids
                    self._order = list(range(len(guids)))
                    self._position = start
                    if self._attr_shuffle:
                        self._shuffle_order()
                    await self._start()
                else:
                    # Enqueuing a list starts with the selected member of that list.
                    guids = guids[start:]
                    indices = list(range(len(self._queue), len(self._queue) + len(guids)))
                    self._queue.extend(guids)
                    if mode == "add":
                        self._order.extend(indices)
                    else:
                        self._order[self._position + 1 : self._position + 1] = indices
                    if mode == "play":
                        self._position += 1
                        await self._start()
                    self.async_write_ha_state()
            except FeiNiuError as err:
                raise HomeAssistantError(str(err)) from err

    async def _send(self, service: str, data: dict[str, Any] | None = None) -> None:
        target = self._target()
        if target is None or target.state in {"unavailable", "unknown"}:
            raise ServiceValidationError("Select an available output player first")
        await self.hass.services.async_call(
            "media_player",
            service,
            {"entity_id": self._output, **(data or {})},
            blocking=True,
            context=self._context,
        )

    async def _start(self) -> None:
        """Resolve/check the next track just in time; send one original stream to the output."""
        self._generation += 1
        self._changing = True
        self._active = False
        self._seen_playing = False
        self._playback_ready.clear()
        self._last_error = None
        self._attr_state = MediaPlayerState.BUFFERING
        self.async_write_ha_state()
        try:
            guid = self._queue[self._order[self._position]]
            identifier = f"{self.runtime.entry.entry_id}/track/{guid}"
            resolved = await FeiNiuMediaSource(self.hass).async_resolve_media(
                MediaSourceItem(self.hass, DOMAIN, identifier, self.entity_id)
            )
            metadata = resolved.didl_metadata
            self._attr_media_content_id = f"media-source://{DOMAIN}/{identifier}"
            self._attr_media_title = metadata.title
            self._attr_media_artist = metadata.artist
            self._attr_media_album_name = metadata.album
            self._attr_media_image_url = metadata.album_art_uri
            self._attr_media_position = 0
            self._attr_media_position_updated_at = dt_util.utcnow()
            row = await self.runtime.detail("track", guid)
            duration = row.get("duration")
            self._attr_media_duration = (
                int(duration / 1000)
                if isinstance(duration, (int, float)) and duration > 0
                else None
            )
            self._expected_url = resolved.url
            self._active = True
            await self._send(
                "play_media",
                {
                    "media_content_id": resolved.url,
                    "media_content_type": resolved.mime_type,
                    "extra": {
                        "title": metadata.title,
                        "thumb": metadata.album_art_uri,
                        "metadata": {"artist": metadata.artist, "album": metadata.album},
                    },
                },
            )
            self._changing = False
            target = self._target()
            if target and self._matches(target):
                self._mirror(target)
            try:
                await asyncio.wait_for(self._playback_ready.wait(), timeout=20)
            except TimeoutError as err:
                raise HomeAssistantError(
                    "The output did not confirm playback of this track"
                ) from err
        except HomeAssistantError, FeiNiuError:
            self._active = False
            self._attr_state = MediaPlayerState.IDLE
            self._last_error = "playback_failed"
            raise
        finally:
            self._changing = False
            self.async_write_ha_state()

    def _matches(self, state: State) -> bool:
        url = state.attributes.get("media_content_id")
        if not isinstance(url, str) or not self._expected_url:
            return False
        actual, expected = urlsplit(url), urlsplit(self._expected_url)
        return (actual.scheme, actual.netloc, actual.path) == (
            expected.scheme,
            expected.netloc,
            expected.path,
        )

    def _mirror(self, target: State) -> None:
        if target.state in {
            MediaPlayerState.PLAYING,
            MediaPlayerState.PAUSED,
            MediaPlayerState.BUFFERING,
        }:
            self._attr_state = MediaPlayerState(target.state)
        if target.state == MediaPlayerState.PLAYING:
            self._seen_playing = True
            self._playback_ready.set()
        for name in ("media_position", "media_position_updated_at", "media_duration"):
            if (value := target.attributes.get(name)) is not None:
                setattr(self, f"_attr_{name}", value)

    def _at_end(self, old: State | None) -> bool:
        if not old or old.state != MediaPlayerState.PLAYING:
            return False
        duration = old.attributes.get("media_duration") or self.media_duration
        position = old.attributes.get("media_position")
        updated = old.attributes.get("media_position_updated_at")
        if (
            not isinstance(duration, (float, int))
            or duration <= 0
            or not isinstance(position, (float, int))
        ):
            return False
        if isinstance(updated, str):
            updated = dt_util.parse_datetime(updated)
        if isinstance(updated, datetime):
            position += max(0, (dt_util.utcnow() - updated).total_seconds())
        return position >= duration - 2

    @callback
    def _target_changed(self, event: Event[EventStateChangedData]) -> None:
        new, old = event.data.get("new_state"), event.data.get("old_state")
        if not self._active or self._changing:
            self.async_write_ha_state()
            return
        if new is None or new.state in {"off", "unavailable", "unknown"}:
            self._active = False
            self._attr_state = MediaPlayerState.IDLE
        elif self._matches(new) and new.state != MediaPlayerState.IDLE:
            self._mirror(new)
        elif new.state == MediaPlayerState.IDLE and (
            self._matches(new) or not new.attributes.get("media_content_id")
        ):
            if not self._seen_playing:
                # SetTransportURI may briefly report idle before the new track starts.
                return
            completed = self._seen_playing and self._at_end(old)
            self._active = False
            self._attr_state = MediaPlayerState.IDLE
            if completed:
                generation = self._generation
                self._advance_task = self.hass.async_create_task(self._auto_advance(generation))
        else:
            # An external controller replaced playback. Never reclaim the speaker automatically.
            self._active = False
            self._attr_state = MediaPlayerState.IDLE
        self.async_write_ha_state()

    async def _auto_advance(self, generation: int) -> None:
        async with self._lock:
            if generation != self._generation:
                return
            try:
                await self._advance(automatic=True)
            except (HomeAssistantError, FeiNiuError) as err:
                self._active = False
                self._attr_state = MediaPlayerState.IDLE
                self._last_error = "playback_failed"
                self.async_write_ha_state()
                _LOGGER.warning("FeiNiu queue stopped: %s", type(err).__name__)

    async def _advance(self, *, automatic: bool = False) -> None:
        if not self._order:
            return
        if not (automatic and self._attr_repeat == RepeatMode.ONE):
            if self._position + 1 < len(self._order):
                self._position += 1
            elif self._attr_repeat == RepeatMode.ALL:
                self._position = 0
            else:
                await self._stop()
                return
        await self._start()

    async def async_media_next_track(self) -> None:
        async with self._lock:
            await self._advance()

    async def async_media_previous_track(self) -> None:
        async with self._lock:
            if self._order:
                self._position = (
                    (self._position - 1) % len(self._order)
                    if self._attr_repeat == RepeatMode.ALL
                    else max(0, self._position - 1)
                )
                await self._start()

    async def async_media_play(self) -> None:
        async with self._lock:
            if self._active:
                if self.state == MediaPlayerState.PAUSED:
                    await self._send("media_play")
            elif self._order:
                await self._start()

    async def async_media_pause(self) -> None:
        async with self._lock:
            if self._active and self.state != MediaPlayerState.PAUSED:
                await self._send("media_pause")

    async def async_media_seek(self, position: float) -> None:
        async with self._lock:
            if (
                not self._active
                or position < 0
                or (self.media_duration and position > self.media_duration)
            ):
                raise ServiceValidationError("No active track at that position")
            await self._send("media_seek", {"seek_position": position})

    async def _stop(self) -> None:
        was_active = self._active
        self._active = False
        self._generation += 1
        if was_active:
            await self._send("media_stop")
        self._attr_state = MediaPlayerState.IDLE
        self.async_write_ha_state()

    async def async_media_stop(self) -> None:
        async with self._lock:
            await self._stop()

    async def async_clear_playlist(self) -> None:
        async with self._lock:
            await self._stop()
            self._queue.clear()
            self._order.clear()
            self._position = 0
            self.async_write_ha_state()

    async def async_set_volume_level(self, volume: float) -> None:
        await self._send("volume_set", {"volume_level": volume})

    async def async_mute_volume(self, mute: bool) -> None:
        await self._send("volume_mute", {"is_volume_muted": mute})

    async def async_set_repeat(self, repeat: str) -> None:
        self._attr_repeat = RepeatMode(repeat)
        self.async_write_ha_state()

    def _shuffle_order(self) -> None:
        current = self._order[self._position]
        remaining = [i for i in self._order if i != current]
        random.shuffle(remaining)
        self._order = [current, *remaining]
        self._position = 0

    async def async_set_shuffle(self, shuffle: bool) -> None:
        async with self._lock:
            self._attr_shuffle = shuffle
            if self._order:
                current = self._order[self._position]
                if shuffle:
                    self._shuffle_order()
                else:
                    self._order.sort()
                    self._position = self._order.index(current)
            self.async_write_ha_state()
