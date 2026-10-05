"""Fixed account/output entities; sessions own control and queues own order."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import asdict, replace
from datetime import timedelta
from time import monotonic
from typing import Any

from homeassistant.components.http.auth import async_sign_path
from homeassistant.components.media_player import (
    BrowseMedia,
    MediaPlayerEntity,
    MediaPlayerState,
    MediaType,
    RepeatMode,
    SearchMedia,
    SearchMediaQuery,
)
from homeassistant.components.media_player import MediaPlayerEntityFeature as Feature
from homeassistant.components.media_player.browse_media import async_process_play_media_url
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .client import FeiNiuError
from .const import DOMAIN
from .media import mime_type, play_media
from .output import OutputAdapter, OutputLeases
from .queue import QueueItem
from .runtime import FeiNiuConfigEntry, FeiNiuRuntime
from .selection import Selection
from .session import PlaybackRequest, PlaybackSession
from .storage import SavedSession
from .streaming import AudioRound
from .timeline import number

_BASE_FEATURES = (
    Feature.PLAY_MEDIA
    | Feature.BROWSE_MEDIA
    | Feature.SEARCH_MEDIA
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
    """Only explicitly selected outputs receive an entity; options are incremental."""
    from .players import AccountPlayers

    manager = AccountPlayers(hass, entry, async_add_entities)
    hass.data[DOMAIN].setdefault("players", {})[entry.entry_id] = manager
    await manager.setup()


class FeiNiuPlayer(MediaPlayerEntity):
    """HA facade; properties never resolve content or send output commands."""

    _attr_should_poll = False
    _attr_icon = "mdi:music-circle"
    _attr_media_content_type = MediaType.MUSIC

    def __init__(
        self,
        runtime: FeiNiuRuntime,
        saved: SavedSession,
        leases: OutputLeases,
        persist: Callable[[SavedSession], None],
        *,
        legacy: bool = False,
    ) -> None:
        self.runtime = runtime
        self.saved = saved
        self.output = OutputAdapter(runtime.hass, saved.binding)
        self._leases = leases
        self._persist = persist
        self.session: PlaybackSession | None = None
        self._removed = False
        self._persist_key: tuple | None = None
        self._checkpoint = monotonic()
        self._resume_position = saved.position
        self._attr_unique_id = (
            f"{runtime.entry.entry_id}_player"
            if legacy
            else f"{runtime.entry.entry_id}_{saved.binding.key}"
        )
        self._attr_name = f"{runtime.entry.title} · {saved.binding.entity_id.split('.', 1)[-1]}"

    @property
    def control(self) -> PlaybackSession:
        if self.session is None or self.session.closed:
            raise ServiceValidationError("This output session is unavailable")
        return self.session

    async def async_added_to_hass(self) -> None:
        self._removed = False
        self.session = PlaybackSession(
            self.hass,
            self.output,
            self._leases,
            self._resolve,
            self._changed,
            queue=self.saved.queue,
            profile=self.saved.profile,
            cancel_streams=lambda: self.runtime.cancel_audio(self.saved.binding.key),
        )
        self._changed()

    async def async_will_remove_from_hass(self) -> None:
        if self._removed:
            return
        self._save(force=True)
        self._removed = True
        if self.session:
            await self.session.close()

    @callback
    def _changed(self) -> None:
        if self._removed or self.session is None:
            return
        self._save()
        self.async_write_ha_state()

    def _save(self, *, force: bool = False) -> None:
        if self.session is None:
            return
        session = self.session
        key = (session.queue.revision, session.phase, self.saved.lyric_offset, session.profile)
        if force or key != self._persist_key or monotonic() - self._checkpoint >= 30:
            position = session.timeline.saved_position()
            if position is not None:
                self.saved.position = position
            elif session.phase not in {"restored", "idle"}:
                self.saved.position = None
            self.saved.profile = session.profile
            self._persist(self.saved)
            self._persist_key, self._checkpoint = key, monotonic()

    @property
    def name(self) -> str:
        target = self.output.state
        label = target.name if target else self.saved.binding.entity_id
        return f"{self.runtime.entry.title} · {label}"

    @property
    def state(self) -> MediaPlayerState:
        phase = self.session.phase if self.session else "idle"
        return {
            "playing": MediaPlayerState.PLAYING,
            "paused": MediaPlayerState.PAUSED,
            "loading": MediaPlayerState.BUFFERING,
            "buffering": MediaPlayerState.BUFFERING,
        }.get(phase, MediaPlayerState.IDLE)

    @property
    def available(self) -> bool:
        return not self.runtime.closed and self.output.available

    @property
    def supported_features(self) -> Feature:
        features = _BASE_FEATURES | (
            self.output.features
            & (Feature.PAUSE | Feature.SEEK | Feature.VOLUME_SET | Feature.VOLUME_MUTE)
        )
        # Preserve the standard mode's feature projection. Compatibility adds a
        # truthful seek gate while retaining an unconfirmed playback session.
        if (
            self.session
            and self.session.compatible
            and self.session.confirmation_stage != "confirmed"
        ):
            features &= ~Feature.SEEK
        return features

    @property
    def assumed_state(self) -> bool:
        session = self.session
        return bool(
            session
            and session.compatible
            and session.owned
            and (
                session.confirmation_stage == "assumed"
                or session.reason in {"pause_requested", "resume_requested"}
            )
        )

    @property
    def volume_level(self) -> float | None:
        return (
            number(self.output.state.attributes.get("volume_level")) if self.output.state else None
        )

    @property
    def is_volume_muted(self) -> bool | None:
        value = self.output.state.attributes.get("is_volume_muted") if self.output.state else None
        return value if type(value) is bool else None

    @property
    def shuffle(self) -> bool:
        return self.saved.queue.shuffle

    @property
    def repeat(self) -> RepeatMode:
        return RepeatMode(self.saved.queue.repeat)

    @property
    def media_position(self) -> int | None:
        if self.session and self.session.position_visible:
            value = self.session.timeline.ha_anchor()[0]
            return int(value) if value is not None else None
        return None

    @property
    def media_position_updated_at(self):
        if self.session and self.session.position_visible:
            return self.session.timeline.ha_anchor()[1]
        return None

    @property
    def media_duration(self) -> int | None:
        value = self.session.timeline.duration if self.session else None
        return int(value) if value is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        session, queue = self.session, self.saved.queue
        return {
            "feiniu_queue": True,
            "output_player": self.output.entity_id,
            "queue_length": len(queue.items),
            "queue_position": queue.position + 1,
            "queue_revision": queue.revision,
            "queue_item_id": queue.current_id,
            "queue_active": bool(session and session.owned and session.position_visible),
            "session_phase": session.phase if session else "idle",
            "session_reason": session.reason if session else "not_loaded",
            "last_queue_error": session.reason if session and session.phase == "failed" else None,
            "playback_round": session.round_id if session else 0,
            "confirmation": session.confirmation if session else "unconfirmed",
            "confirmation_stage": session.confirmation_stage if session else None,
            "effective_feedback_mode": session.feedback_mode if session else "standard",
            "effective_unconfirmed_end": session.unconfirmed_end if session else "manual",
            "estimated_end_blocked_reason": session.estimated_end_blocked_reason
            if session
            else None,
            "position_source": session.timeline.source
            if session and session.position_visible
            else "unavailable",
            "lyric_offset": self.saved.lyric_offset,
            "playback_profile": asdict(session.profile if session else self.saved.profile),
        }

    @callback
    def set_playback_profile(self, changes: dict[str, Any]) -> None:
        """Share per-output preferences between native options and the optional card."""
        self.control.profile = replace(self.control.profile, **changes)
        self._changed()

    async def _resolve(self, item: QueueItem, round_id: int) -> PlaybackRequest:
        """JIT permission validation and unique round URL before any output command."""
        session = self.control
        generation = session.generation
        row = await self.runtime.detail("track", item.track_id, fresh=True)
        if (
            session.closed
            or generation != session.generation
            or round_id != session.round_id
            or item.item_id != session.queue.current_id
        ):
            raise asyncio.CancelledError
        mime = mime_type(row)
        token = self.runtime.grant_audio(
            AudioRound(self.saved.binding.key, item.track_id, round_id, session.stream_event)
        )
        path = (
            f"/api/{DOMAIN}/{self.runtime.entry.entry_id}/{self.runtime.scope}"
            f"/session/{token}/{item.track_id}"
        )
        url = async_process_play_media_url(
            self.hass, async_sign_path(self.hass, path, timedelta(hours=2))
        )
        metadata = play_media(self.runtime, row, url, mime).didl_metadata
        self._attr_media_content_id = (
            f"media-source://{DOMAIN}/{self.runtime.entry.entry_id}/track/{item.track_id}"
        )
        self._attr_media_title = metadata.title
        self._attr_media_artist = metadata.artist
        self._attr_media_album_name = metadata.album
        # HA's image proxy serves the full player; the speaker keeps the smaller
        # existing artwork grant. Both variants retain the same owner checks.
        self._attr_media_image_url = (
            f"{metadata.album_art_uri}&size=1024" if metadata.album_art_uri else None
        )
        duration = number(row.get("duration"))
        return PlaybackRequest(
            url,
            # HA needs the music media class to retain artist/album/artwork in DLNA.
            # The audio endpoint still supplies the original MIME Content-Type.
            MediaType.MUSIC,
            {
                "title": metadata.title,
                "thumb": metadata.album_art_uri,
                "metadata": {"artist": metadata.artist, "album": metadata.album},
            },
            duration / 1000 if duration is not None and duration > 0 else None,
        )

    async def async_browse_media(
        self, media_content_type: str | None = None, media_content_id: str | None = None
    ) -> BrowseMedia:
        return await Selection(self.runtime, self.entity_id).browse(
            media_content_id=media_content_id
        )

    async def async_search_media(self, query: SearchMediaQuery) -> SearchMedia:
        return await Selection(self.runtime, self.entity_id).search(query)

    async def async_play_media(self, media_type: str, media_id: str, **kwargs: Any) -> None:
        if kwargs.get("announce"):
            raise ServiceValidationError("Announcements are not supported by this queue")
        self._resume_position = None
        try:
            await self.control.replace_or_enqueue(
                lambda: Selection(self.runtime, self.entity_id).items(
                    media_id, expand_context=kwargs.get("enqueue") not in {"add", "next"}
                ),
                kwargs.get("enqueue") or "replace",
                context=self._context,
            )
        except FeiNiuError as err:
            raise HomeAssistantError(str(err)) from err

    async def async_media_play(self) -> None:
        session = self.control
        position, self._resume_position = self._resume_position, None
        await session.start(context=self._context)
        if position and session.started:
            if self.output.features & Feature.SEEK:
                await session.seek(min(position, session.timeline.duration or position))
            else:
                session.record("resume", "from_start_seek_unavailable")

    async def async_media_pause(self) -> None:
        await self.control.pause()

    async def async_media_stop(self) -> None:
        await self.control.stop()

    async def async_media_seek(self, position: float) -> None:
        await self.control.seek(position)

    async def async_media_next_track(self) -> None:
        self._resume_position = None
        await self.control.next()

    async def async_media_previous_track(self) -> None:
        self._resume_position = None
        await self.control.next(previous=True)

    async def async_clear_playlist(self) -> None:
        self._resume_position = None
        self.saved.position = None
        await self.control.stop(clear=True)

    async def async_set_volume_level(self, volume: float) -> None:
        await self.output.send("volume_set", {"volume_level": volume}, context=self._context)

    async def async_mute_volume(self, mute: bool) -> None:
        await self.output.send("volume_mute", {"is_volume_muted": mute}, context=self._context)

    async def async_set_repeat(self, repeat: str) -> None:
        self.control.queue.set_repeat(repeat)
        self.control.record("queue", "repeat_changed")
        self._changed()

    async def async_set_shuffle(self, shuffle: bool) -> None:
        self.control.queue.set_shuffle(shuffle)
        self.control.record("queue", "shuffle_changed")
        self._changed()

    async def edit_queue(
        self, action: str, revision: int, item_id: str | None = None, before_id: str | None = None
    ) -> None:
        session = self.control
        if action == "jump" and item_id is not None:
            await session.jump(item_id, revision)
        elif action == "move" and item_id is not None:
            session.queue.move(item_id, before_id, revision)
            session.record("queue", "move")
            self._changed()
        elif action == "remove" and item_id is not None:
            current = item_id == session.queue.current_id
            playing = session.owned and session.position_visible and session.phase == "playing"
            session.queue.remove(item_id, revision)
            session.record("queue", "remove")
            if current:
                await session.stop()
                if playing and session.queue.current:
                    await session.start(context=self._context)
            self._changed()
        elif action == "clear":
            session.queue.check_revision(revision)
            await self.async_clear_playlist()
        else:
            raise ServiceValidationError("Invalid queue edit")
