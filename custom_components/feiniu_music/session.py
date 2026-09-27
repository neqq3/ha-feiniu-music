"""Cancellable playback for one fixed account/output pair, without device protocols."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from homeassistant.components.media_player import MediaPlayerEntityFeature as Feature
from homeassistant.core import Context, HomeAssistant, State
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from .client import FeiNiuError
from .output import OutputAdapter, OutputLeases
from .queue import QueueItem, QueueModel
from .timeline import Timeline

START_TIMEOUT = 20.0
COMPAT_PLAY_DELAY = 2.0
SEEK_TIMEOUT = 5.0


@dataclass(frozen=True, slots=True)
class PlaybackRequest:
    """Server-only resolved request. No URL/metadata is included in diagnostics/storage."""

    url: str
    content_type: str
    extra: dict[str, Any]
    duration: float | None = None


@dataclass(frozen=True, slots=True)
class OutputProfile:
    """A small set of explicit, per-output compatibility choices."""

    confirmation: str = "delivery"
    play_once: bool = False
    end_state: str = "idle"
    weak_end: bool = False

    def __post_init__(self) -> None:
        if self.confirmation not in {"delivery", "reported"}:
            raise ValueError("Invalid start confirmation policy")
        if self.end_state not in {"idle", "paused", "off"}:
            raise ValueError("Invalid end-state policy")
        if type(self.play_once) is not bool or type(self.weak_end) is not bool:
            raise ValueError("Invalid compatibility flags")


def _identity_url(url: str) -> tuple:
    """Only HA's authentication signature is irrelevant; all business query fields remain."""
    parts = urlsplit(url)
    return (
        parts.scheme.lower(),
        parts.netloc.lower(),
        parts.path,
        tuple((key, value) for key, value in parse_qsl(parts.query) if key != "authSig"),
    )


