"""Cancellable playback for one fixed account/output pair, without device protocols."""

from __future__ import annotations

import asyncio
import logging
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
from .support import private_id, safe_state
from .timeline import Timeline

START_TIMEOUT = 20.0
COMPAT_PLAY_DELAY = 2.0
SEEK_TIMEOUT = 5.0
ESTIMATED_END_GRACE = 5.0
_LOGGER = logging.getLogger(__name__)


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
    feedback_mode: str = "standard"
    unconfirmed_end: str = "manual"

    def __post_init__(self) -> None:
        if self.confirmation not in {"delivery", "reported"}:
            raise ValueError("Invalid start confirmation policy")
        if self.end_state not in {"idle", "paused", "off"}:
            raise ValueError("Invalid end-state policy")
        if type(self.play_once) is not bool or type(self.weak_end) is not bool:
            raise ValueError("Invalid compatibility flags")
        if self.feedback_mode not in {"standard", "compatibility"}:
            raise ValueError("Invalid playback feedback mode")
        if self.unconfirmed_end not in {"manual", "estimated_duration", "duration_fallback"}:
            raise ValueError("Invalid continuation policy")
        if self.feedback_mode == "standard" and self.unconfirmed_end != "manual":
            raise ValueError("Estimated continuation requires compatibility mode")


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
        self._notify = changed
        self.debug_ref = private_id(str(id(self)))
        self._last_observation: tuple | None = None
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
        self.confirmation_stage: str | None = None
        # Only the two new strategy choices take effect on the next round. The four
        # existing preferences deliberately retain their immediate-update semantics.
        self.feedback_mode = "standard"
        self.unconfirmed_end = "manual"
        self._command_return: float | None = None
        self._first_byte: float | None = None
        self._before_state: State | None = None
        self._local_resume = False
        self._resume_pending = False
        self._seek_command_pending = False
        self._estimate_buffering = False
        self._estimated_end: asyncio.TimerHandle | asyncio.Handle | None = None
        self._estimate_token: object | None = None
        self.estimated_end_blocked_reason: str | None = None
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

    @property
    def compatible(self) -> bool:
        return self.feedback_mode == "compatibility"

    @property
    def duration_fallback(self) -> bool:
        """An explicit opt-in; confirmation alone does not disable this deadline."""
        return self.compatible and self.unconfirmed_end == "duration_fallback"

    @property
    def position_visible(self) -> bool:
        return self.started or (
            self.compatible and self.owned and self.confirmation_stage == "assumed"
        )

    def _cancel_estimated(self, reason: str) -> None:
        self._estimate_token = None
        if self._estimated_end is not None:
            self._estimated_end.cancel()
            self._estimated_end = None
            self.record("estimated_end_cancelled", reason)

    def _estimate_blocked(self) -> str | None:
        if not self.owned or self.closed:
            return "lost_owner"
        if not self.compatible or self.unconfirmed_end == "manual":
            return "disabled"
        if self.confirmation_stage == "confirmed" and not self.duration_fallback:
            return "confirmed"
        if self.confirmation_stage not in {"awaiting", "assumed", "confirmed"}:
            return "inactive"
        if (
            self.intent == "seek"
            or self.timeline.seek_target is not None
            or self._seek_command_pending
        ):
            return "seek_pending"
        if self.intent != "play":
            return "paused" if self.intent == "pause" else "inactive"
        if self.duration_fallback and self.phase == "paused":
            return "paused"
        if self._resume_pending:
            return "resume_pending"
        if self._estimate_buffering:
            return "buffering"
        if self._ended_round == self.round_id or self.queue.current is None:
            return "inactive"
        if self._command_return is None:
            return "command_pending"
        if self._first_byte is None:
            return "no_delivery"
        if self.timeline.duration is None:
            return "duration_unknown"
        return None

    def _sync_estimated(self) -> None:
        """One cancellable handle; callbacks also validate the complete round token."""
        if not self.compatible:
            return
        if self._command_return is not None and self._first_byte is not None:
            self.timeline.start_estimate(max(self._command_return, self._first_byte))
            if (
                self.intent != "play"
                or self._estimate_buffering
                or self._resume_pending
                or self._seek_command_pending
                or (self.duration_fallback and self.phase == "paused")
            ):
                self.timeline.freeze_estimate()
        blocked = self._estimate_blocked()
        if blocked != self.estimated_end_blocked_reason:
            self.estimated_end_blocked_reason = blocked
            if blocked is not None and self.unconfirmed_end != "manual":
                self.record("estimated_end_blocked", blocked)
        if blocked is not None:
            self._cancel_estimated(blocked)
            return
        if self._estimated_end is not None:
            return
        token = self._estimate_token = object()
        generation, round_id, item_id = self.generation, self.round_id, self.queue.current_id

        def eligible() -> bool:
            return (
                token is self._estimate_token
                and self._valid(generation)
                and round_id == self.round_id
                and item_id == self.queue.current_id
                and self._estimate_blocked() is None
            )

        def finish() -> None:
            if not eligible():
                if token is self._estimate_token:
                    self._cancel_estimated(self._estimate_blocked() or "stale_round")
                return
            self._estimated_end = None
            self._estimate_token = None
            self._finish_round_once("estimated_end")

        def due() -> None:
            if eligible():
                # Give already queued explicit intents and output feedback priority
                # over inference in this event-loop turn, then check every guard again.
                self._estimated_end = self.hass.loop.call_soon(finish)
            elif token is self._estimate_token:
                self._cancel_estimated(self._estimate_blocked() or "stale_round")

        assert self.timeline.duration is not None
        grace = 0.0 if self.duration_fallback else ESTIMATED_END_GRACE
        remaining = self.timeline.duration + grace - self.timeline.estimated_elapsed()
        self._estimated_end = self.hass.loop.call_later(max(0, remaining), due)
        self.record(
            "estimated_end_armed", "duration" if self.duration_fallback else "duration_plus_grace"
        )

    def _finish_round_once(self, reason: str) -> None:
        if self._ended_round == self.round_id:
            return
        self._ended_round = self.round_id
        if reason == "estimated_end":
            # A short track can finish while its startup waiter is still pending.
            # Invalidate that waiter even at the end of the queue.
            self._invalidate("play")
        else:
            self._cancel_estimated("confirmed")
        self.phase, self.reason, self.started = "idle", reason, False
        self.record("end", reason)
        self._advance = self.hass.async_create_background_task(
            self._auto_advance(self.generation), "FeiNiu natural queue advance"
        )

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
        _LOGGER.debug(
            "Playback session=%s output=%s event=%s reason=%s round=%s generation=%s revision=%s queue_length=%s",
            self.debug_ref,
            private_id(self.output.binding.key),
            event,
            reason,
            self.round_id,
            self.generation,
            self.queue.revision,
            len(self.queue.items),
        )

    def changed(self) -> None:
        """Log operational changes, not each position/volume update or media identity."""
        state = self.output.state
        identity_class = (
            self.identity if self.identity in {"matched", "foreign", "unknown"} else "unknown"
        )
        observation = (
            safe_state(state.state if state else None),
            self.phase,
            self.reason,
            identity_class,
            self.confirmation,
            self.started,
            self.owned,
            self.queue.revision,
        )
        if observation != self._last_observation:
            self._last_observation = observation
            _LOGGER.debug(
                "Playback observation session=%s state=%s phase=%s reason=%s identity_class=%s confirmation=%s started=%s owned=%s revision=%s",
                self.debug_ref,
                *observation,
            )
        self._notify()

    def _invalidate(self, intent: str) -> int:
        self._cancel_estimated(intent)
        self._resume_pending = False
        self._seek_command_pending = False
        if intent in {"stop", "unload", "detach", "failure"}:
            self._estimate_buffering = False
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
        self.confirmation_stage = None
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
        self.record("detach", reason)
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
            self.record("selection", "resolved")
            self.queue.enqueue(rows[start:], mode)
            self.record("queue", mode)
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
            self.record("selection", "resolved")
            play = self.queue.enqueue(rows, mode, start)
            self.record("queue", mode)
            if play:
                await self._load(generation)
            else:
                self.phase, self.reason = "idle", "empty_queue"
                self.leases.release(self.output.binding.key, self)
                self.changed()

        await self._await_operation(generation, work())

    async def start(self, *, context: Context | None = None) -> None:
        self._context = context
        target = self.output.state
        if self.compatible and self.owned and self._issued and self._command_return is not None:
            if self.intent == "pause" or self.phase == "paused":
                generation = self._invalidate("play")
                await self._await_operation(generation, self._resume(generation))
                return
            if self.intent == "play":
                return
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
        if self.compatible and not self.output.features & Feature.PLAY:
            raise ServiceValidationError("Output cannot resume at this time")
        self.phase, self.reason = "loading", "resuming"
        self._local_resume = self.compatible
        self._resume_pending = self.compatible
        self._sync_estimated()
        self.changed()
        await self._send(generation, "media_play")
        if self.compatible:
            self._resume_pending = False
            if self._estimate_buffering:
                self.phase, self.reason = "buffering", "output_buffering"
            elif self._local_resume:
                self.phase, self.reason = "playing", "resume_requested"
            if self.confirmation_stage == "awaiting":
                self.confirmation_stage = "assumed"
            if not self._estimate_buffering:
                self.timeline.resume_estimate()
                if self.confirmation_stage == "confirmed":
                    self.timeline.resume()
                else:
                    self.timeline.show_estimate(moving=True)
            self._sync_estimated()
            self.changed()
            return
        await self._wait_ready(START_TIMEOUT)
        self._check(generation)

    async def _wait_ready(self, seconds: float) -> None:
        await asyncio.wait_for(self._ready.wait(), seconds)

    async def _send(self, generation: int, service: str, data: dict | None = None) -> None:
        self._check(generation)
        self.record("command", service)
        await self.output.send(service, data, context=self._context)
        self._check(generation)
        self.record("command_returned", service)

    async def _load(self, generation: int) -> None:
        self._check(generation)
        item = self.queue.current
        if item is None:
            return
        self.cancel_streams()
        self.round_id += 1
        self._prepare_load()
        self.feedback_mode = self.profile.feedback_mode
        self.unconfirmed_end = self.profile.unconfirmed_end
        self._command_return = self._first_byte = None
        self._local_resume = self._estimate_buffering = False
        self.estimated_end_blocked_reason = None
        self._audio, self.started, self._issued = False, False, False
        self._raw_samples = 0
        self.stream_counts = {}
        self._ready.clear()
        self.identity, self.confirmation = "unknown", "unconfirmed"
        self.phase, self.reason = "loading", "resolving_track"
        self.timeline.reset(self.round_id)
        self.record("round", "resolve_started")
        self.changed()
        request = await self.resolve(item, self.round_id)
        self._check(generation)
        if self.queue.current_id != item.item_id:
            raise asyncio.CancelledError
        self.record("round", "resolve_completed")
        self.timeline.reset(self.round_id, request.duration)
        self._expected = request.url
        target = self.output.state
        self._before_state = target
        self._source = self._source_of(target) if target else None
        value = target.attributes.get("media_content_id") if target else None
        self._before_command = value if isinstance(value, str) else None
        self._issued = True
        self._controlled = True
        self.confirmation_stage = "awaiting"
        await self._send(
            generation,
            "play_media",
            {
                "media_content_id": request.url,
                "media_content_type": request.content_type,
                "extra": request.extra,
            },
        )
        self._command_return = self.timeline.clock()
        self._sync_estimated()
        # Events were processed even during the command; inspect the final snapshot too.
        self.observe(None, self.output.state)
        self._check(generation)
        if self.profile.play_once and not self._ready.is_set():
            try:
                await self._wait_ready(COMPAT_PLAY_DELAY)
            except TimeoutError:
                self._check(generation)
                target = self.output.state
                if self.intent == "play" and target and self._matches(target) == "matched":
                    if self.output.features & Feature.PLAY:
                        self.record("compatibility", "one_standard_play_after_load")
                        await self._send(generation, "media_play")
        try:
            await self._wait_ready(START_TIMEOUT)
        except TimeoutError:
            if self.compatible:
                self._check(generation)
                if self.confirmation_stage == "confirmed":
                    return
                self.confirmation_stage = "assumed"
                self.phase, self.reason = "playing", "start_unconfirmed_retained"
                self.timeline.show_estimate(moving=not self._estimate_buffering)
                if self._estimate_buffering:
                    self.phase = "buffering"
                self.record("timeout_degraded", "start_unconfirmed_retained")
                self._sync_estimated()
                self.changed()
                return
            self.reason = "start_unconfirmed"
            self.record("timeout", "start_unconfirmed")
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
        self.record("stream", event)
        if event == "first_byte":
            self._audio = True
            if self._first_byte is None:
                self._first_byte = self.timeline.clock()
            self.observe(None, self.output.state)
            self._sync_estimated()
        elif event == "error":
            self._fail("stream_failed")
        # EOF is delivery completion, not acoustic completion or a queue-advance signal.
        self.changed()

    def observe(self, old: State | None, new: State | None) -> None:
        if self.closed:
            return
        if not self.owned:
            self._cancel_estimated("lost_owner")
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
        if self.compatible and self._ended_round == self.round_id:
            return
        actual = new.attributes.get("media_content_id")
        if isinstance(actual, str) and identity == "foreign":
            retired = any(_identity_url(actual) == _identity_url(url) for url in self._retired)
            loading_previous = (
                not self.started
                and (
                    self.phase == "loading"
                    or (
                        self.compatible
                        and self._before_state is not None
                        and new.last_updated <= self._before_state.last_updated
                    )
                )
                and self._before_command is not None
                and _identity_url(actual) == _identity_url(self._before_command)
            )
            if retired or loading_previous:
                self.record("observation", "previous_round_ignored")
                return
        source = self._source_of(new)
        if identity == "foreign" or (
            (self.started or (self.compatible and self._command_return is not None))
            and identity == "unknown"
            and self._source is not None
            and source != self._source
            and any(source)
        ):
            self.detach("external_media")
            return
        self.identity = identity
        if self.compatible and identity == "unknown" and self._before_state is not None:
            # A repeated vendor ID is not a round token. A cached pre-command
            # snapshot cannot confirm the new load merely because first_byte arrived.
            if new.last_updated <= self._before_state.last_updated:
                return
        evidence = identity == "matched" or (identity == "unknown" and self._audio)
        if not evidence:
            self.reason = "awaiting_media_identity"
            self.changed()
            return
        was_playing = old is not None and old.state == "playing"
        old_position = self.timeline.position()
        duration = self.timeline.duration
        timeline_state = new.state
        if self.compatible and self.intent == "pause":
            timeline_state = "paused"
        elif (
            self.compatible
            and self.intent == "play"
            and new.state == "paused"
            and (self.confirmation_stage != "confirmed" or self._local_resume)
            and not self._estimate_buffering
            and not self._resume_pending
        ):
            timeline_state = "playing"
        if self.timeline.observe(self.round_id, timeline_state, new.attributes):
            self._raw_samples += 1
        if self.intent == "seek" and self.timeline.seek_target is None:
            self.intent = self._seek_return_intent
            self._sync_seek_estimate(accepted=True)
            if self._seek:
                self._seek.cancel()
                self._seek = None
        if new.state == "playing" and self.intent not in {"pause", "stop", "seek"}:
            confirmed = (
                self.profile.confirmation == "reported" or self._audio or self._raw_samples >= 2
            )
            if confirmed:
                previously_confirmed = self.started
                late = self.confirmation_stage == "assumed"
                self.confirmation_stage = "confirmed"
                self._local_resume = False
                self._estimate_buffering = False
                if not self.duration_fallback:
                    self._cancel_estimated("confirmed")
                    self.estimated_end_blocked_reason = "confirmed"
                elif not self._resume_pending:
                    self.timeline.resume_estimate()
                self.started = True
                self.phase, self.reason = "playing", "output_reported_playing"
                if late:
                    self.reason = "late_confirmed"
                self.confirmation = (
                    "delivery"
                    if self._audio
                    else ("native_samples" if self._raw_samples >= 2 else "reported")
                )
                self._source = source
                self.timeline.confirm(self.round_id, estimate_from_start=self._audio)
                self._ready.set()
                if not previously_confirmed:
                    self.record("confirmed", self.confirmation)
                    if late:
                        self.record("late_confirmed", self.confirmation)
            else:
                self.phase, self.reason = "loading", "reported_without_delivery"
        elif (
            new.state == self.profile.end_state
            and self.started
            and was_playing
            and not (self.compatible and self._local_resume)
        ):
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
                self._finish_round_once("natural_end")
            elif self.intent not in {"pause", "stop", "seek"}:
                self.detach("end_not_confirmed")
                return
        elif (
            new.state == "paused"
            and (self.started or self.intent == "pause")
            and not (self.compatible and self._local_resume and self.intent == "play")
        ):
            self.phase, self.reason = "paused", "output_paused"
        elif new.state == "buffering" and self.started:
            self.phase, self.reason = "buffering", "output_buffering"
        elif (
            new.state in {"idle", "off"}
            and self.started
            and self.intent not in {"pause", "stop", "seek"}
            and not (self.compatible and self._local_resume)
        ):
            self.detach("output_stopped")
            return
        if self.compatible:
            if new.state == "buffering":
                self._estimate_buffering = True
                self.timeline.freeze_estimate()
                self.timeline.freeze("output_buffering")
                self.phase, self.reason = "buffering", "output_buffering"
            elif new.state == "playing" and self._estimate_buffering:
                self._estimate_buffering = False
                if not self._resume_pending:
                    self.timeline.resume_estimate()
            self._sync_estimated()
            if self.confirmation_stage == "assumed" and self.intent == "play":
                self.timeline.show_estimate(
                    moving=not self._estimate_buffering and not self._resume_pending
                )
        self.changed()

    async def _auto_advance(self, generation: int) -> None:
        if not self._valid(generation) or self.intent != "play":
            return
        self.record("advance", "automatic")
        if self.queue.advance(natural=True) is None:
            if self.duration_fallback and self.reason == "estimated_end":
                # The device may still be looping its one-item list. Stop only our
                # current owned round, using public HA capabilities, at queue end.
                self.cancel_streams()
                service = "media_stop" if self.output.features & Feature.STOP else "media_pause"
                if self.output.features & (Feature.STOP | Feature.PAUSE):
                    try:
                        await self._send(generation, service)
                    except HomeAssistantError:
                        if self._valid(generation):
                            self._fail("stop_unconfirmed")
                        return
                self._check(generation)
            self.phase, self.reason = "ended", "queue_ended"
            self.record("end", "queue_ended")
            self.timeline.freeze("queue_ended")
            self.leases.release(self.output.binding.key, self)
            self.changed()
            return
        new_generation = self._invalidate("play")
        self._prepare_load()
        try:
            await self._await_operation(new_generation, self._load(new_generation))
        except (HomeAssistantError, FeiNiuError, ValueError, TimeoutError):
            # _await_operation already records the classified failure; do not skip items.
            return

    async def next(self, *, previous: bool = False) -> None:
        generation = self._invalidate("play")
        item = self.queue.previous() if previous else self.queue.advance()
        self.record("queue", "previous" if previous else "next")
        if item is None:
            await self.stop()
            return
        self._claim()
        self._prepare_load()
        await self._await_operation(generation, self._load(generation))

    async def jump(self, item_id: str, revision: int) -> None:
        self.queue.jump(item_id, revision)
        self.record("queue", "jump")
        generation = self._invalidate("play")
        self._claim()
        self._prepare_load()
        await self._await_operation(generation, self._load(generation))

    async def pause(self) -> None:
        generation = self._invalidate("pause")
        if self.compatible:
            self.timeline.freeze_estimate()
        self.timeline.freeze("pause_requested")
        self.reason = "pause_requested"
        if self.owned and self._controlled:
            if not self.output.features & Feature.PAUSE:
                self._fail("pause_unsupported")
                raise ServiceValidationError("Output cannot pause at this time")
            try:
                await self._send(generation, "media_pause")
            except HomeAssistantError:
                self._check(generation)
                self._fail("pause_unconfirmed")
                raise
            if not self._issued:
                self.phase, self.reason = "idle", "loading_cancelled"
                self._controlled = False
                self.cancel_streams()
                self.leases.release(self.output.binding.key, self)
            elif self.compatible:
                self.phase, self.reason = "paused", "pause_requested"
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
            self.record("queue", "clear")
        self.cancel_streams()
        try:
            if self.owned and self._controlled:
                await self._send(generation, "media_stop")
        except HomeAssistantError:
            self._check(generation)
            self.phase, self.reason = "failed", "stop_unconfirmed"
            raise
        finally:
            if generation == self.generation and not self.closed:
                self._controlled = False
                self.leases.release(self.output.binding.key, self)
                self.changed()

    async def seek(self, position: float) -> None:
        if self.compatible and self.confirmation_stage != "confirmed":
            raise ServiceValidationError(
                translation_domain="feiniu_music", translation_key="playback_unconfirmed"
            )
        if not self.owned or not self.started or not self.output.features & Feature.SEEK:
            raise ServiceValidationError("Output cannot seek this playback")
        self._seek_return_intent = (
            "pause" if self.output.state and self.output.state.state == "paused" else "play"
        )
        if self.duration_fallback and (self.intent == "pause" or self.phase == "paused"):
            self._seek_return_intent = "pause"
        self.timeline.request_seek(position)
        if self.duration_fallback:
            self.timeline.freeze_estimate()
        generation = self._invalidate("seek")
        self._seek_command_pending = self.duration_fallback
        try:
            await self._send(generation, "media_seek", {"seek_position": position})
        except HomeAssistantError:
            if self.duration_fallback:
                self._check(generation)
                self._seek_command_pending = False
            self.timeline.reject_seek()
            self.intent = self._seek_return_intent
            self._sync_seek_estimate(accepted=False)
            self.changed()
            raise
        self._seek_command_pending = False
        if self.timeline.seek_target is None:
            self.intent = self._seek_return_intent
            self._sync_seek_estimate(accepted=False)
        else:

            async def expire() -> None:
                await asyncio.sleep(SEEK_TIMEOUT)
                if self._valid(generation):
                    self.timeline.reject_seek()
                    self.intent = self._seek_return_intent
                    self._sync_seek_estimate(accepted=False)
                    self.changed()

            self._seek = self.hass.async_create_background_task(
                expire(), "FeiNiu seek confirmation"
            )
        self.changed()

    def _sync_seek_estimate(self, *, accepted: bool) -> None:
        """Only a locally requested, acknowledged seek can rebase the fallback clock."""
        if not self.duration_fallback:
            return
        position = self.timeline.position()
        if accepted and position is not None:
            self.timeline.seek_estimate(position)
        if self.intent == "play" and not self._estimate_buffering and not self._resume_pending:
            self.timeline.resume_estimate()
        self._sync_estimated()

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
            "ref": self.debug_ref,
            "profile": asdict(self.profile),
            "phase": self.phase,
            "reason": self.reason,
            "intent": self.intent,
            "generation": self.generation,
            "round": self.round_id,
            "queue_revision": self.queue.revision,
            "queue_length": len(self.queue.items),
            "queue_position": self.queue.position,
            "started": self.started,
            "closed": self.closed,
            "has_duration": self.timeline.duration is not None,
            "has_position": self.timeline.position() is not None,
            "owned": self.owned,
            "identity": self.identity
            if self.identity in {"matched", "foreign", "unknown"}
            else "unknown",
            "confirmation": self.confirmation,
            "confirmation_stage": self.confirmation_stage,
            "effective_feedback_mode": self.feedback_mode,
            "effective_unconfirmed_end": self.unconfirmed_end,
            "estimated_end_armed": self._estimated_end is not None,
            "estimated_end_blocked_reason": self.estimated_end_blocked_reason,
            "position_source": self.timeline.source,
            "timeline_reason": self.timeline.reason,
            "output_state": safe_state(self.output.state.state if self.output.state else None),
            "features": int(self.output.features),
            "stream_events": dict(self.stream_counts),
            "events": list(self.history),
        }