class PlaybackSession:
    """Synchronous intent changes invalidate cancellable work at every async boundary."""

    def __init__(
        self,
        hass: HomeAssistant,
        output: OutputAdapter,
        leases: OutputLeases,
        resolve: Callable[[QueueItem, int], Awaitable[PlaybackRequest]],
        changed: Callable[[], None],
        *,
        queue: QueueModel | None = None,
        profile: OutputProfile | None = None,
        timeline: Timeline | None = None,
        cancel_streams: Callable[[], None] | None = None,
    ) -> None:
        self.hass = hass
        self.output = output
        self.leases = leases
        self.resolve = resolve
        self.changed = changed
        self.queue = queue if queue is not None else QueueModel()
        self.profile = profile or OutputProfile()
        self.timeline = timeline or Timeline()
        self.cancel_streams = cancel_streams or (lambda: None)
        self.phase = "restored" if self.queue.items else "idle"
        self.reason = "queue_restored" if self.queue.items else "empty_queue"
        self.intent = "none"
        self.generation = 0
        self.round_id = 0
        self.closed = False
        self.started = False
        self.identity = "unknown"
        self.confirmation = "unconfirmed"
        self._expected: str | None = None
        self._retired: deque[str] = deque(maxlen=8)
        self._before_command: str | None = None
        self._operation: asyncio.Task | None = None
        self._advance: asyncio.Task | None = None
        self._seek: asyncio.Task | None = None
        self._seek_return_intent = "play"
        self._ready = asyncio.Event()
        self._audio = False
        self._raw_samples = 0
        self._issued = False
        self._controlled = False
        self._edits: set[asyncio.Task] = set()
        self._ended_round = -1
        self._source: tuple[Any, Any] | None = None
        self._context: Context | None = None
        self.history: deque[dict[str, Any]] = deque(maxlen=32)
        self.stream_counts: dict[str, int] = {}
        self.output.subscribe(self.observe)

    @property
    def owned(self) -> bool:
        return self.leases.owns(self.output.binding.key, self)

    def record(self, event: str, reason: str) -> None:
        """Only controlled labels and numbers; never raw exception text or media URLs."""
        self.history.append(
            {
                "event": event,
                "reason": reason,
                "round": self.round_id,
                "generation": self.generation,
                "revision": self.queue.revision,
            }
        )

    def _invalidate(self, intent: str) -> int:
        self.generation += 1
        self.intent = intent
        current = asyncio.current_task()
        for task in (self._operation, self._advance, self._seek, *self._edits):
            if task and task is not current and not task.done():
                task.cancel()
        self.record("intent", intent)
        return self.generation

    def _valid(self, generation: int) -> bool:
        return not self.closed and generation == self.generation and self.owned

    def _check(self, generation: int) -> None:
        if not self._valid(generation):
            raise asyncio.CancelledError

    def _claim(self) -> None:
        if self.closed:
            raise ServiceValidationError("This output session is unloaded")
        self.leases.claim(self.output.binding.key, self, self._displaced)

    def _prepare_load(self) -> None:
        if self._expected:
            self._retired.append(self._expected)
        self._expected = None
        self.started = self._issued = False
        self.phase, self.reason = "loading", "resolving_track"
        self.timeline.freeze("changing_track", forget=True)

    def _displaced(self) -> None:
        self.detach("another_feiniu_session")

    def detach(self, reason: str) -> None:
        self._invalidate("detach")
        self.started = False
        self._controlled = False
        self.phase = "detached"
        self.reason = reason
        self.timeline.freeze(reason, forget=True)
        self.cancel_streams()
        self.leases.release(self.output.binding.key, self)
        self.changed()

    def _fail(self, reason: str) -> None:
        self._invalidate("failure")
        self.phase, self.reason, self.started = "failed", reason, False
        self._controlled = False
        self.timeline.freeze(reason)
        self.leases.release(self.output.binding.key, self)
        self.cancel_streams()
        self.record("failure", reason)
        self.changed()

    async def _await_operation(self, generation: int, action: Coroutine[Any, Any, None]) -> None:
        task: asyncio.Task[None] = self.hass.async_create_background_task(
            action, "FeiNiu playback operation"
        )
        self._operation = task
        try:
            await task
        except asyncio.CancelledError:
            if generation == self.generation and not self.closed:
                self.detach("request_cancelled")
                raise
            # A newer explicit intent superseded this call; never send stale cleanup.
        except (HomeAssistantError, FeiNiuError, ValueError, TimeoutError) as err:
            if self._valid(generation):
                self._fail(
                    "start_unconfirmed"
                    if self.reason == "start_unconfirmed"
                    else type(err).__name__
                )
            raise
        finally:
            if self._operation is task:
                self._operation = None

    async def replace_or_enqueue(
        self,
        read: Callable[[], Coroutine[Any, Any, tuple[list[QueueItem], int]]],
        mode: str,
        *,
        context: Context | None = None,
    ) -> None:
        """The slow collection read is itself cancellable, before any queue mutation."""
        if mode not in {"replace", "add", "next", "play"}:
            raise ServiceValidationError("Unknown enqueue mode")
        if mode in {"add", "next"}:
            # Queue-only operations do not take over the physical output. They still
            # reject a stale result if Stop/replace/remove happened during the read.
            generation, revision = self.generation, self.queue.revision
            task = self.hass.async_create_background_task(read(), "FeiNiu queue selection")
            self._edits.add(task)
            try:
                rows, start = await task
            except asyncio.CancelledError:
                if self.closed or generation != self.generation:
                    return
                raise
            finally:
                self._edits.discard(task)
            if self.closed or generation != self.generation:
                return
            self.queue.check_revision(revision)
            self.queue.enqueue(rows[start:], mode)
            self.changed()
            return
        self._context = context
        generation = self._invalidate("play")
        self._claim()
        self._prepare_load()
        self.phase, self.reason = "loading", "loading_selection"
        self.changed()

        async def work() -> None:
            rows, start = await read()
            self._check(generation)
            if self.queue.enqueue(rows, mode, start):
                await self._load(generation)
            else:
                self.phase, self.reason = "idle", "empty_queue"
                self.leases.release(self.output.binding.key, self)
                self.changed()

        await self._await_operation(generation, work())

    async def start(self, *, context: Context | None = None) -> None:
        self._context = context
        target = self.output.state
        if self.owned and self.started and target and self._matches(target) == "matched":
            if target.state == "paused":
                generation = self._invalidate("play")
                self._ready.clear()
                await self._await_operation(generation, self._resume(generation))
                return
            if target.state == "playing" and self.phase == "playing":
                return
        if not self.queue.current and self.queue.order:
            self.queue.jump(self.queue.order[0], self.queue.revision)
        if not self.queue.current:
            return
        generation = self._invalidate("play")
        self._claim()
        self._prepare_load()
        await self._await_operation(generation, self._load(generation))

    async def _resume(self, generation: int) -> None:
        self.phase, self.reason = "loading", "resuming"
        self.changed()
        await self._send(generation, "media_play")
        await asyncio.wait_for(self._ready.wait(), START_TIMEOUT)
        self._check(generation)

    async def _send(self, generation: int, service: str, data: dict | None = None) -> None:
        self._check(generation)
        self.record("command", service)
        await self.output.send(service, data, context=self._context)
        self._check(generation)

    async def _load(self, generation: int) -> None:
        self._check(generation)
        item = self.queue.current
        if item is None:
            return
        self.cancel_streams()
        self.round_id += 1
        self._prepare_load()
        self._audio, self.started, self._issued = False, False, False
        self._raw_samples = 0
        self.stream_counts = {}
        self._ready.clear()
        self.identity, self.confirmation = "unknown", "unconfirmed"
        self.phase, self.reason = "loading", "resolving_track"
        self.timeline.reset(self.round_id)
        self.changed()
        request = await self.resolve(item, self.round_id)
        self._check(generation)
        if self.queue.current_id != item.item_id:
            raise asyncio.CancelledError
        self.timeline.reset(self.round_id, request.duration)
        self._expected = request.url
        target = self.output.state
        self._source = self._source_of(target) if target else None
        value = target.attributes.get("media_content_id") if target else None
        self._before_command = value if isinstance(value, str) else None
        self._issued = True
        self._controlled = True
        await self._send(
            generation,
            "play_media",
            {
                "media_content_id": request.url,
                "media_content_type": request.content_type,
                "extra": request.extra,
            },
        )
        # Events were processed even during the command; inspect the final snapshot too.
        self.observe(None, self.output.state)
        self._check(generation)
        if self.profile.play_once and not self._ready.is_set():
            try:
                await asyncio.wait_for(self._ready.wait(), COMPAT_PLAY_DELAY)
            except TimeoutError:
                self._check(generation)
                target = self.output.state
                if self.intent == "play" and target and self._matches(target) == "matched":
                    if self.output.features & Feature.PLAY:
                        self.record("compatibility", "one_standard_play_after_load")
                        await self._send(generation, "media_play")
        try:
            await asyncio.wait_for(self._ready.wait(), START_TIMEOUT)
        except TimeoutError:
            self.reason = "start_unconfirmed"
            raise HomeAssistantError("Output did not confirm this playback round") from None
        self._check(generation)

    @staticmethod
    def _source_of(state: State) -> tuple[Any, Any]:
        return state.attributes.get("app_id"), state.attributes.get("source")

    def _matches(self, state: State) -> str:
        value = state.attributes.get("media_content_id")
        if not self._expected or not isinstance(value, str) or not value:
            return "unknown"
        if _identity_url(value) == _identity_url(self._expected):
            return "matched"
        if urlsplit(value).scheme in {"http", "https"}:
            return "foreign"
        return "unknown"

    def stream_event(self, round_id: int, event: str) -> None:
        """Called by the controlled HTTP route, never with URLs or arbitrary error text."""
        if self.closed or not self.owned or round_id != self.round_id:
            return
        if event not in {"head", "get", "first_byte", "eof", "cancelled", "error"}:
            return
        self.stream_counts[event] = min(1000000, self.stream_counts.get(event, 0) + 1)
        if event == "first_byte":
            self._audio = True
            self.observe(None, self.output.state)
        elif event == "error":
            self._fail("stream_failed")
        # EOF is delivery completion, not acoustic completion or a queue-advance signal.
        self.changed()

    def observe(self, old: State | None, new: State | None) -> None:
        if self.closed:
            return
        if not self.owned:
            self.changed()
            return
        if new is None or new.state in {"unavailable", "unknown"}:
            self.detach("output_unavailable")
            return
        identity = self._matches(new)
        # Until the new SetURI command has been sent, a previous track is not evidence
        # that the new round was stolen. It cannot confirm or finish the round either.
        if not self._issued:
            self.changed()
            return
        actual = new.attributes.get("media_content_id")
        if isinstance(actual, str) and identity == "foreign":
            retired = any(_identity_url(actual) == _identity_url(url) for url in self._retired)
            loading_previous = (
                not self.started
                and self.phase == "loading"
                and self._before_command is not None
                and _identity_url(actual) == _identity_url(self._before_command)
            )
            if retired or loading_previous:
                self.record("observation", "previous_round_ignored")
                return
        source = self._source_of(new)
        if identity == "foreign" or (
            self.started
            and identity == "unknown"
            and self._source is not None
            and source != self._source
            and any(source)
        ):
            self.detach("external_media")
            return
        self.identity = identity
        evidence = identity == "matched" or (identity == "unknown" and self._audio)
        if not evidence:
            self.reason = "awaiting_media_identity"
            self.changed()
            return
        was_playing = old is not None and old.state == "playing"
        old_position = self.timeline.position()
        duration = self.timeline.duration
        if self.timeline.observe(self.round_id, new.state, new.attributes):
            self._raw_samples += 1
        if self.intent == "seek" and self.timeline.seek_target is None:
            self.intent = self._seek_return_intent
            if self._seek:
                self._seek.cancel()
                self._seek = None
        if new.state == "playing" and self.intent not in {"pause", "stop", "seek"}:
            confirmed = (
                self.profile.confirmation == "reported" or self._audio or self._raw_samples >= 2
            )
            if confirmed:
                self.started = True
                self.phase, self.reason = "playing", "output_reported_playing"
                self.confirmation = (
                    "delivery"
                    if self._audio
                    else ("native_samples" if self._raw_samples >= 2 else "reported")
                )
                self._source = source
                self.timeline.confirm(self.round_id, estimate_from_start=self._audio)
                self._ready.set()
            else:
                self.phase, self.reason = "loading", "reported_without_delivery"
        elif new.state == self.profile.end_state and self.started and was_playing:
            native_end = (
                self.timeline.source == "native"
                and old_position is not None
                and duration is not None
                and old_position >= max(0, duration - min(2, duration / 5))
            )
            weak_end = self.profile.weak_end and self.identity != "foreign"
            if (
                self.intent == "play"
                and self._ended_round != self.round_id
                and ((identity == "matched" and native_end) or weak_end)
            ):
                self._ended_round = self.round_id
                self.phase, self.reason, self.started = "idle", "natural_end", False
                generation = self.generation
                self._advance = self.hass.async_create_background_task(
                    self._auto_advance(generation), "FeiNiu natural queue advance"
                )
            elif self.intent not in {"pause", "stop", "seek"}:
                self.detach("end_not_confirmed")
                return
        elif new.state == "paused" and (self.started or self.intent == "pause"):
            self.phase, self.reason = "paused", "output_paused"
        elif new.state == "buffering" and self.started:
            self.phase, self.reason = "buffering", "output_buffering"
        elif (
            new.state in {"idle", "off"}
            and self.started
            and self.intent not in {"pause", "stop", "seek"}
        ):
            self.detach("output_stopped")
            return
        self.changed()

    async def _auto_advance(self, generation: int) -> None:
        if not self._valid(generation) or self.intent != "play":
            return
        if self.queue.advance(natural=True) is None:
            self.phase, self.reason = "ended", "queue_ended"
            self.timeline.freeze("queue_ended")
            self.leases.release(self.output.binding.key, self)
            self.changed()
            return
        new_generation = self._invalidate("play")
        self._prepare_load()
        try:
            await self._await_operation(new_generation, self._load(new_generation))
        except HomeAssistantError, FeiNiuError, ValueError, TimeoutError:
            # _await_operation already records the classified failure; do not skip items.
            return

    async def next(self, *, previous: bool = False) -> None:
        generation = self._invalidate("play")
        item = self.queue.previous() if previous else self.queue.advance()
        if item is None:
            await self.stop()
            return
        self._claim()
        self._prepare_load()
        await self._await_operation(generation, self._load(generation))

    async def jump(self, item_id: str, revision: int) -> None:
        self.queue.jump(item_id, revision)
        generation = self._invalidate("play")
        self._claim()
        self._prepare_load()
        await self._await_operation(generation, self._load(generation))

    async def pause(self) -> None:
        generation = self._invalidate("pause")
        self.timeline.freeze("pause_requested")
        self.reason = "pause_requested"
        if self.owned and self._controlled:
            if not self.output.features & Feature.PAUSE:
                self._fail("pause_unsupported")
                raise ServiceValidationError("Output cannot pause at this time")
            try:
                await self._send(generation, "media_pause")
            except HomeAssistantError:
                self._fail("pause_unconfirmed")
                raise
            if not self._issued:
                self.phase, self.reason = "idle", "loading_cancelled"
                self._controlled = False
                self.cancel_streams()
                self.leases.release(self.output.binding.key, self)
        else:
            self.phase, self.reason = "idle", "loading_cancelled"
            self.leases.release(self.output.binding.key, self)
        self.changed()

    async def stop(self, *, clear: bool = False) -> None:
        generation = self._invalidate("stop")
        self.started = False
        self.timeline.freeze("stop_requested")
        self.phase, self.reason = "idle", "stop_requested"
        if clear:
            self.queue.clear()
        self.cancel_streams()
        try:
            if self.owned and self._controlled:
                await self._send(generation, "media_stop")
        except HomeAssistantError:
            self.phase, self.reason = "failed", "stop_unconfirmed"
            raise
        finally:
            self._controlled = False
            self.leases.release(self.output.binding.key, self)
            self.changed()

    async def seek(self, position: float) -> None:
        if not self.owned or not self.started or not self.output.features & Feature.SEEK:
            raise ServiceValidationError("Output cannot seek this playback")
        self._seek_return_intent = (
            "pause" if self.output.state and self.output.state.state == "paused" else "play"
        )
        self.timeline.request_seek(position)
        generation = self._invalidate("seek")
        try:
            await self._send(generation, "media_seek", {"seek_position": position})
        except HomeAssistantError:
            self.timeline.reject_seek()
            self.intent = self._seek_return_intent
            self.changed()
            raise
        if self.timeline.seek_target is None:
            self.intent = self._seek_return_intent
        else:

            async def expire() -> None:
                await asyncio.sleep(SEEK_TIMEOUT)
                if self._valid(generation):
                    self.timeline.reject_seek()
                    self.intent = self._seek_return_intent
                    self.changed()

            self._seek = self.hass.async_create_background_task(
                expire(), "FeiNiu seek confirmation"
            )
        self.changed()

    async def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self._invalidate("unload")
        self.output.close()
        self.leases.release(self.output.binding.key, self)
        self.cancel_streams()
        tasks = [
            task
            for task in (self._operation, self._advance, self._seek, *self._edits)
            if task and task is not asyncio.current_task()
        ]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def diagnostics(self) -> dict[str, Any]:
        return {
            "profile": asdict(self.profile),
            "phase": self.phase,
            "reason": self.reason,
            "intent": self.intent,
            "generation": self.generation,
            "round": self.round_id,
            "queue_revision": self.queue.revision,
            "queue_length": len(self.queue.items),
            "owned": self.owned,
            "identity": self.identity,
            "confirmation": self.confirmation,
            "position_source": self.timeline.source,
            "timeline_reason": self.timeline.reason,
            "output_state": self.output.state.state if self.output.state else "missing",
            "features": int(self.output.features),
            "stream_events": dict(self.stream_counts),
            "events": list(self.history),
        }
