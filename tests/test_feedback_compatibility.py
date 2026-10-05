"""Controlled clocks and HA State objects; no real speakers or wall-clock sleeps."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from itertools import product
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from homeassistant.components.media_player import MediaPlayerEntityFeature as Feature
from homeassistant.core import State
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from custom_components.feiniu_music.output import OutputBinding, OutputLeases
from custom_components.feiniu_music.queue import QueueItem
from custom_components.feiniu_music.session import OutputProfile, PlaybackRequest, PlaybackSession
from custom_components.feiniu_music.timeline import Timeline

PROFILES = [
    OutputProfile(*values)
    for values in product(
        ("delivery", "reported"), (False, True), ("idle", "paused", "off"), (False, True)
    )
]


class Clock:
    def __init__(self):
        self.now = 100.0
        self.handles = []

    def utcnow(self):
        return datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=self.now)

    def call_later(self, delay, callback):
        handle = asyncio.TimerHandle(self.now + delay, callback, (), asyncio.get_running_loop())
        self.handles.append(handle)
        return handle

    def call_soon(self, callback):
        return self.call_later(0, callback)

    def advance(self, seconds):
        self.now += seconds
        # Snapshot: a deferred finish executes only in the next controlled turn.
        due = [h for h in self.handles if h.when() <= self.now]
        self.handles = [h for h in self.handles if h not in due]
        for handle in sorted(due, key=lambda h: h.when()):
            if not handle.cancelled():
                handle._run()


class Output:
    binding = OutputBinding("entity:media_player.synthetic", "media_player.synthetic")
    entity_id = binding.entity_id
    features = Feature.PLAY_MEDIA | Feature.PLAY | Feature.PAUSE | Feature.STOP | Feature.SEEK

    def __init__(self, clock):
        self.clock = clock
        self.calls = []
        self.state = State(self.binding.entity_id, "paused", {}, last_updated=clock.utcnow())
        self.observe = None
        self.hook = None

    def subscribe(self, observe):
        self.observe = observe

    def close(self):
        self.observe = None

    def report(self, state, media_id=None, **attrs):
        old = self.state
        self.state = State(
            self.binding.entity_id,
            state,
            {
                "media_content_id": media_id,
                **attrs,
            },
            last_updated=self.clock.utcnow(),
        )
        if self.observe:
            self.observe(old, self.state)

    async def send(self, service, data=None, **kwargs):
        self.calls.append((service, data))
        if self.hook:
            await self.hook(service, data)


class Harness:
    def __init__(self, profile, duration=240):
        self.clock = Clock()
        self.output = Output(self.clock)
        self.cancel = Mock()
        self.resolve = Mock()
        self.duration = duration
        self.waiters = []

        async def resolve(item, round_id):
            self.resolve(item, round_id)
            return PlaybackRequest(
                f"http://synthetic.invalid/{round_id}/{item.item_id}", "music", {}, self.duration
            )

        self.session = PlaybackSession(
            SimpleNamespace(
                loop=self.clock,
                async_create_background_task=lambda coro, name: asyncio.create_task(coro),
            ),
            self.output,
            OutputLeases(),
            resolve,
            Mock(),
            profile=profile,
            timeline=Timeline(lambda: self.clock.now, self.clock.utcnow),
            cancel_streams=self.cancel,
        )
        self.session.queue.replace([QueueItem.create(str(i)) for i in range(3)])

        async def wait_ready(seconds):
            if self.session._ready.is_set():
                return
            future = asyncio.get_running_loop().create_future()
            self.waiters.append((seconds, future))
            ready = asyncio.create_task(self.session._ready.wait())
            try:
                done, _ = await asyncio.wait([future, ready], return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    task.result()
            finally:
                ready.cancel()
                future.cancel()
                await asyncio.gather(ready, return_exceptions=True)

        self.session._wait_ready = wait_ready

    async def settle(self):
        for _ in range(12):
            await asyncio.sleep(0)

    async def begin(self):
        task = asyncio.create_task(self.session.start())
        await self.settle()
        return task

    async def expire(self, task):
        self.clock.advance(20)
        for _, future in self.waiters:
            if not future.done():
                future.set_exception(TimeoutError())
        await task

    def byte(self):
        self.session.stream_event(self.session.round_id, "first_byte")

    def playing(self, *, vendor=False, position=None):
        attrs = (
            {}
            if position is None
            else {"media_position": position, "media_position_updated_at": self.clock.utcnow()}
        )
        self.output.report("playing", "vendor-fixed" if vendor else self.session._expected, **attrs)

    async def tick(self, seconds):
        self.clock.advance(seconds)
        self.clock.advance(0)
        await self.settle()


@pytest.fixture
async def make():
    harnesses = []

    def create(*, estimated=False, profile=None, duration=240):
        harness = Harness(
            profile
            or OutputProfile(
                feedback_mode="compatibility",
                unconfirmed_end="estimated_duration" if estimated else "manual",
            ),
            duration,
        )
        harnesses.append(harness)
        return harness

    yield create
    for harness in harnesses:
        await harness.session.close()
        await harness.settle()
        assert all(h.cancelled() for h in harness.clock.handles)


@pytest.mark.parametrize("profile", PROFILES)
async def test_all_24_standard_profiles_fast_confirmation_and_end(make, profile):
    h = make(profile=profile)
    task = await h.begin()
    h.byte()
    h.playing(position=0)
    await task
    s = h.session
    assert s.started and s.phase == "playing" and s.owned
    assert s.feedback_mode == "standard" and s.unconfirmed_end == "manual"
    assert s._estimated_end is None
    await h.tick(239)
    h.playing(position=239)
    h.output.report(profile.end_state, s._expected)
    await h.settle()
    assert s.round_id == 2 and s.queue.position == 1
    assert [e for e in s.history if e["event"] == "advance"][-1]["reason"] == "automatic"


@pytest.mark.parametrize("profile", PROFILES)
async def test_all_24_standard_profiles_timeout_release_and_no_late_revival(make, profile):
    h = make(profile=profile)
    task = await h.begin()
    # Exercise the optional one-shot Play gate with a matched paused snapshot.
    h.output.report("paused", h.session._expected)
    if profile.play_once:
        h.waiters[-1][1].set_exception(TimeoutError())
        await h.settle()
    with pytest.raises(HomeAssistantError):
        await h.expire(task)
    count = h.cancel.call_count
    assert h.session.phase == "failed" and h.session.reason == "start_unconfirmed"
    assert not h.session.owned
    await h.tick(10)
    h.byte()
    h.playing()
    assert not h.session.started and h.cancel.call_count == count
    assert [c[0] for c in h.output.calls].count("media_play") == int(profile.play_once)
    assert all(c[0] != "media_stop" for c in h.output.calls)


async def test_manual_timeout_late_confirmation_keeps_round_and_lease(make):
    h = make()
    task = await h.begin()
    h.byte()
    await h.expire(task)
    s = h.session
    assert (s.confirmation_stage, s.phase, s.owned) == ("assumed", "playing", True)
    count = h.cancel.call_count
    await h.tick(10)
    h.playing()
    assert s.confirmation_stage == "confirmed" and s.timeline.source == "estimated"
    assert s.round_id == 1 and h.resolve.call_count == 1 and h.cancel.call_count == count
    h.playing()
    assert sum(e["event"] == "late_confirmed" for e in s.history) == 1


@pytest.mark.parametrize("vendor", [False, True])
@pytest.mark.parametrize("confirmed", [False, True])
@pytest.mark.parametrize("end_state", ["idle", "paused", "off"])
@pytest.mark.parametrize("weak_end", [False, True])
async def test_compatible_resume_never_reloads_even_after_late_confirmation(
    make, vendor, confirmed, end_state, weak_end
):
    h = make(
        profile=OutputProfile(
            feedback_mode="compatibility",
            unconfirmed_end="estimated_duration",
            end_state=end_state,
            weak_end=weak_end,
        )
    )
    task = await h.begin()
    h.byte()
    await h.expire(task)
    if confirmed:
        h.playing(vendor=vendor)
    await h.session.pause()
    frozen = h.session.timeline.position()
    assert h.session.phase == "paused" and h.session._estimated_end is None
    await h.tick(500)
    assert h.session.timeline.position() == frozen
    await h.session.start()
    h.output.report("paused", "vendor-fixed" if vendor else h.session._expected)
    await h.tick(30)
    assert h.session.round_id == 1 and h.resolve.call_count == 1
    assert [c[0] for c in h.output.calls] == ["play_media", "media_pause", "media_play"]
    assert h.session.owned and h.session.phase == "playing"
    assert (h.session._estimated_end is None) == confirmed


@pytest.mark.parametrize("first_byte_before", [False, True])
async def test_estimate_zero_later_of_command_and_delivery_and_exact_grace(make, first_byte_before):
    h = make(estimated=True, duration=10)
    gate = asyncio.get_running_loop().create_future()

    async def command(service, data):
        if service == "play_media":
            await gate

    h.output.hook = command
    task = await h.begin()
    if first_byte_before:
        h.byte()
        h.clock.advance(7)
    gate.set_result(None)
    await h.settle()
    if not first_byte_before:
        h.clock.advance(7)
        h.byte()
    assert h.session._estimated_end.when() == 122
    for event in ("eof", "get", "eof", "first_byte", "eof"):
        h.session.stream_event(1, event)
    await h.tick(10)
    assert h.session.round_id == 1
    await h.tick(4.999)
    assert h.session.round_id == 1
    await h.tick(0.001)
    assert h.session.round_id == 2 and h.session.queue.position == 1
    await task  # Short-track inference cancels its still-pending startup wait.
    assert (
        sum(e["event"] == "end" and e["reason"] == "estimated_end" for e in h.session.history) == 1
    )


@pytest.mark.parametrize("duration", [None, 0, -1, float("nan"), float("inf"), True, "10"])
async def test_invalid_duration_keeps_session_but_never_schedules(make, duration):
    h = make(estimated=True, duration=duration)
    task = await h.begin()
    h.byte()
    await h.expire(task)
    await h.tick(10000)
    assert h.session.owned and h.session.round_id == 1
    assert h.session._estimated_end is None
    assert h.session.estimated_end_blocked_reason == "duration_unknown"


@pytest.mark.parametrize("events", [[], ["head"], ["get"], ["head", "get", "eof"]])
async def test_no_first_byte_is_never_eligible(make, events):
    h = make(estimated=True)
    task = await h.begin()
    for event in events:
        h.session.stream_event(1, event)
    await h.expire(task)
    await h.tick(10000)
    assert h.session.owned and h.session.round_id == 1
    assert h.session._estimated_end is None


async def test_manual_never_automatically_advances(make):
    h = make()
    task = await h.begin()
    h.byte()
    await h.expire(task)
    await h.tick(10000)
    assert h.session.owned and h.session.queue.position == 0
    await h.session.stop()
    assert not h.session.owned


async def test_pause_during_grace_preserves_unclamped_elapsed(make):
    h = make(estimated=True, duration=10)
    task = await h.begin()
    h.byte()
    await h.tick(12)
    await h.session.pause()
    await task
    assert h.session.timeline.estimated_elapsed() == 12
    await h.tick(300)
    await h.session.start()
    await h.tick(2.999)
    assert h.session.round_id == 1
    await h.tick(0.001)
    assert h.session.round_id == 2


@pytest.mark.parametrize("same_tick", [False, True])
async def test_late_confirmation_has_priority_over_estimated_inference(make, same_tick):
    h = make(estimated=True, duration=30)
    task = await h.begin()
    h.byte()
    await h.expire(task)
    if same_tick:
        h.clock.advance(15)  # due() queued finish(), not yet consumed
    h.playing(position=20)
    await h.tick(100)
    assert h.session.round_id == 1 and h.session._estimated_end is None
    assert h.session.confirmation_stage == "confirmed" and h.session.timeline.source == "native"


@pytest.mark.parametrize(
    "action",
    ["next", "previous", "new", "stop", "close", "error", "unavailable", "foreign", "displace"],
)
async def test_terminal_intent_invalidates_even_already_queued_timer(make, action):
    h = make(estimated=True, duration=10)
    task = await h.begin()
    h.byte()
    timer = h.session._estimated_end
    # Preserve the old callback to simulate cancellation losing a scheduling race.
    callback = timer._callback
    s = h.session
    next_task = None
    if action in {"next", "previous"}:
        next_task = asyncio.create_task(s.next(previous=action == "previous"))
    elif action == "new":
        next_task = asyncio.create_task(s.jump(s.queue.order[2], s.queue.revision))
    elif action == "stop":
        await s.stop()
    elif action == "close":
        await s.close()
    elif action == "error":
        s.stream_event(1, "error")
    elif action == "unavailable":
        h.output.report("unavailable")
    elif action == "foreign":
        h.output.report("playing", "http://foreign.invalid/track")
    else:
        s.leases.claim(s.output.binding.key, object(), lambda: None)
    await h.settle()
    position, round_id = s.queue.position, s.round_id
    callback()
    await h.tick(10000)
    assert (s.queue.position, s.round_id) == (position, round_id)
    await task
    if next_task:
        await s.stop()
        await next_task


async def test_unconfirmed_seek_rejects_without_touching_deadline(make):
    h = make(estimated=True)
    task = await h.begin()
    h.byte()
    await h.expire(task)
    handle = h.session._estimated_end
    with pytest.raises(ServiceValidationError):
        await h.session.seek(50)
    assert h.session._estimated_end is handle
    assert all(c[0] != "media_seek" for c in h.output.calls)
    h.playing(position=20)
    await h.session.seek(50)
    assert h.output.calls[-1] == ("media_seek", {"seek_position": 50})


async def test_retired_url_and_repeated_vendor_id_cannot_confirm_new_round(make):
    h = make(estimated=True)
    task = await h.begin()
    h.byte()
    await h.expire(task)
    h.playing(vendor=True)
    old = h.output.state
    old_url = h.session._expected
    next_task = asyncio.create_task(h.session.next())
    await h.settle()
    h.byte()  # Cached vendor snapshot must not be promoted to new-round confirmation.
    h.session.observe(None, old)
    h.output.report("playing", old_url)
    h.output.report("paused", old_url)
    assert h.session.confirmation_stage == "awaiting" and h.session.owned
    assert h.session._estimated_end is not None
    await h.session.stop()
    await next_task


async def test_buffering_freezes_and_eof_cannot_restart_estimate(make):
    h = make(estimated=True)
    task = await h.begin()
    h.byte()
    await h.expire(task)
    h.output.report("buffering", h.session._expected)
    frozen = h.session.timeline.estimated_elapsed()
    for _ in range(4):
        h.session.stream_event(1, "eof")
        await h.tick(100)
    assert h.session.timeline.estimated_elapsed() == frozen
    assert h.session._estimated_end is None and h.session.phase == "buffering"


@pytest.mark.parametrize("repeat,shuffle", [("one", False), ("all", False), ("off", True)])
async def test_estimated_end_uses_current_queue_order_once(make, repeat, shuffle):
    h = make(estimated=True, duration=10)
    s = h.session
    if repeat == "all":
        s.queue.jump(s.queue.order[-1], s.queue.revision)
    task = await h.begin()
    h.byte()
    s.queue.set_repeat(repeat)
    s.queue.set_shuffle(shuffle)
    before = s.queue.current_id
    expected = (
        before if repeat == "one" else s.queue.order[(s.queue.position + 1) % len(s.queue.order)]
    )
    await h.tick(15)
    await task
    assert s.round_id == 2 and s.queue.current_id == expected


async def test_new_strategies_snapshot_but_legacy_preferences_stay_live(make):
    h = make(estimated=True)
    task = await h.begin()
    h.byte()
    await h.expire(task)
    handle = h.session._estimated_end
    h.session.profile = replace(
        h.session.profile,
        feedback_mode="standard",
        unconfirmed_end="manual",
        confirmation="reported",
        end_state="off",
        weak_end=True,
    )
    assert h.session.compatible and h.session._estimated_end is handle
    h.playing()
    h.output.report("off", h.session._expected)
    await h.settle()
    assert h.session.round_id == 2 and not h.session.compatible


def test_invalid_standard_estimation_is_rejected():
    with pytest.raises(ValueError):
        OutputProfile(unconfirmed_end="estimated_duration")


@pytest.mark.parametrize("stage", ["awaiting", "assumed", "confirmed"])
async def test_stream_error_is_terminal_at_every_compatibility_stage(make, stage):
    h = make(estimated=True)
    task = await h.begin()
    h.byte()
    if stage != "awaiting":
        await h.expire(task)
    if stage == "confirmed":
        h.playing()
    h.session.stream_event(1, "error")
    await task
    assert h.session.phase == "failed" and not h.session.owned
    assert h.session._estimated_end is None
    await h.tick(10000)
    assert h.session.round_id == 1


@pytest.mark.parametrize("service", ["play_media", "media_play", "media_pause"])
async def test_service_errors_are_not_mistaken_for_feedback_timeout(make, service):
    h = make(estimated=True)
    if service != "play_media":
        task = await h.begin()
        h.byte()
        await h.expire(task)
        if service == "media_play":
            await h.session.pause()

    async def fail(command, data):
        raise HomeAssistantError("PRIVATE_RAW_ERROR")

    h.output.hook = fail
    with pytest.raises(HomeAssistantError):
        if service == "media_pause":
            await h.session.pause()
        else:
            await h.session.start()
    assert not h.session.owned and h.session.phase == "failed"
    assert h.session._estimated_end is None
    assert "PRIVATE" not in str(h.session.diagnostics())


async def test_confirmation_and_normal_end_win_when_estimate_is_already_due(make):
    h = make(estimated=True, duration=30)
    task = await h.begin()
    h.byte()
    await h.expire(task)
    h.clock.advance(15)
    h.playing(position=30)
    h.output.report("idle", h.session._expected)
    await h.tick(0)
    assert h.session.round_id == 2 and h.session.queue.position == 1
    assert not any(e["reason"] == "estimated_end" for e in h.session.history)


async def test_next_wins_over_due_estimate_and_uses_only_one_queue_advance(make):
    h = make(estimated=True, duration=10)
    task = await h.begin()
    h.byte()
    h.clock.advance(15)
    next_task = asyncio.create_task(h.session.next())
    await h.settle()
    await h.tick(0)
    assert h.session.round_id == 2 and h.session.queue.position == 1
    await task
    await h.session.stop()
    await next_task


@pytest.mark.parametrize("profile", PROFILES)
async def test_all_24_standard_pause_resume_and_seek_keep_existing_semantics(make, profile):
    h = make(profile=profile)
    task = await h.begin()
    h.byte()
    h.playing(position=0)
    await task

    async def report(command, data):
        if command == "media_pause":
            h.output.report("paused", h.session._expected)
        elif command == "media_play":
            h.playing()
        elif command == "media_seek":
            h.playing(position=data["seek_position"])

    h.output.hook = report
    await h.session.pause()
    # Preserve the baseline's end_state=paused branch: explicit Pause freezes its
    # clock but that candidate-end branch leaves the old phase until another report.
    assert h.session.intent == "pause"
    assert h.session.phase == ("playing" if profile.end_state == "paused" else "paused")
    await h.tick(3)
    await h.session.start()
    await h.tick(1)
    await h.session.seek(15)
    assert h.session.round_id == 1 and h.session.timeline.position() == 15
    assert h.session.intent == "play" and h.session._estimated_end is None
    assert [c[0] for c in h.output.calls] == [
        "play_media",
        "media_pause",
        "media_play",
        "media_seek",
    ]


async def test_proxy_seek_features_state_and_estimated_anchor_are_truthful(make):
    from custom_components.feiniu_music.media_player import FeiNiuPlayer
    from custom_components.feiniu_music.storage import SavedSession

    h = make()
    s = h.session
    runtime = SimpleNamespace(
        hass=None, entry=SimpleNamespace(entry_id="synthetic", title="Synthetic")
    )
    saved = SavedSession(h.output.binding, s.queue, s.profile)
    player = FeiNiuPlayer(runtime, saved, s.leases, Mock())
    player.output, player.session = h.output, s
    task = await h.begin()
    h.byte()
    await h.expire(task)
    assert str(player.state) == "playing" and player.assumed_state
    assert not player.supported_features & Feature.SEEK
    assert player.extra_state_attributes["confirmation_stage"] == "assumed"
    assert player.extra_state_attributes["queue_active"]
    assert player.extra_state_attributes["position_source"] == "estimated"
    assert player.media_position == 20
    h.playing(position=21)
    assert not player.assumed_state and player.supported_features & Feature.SEEK
    await s.pause()
    assert player.assumed_state and str(player.state) == "paused"


async def test_estimated_queue_tail_cancels_start_waiter_and_releases_once(make):
    h = make(estimated=True, duration=1)
    h.session.queue.jump(h.session.queue.order[-1], h.session.queue.revision)
    task = await h.begin()
    h.byte()
    await h.tick(6)
    await task
    assert h.session.phase == "ended" and not h.session.owned
    await h.tick(10000)
    assert h.session.phase == "ended" and h.session.round_id == 1


async def test_late_confirmation_at_waiter_timeout_never_downgrades_stage(make):
    h = make()
    task = await h.begin()
    h.byte()
    h.waiters[-1][1].set_exception(TimeoutError())
    h.playing()
    await task
    assert h.session.confirmation_stage == "confirmed"
    assert not any(e["event"] == "timeout_degraded" for e in h.session.history)


async def test_unconfirmed_pause_and_resume_capability_failures_are_explicit(make):
    h = make()
    task = await h.begin()
    await h.expire(task)
    await h.session.pause()
    h.output.features &= ~Feature.PLAY
    with pytest.raises(ServiceValidationError):
        await h.session.start()
    assert not h.session.owned and h.session.phase == "failed"
    assert [c[0] for c in h.output.calls] == ["play_media", "media_pause"]


async def test_resolve_timeout_is_not_degraded_to_assumed(make):
    h = make()

    async def resolve(item, round_id):
        raise TimeoutError

    h.session.resolve = resolve
    with pytest.raises(TimeoutError):
        await h.session.start()
    assert not h.session.owned and h.session.phase == "failed"
    assert not h.output.calls


async def test_delivery_after_timeout_does_not_promote_cached_previous_url_to_takeover(make):
    h = make(estimated=True)
    h.output.report("paused", "http://previous.invalid/track")
    task = await h.begin()
    await h.expire(task)
    h.byte()
    assert h.session.owned and h.session.confirmation_stage == "assumed"
    assert h.session._estimated_end is not None
    h.clock.advance(1)
    h.output.report("playing", "http://previous.invalid/track")
    assert not h.session.owned and h.session.reason == "external_media"


async def test_resume_cannot_override_observed_buffering(make):
    h = make(estimated=True)
    task = await h.begin()
    h.byte()
    await h.expire(task)
    h.output.report("buffering", h.session._expected)
    await h.session.pause()
    await h.session.start()
    await h.tick(10000)
    assert h.session.owned and h.session.phase == "buffering"
    assert h.session._estimated_end is None
    h.playing()
    assert h.session.confirmation_stage == "confirmed"


async def test_timer_checks_ownership_even_without_displacement_notification(make):
    h = make(estimated=True, duration=10)
    task = await h.begin()
    h.byte()
    h.session.leases.release(h.output.binding.key, h.session)
    await h.tick(15)
    assert h.session._estimated_end is None
    assert h.session.round_id == 1 and h.session.queue.position == 0
    await h.session.stop()
    await task


async def test_remove_current_assumed_item_uses_existing_stop_then_start_queue_path(make):
    from custom_components.feiniu_music.media_player import FeiNiuPlayer
    from custom_components.feiniu_music.storage import SavedSession

    h = make(estimated=True)
    s = h.session
    runtime = SimpleNamespace(
        hass=None, entry=SimpleNamespace(entry_id="synthetic", title="Synthetic")
    )
    player = FeiNiuPlayer(
        runtime, SavedSession(h.output.binding, s.queue, s.profile), s.leases, Mock()
    )
    player.output, player.session = h.output, s
    player._changed = Mock()
    task = await h.begin()
    h.byte()
    await h.expire(task)
    edit = asyncio.create_task(player.edit_queue("remove", s.queue.revision, s.queue.current_id))
    await h.settle()
    assert s.round_id == 2 and len(s.queue.items) == 2
    assert [c[0] for c in h.output.calls] == ["play_media", "media_stop", "play_media"]
    await s.stop()
    await edit


async def test_compatibility_diagnostics_are_bounded_and_do_not_leak_identity(make):
    h = make(estimated=True)
    h.output.report("paused", "PRIVATE_VENDOR_ID", source="PRIVATE_SOURCE")
    task = await h.begin()
    h.byte()
    await h.expire(task)
    h.output.report(
        "paused", "PRIVATE_VENDOR_ID", source="PRIVATE_SOURCE", media_title="PRIVATE_TITLE"
    )
    for _ in range(60):
        h.session.stream_event(1, "eof")
    data = h.session.diagnostics()
    assert len(data["events"]) == 32
    assert data["profile"]["feedback_mode"] == "compatibility"
    assert data["confirmation_stage"] == "assumed"
    assert "PRIVATE" not in str(data) and "http" not in str(data)


@pytest.mark.parametrize("fails", [False, True])
async def test_pending_resume_keeps_estimate_frozen_until_service_success(make, fails):
    h = make(estimated=True, duration=30)
    task = await h.begin()
    h.byte()
    await h.expire(task)
    await h.session.pause()
    gate = asyncio.get_running_loop().create_future()

    async def command(service, data):
        if service == "media_play":
            await gate

    h.output.hook = command
    resume = asyncio.create_task(h.session.start())
    await h.settle()
    try:
        h.output.report("paused", h.session._expected)
        await h.tick(50)  # Past the old deadline, while resume has not succeeded.
        assert h.session.round_id == 1 and h.session.queue.position == 0
        assert not resume.done() and h.session._estimated_end is None
        assert h.session.estimated_end_blocked_reason == "resume_pending"
        assert h.session.timeline.estimated_elapsed() == 20
        if fails:
            gate.set_exception(HomeAssistantError("synthetic resume failure"))
            with pytest.raises(HomeAssistantError):
                await resume
            await h.tick(100)
            assert h.session.phase == "failed" and not h.session.owned
            assert h.session.round_id == 1 and h.session._estimated_end is None
        else:
            gate.set_result(None)
            await resume
            assert h.session._estimated_end.when() == h.clock.now + 15
            await h.tick(14.999)
            assert h.session.round_id == 1
            await h.tick(0.001)
            assert h.session.round_id == 2 and h.session.queue.position == 1
    finally:
        if not gate.done():
            gate.set_result(None)
        await asyncio.gather(resume, return_exceptions=True)


@pytest.mark.parametrize("action", ["next", "new", "stop", "close"])
@pytest.mark.parametrize("fails", [False, True])
async def test_superseded_resume_cannot_rearm_or_change_new_session(make, action, fails):
    h = make(estimated=True, duration=30)
    task = await h.begin()
    h.byte()
    await h.expire(task)
    stale_callback = h.session._estimated_end._callback
    await h.session.pause()
    gate = asyncio.get_running_loop().create_future()

    async def command(service, data):
        if service == "media_play":
            try:
                await asyncio.shield(gate)
            except asyncio.CancelledError:
                await gate  # A service implementation may finish despite cancellation.
            if fails:
                raise HomeAssistantError("synthetic stale resume failure")

    h.output.hook = command
    resume = asyncio.create_task(h.session.start())
    await h.settle()
    if action == "new":
        newer = asyncio.create_task(
            h.session.jump(h.session.queue.order[2], h.session.queue.revision)
        )
    else:
        newer = asyncio.create_task(getattr(h.session, action)())
    await h.settle()
    if action in {"next", "new"}:
        h.byte()
        h.playing()
        await newer
    snapshot = (h.session.round_id, h.session.phase, h.session.owned, h.cancel.call_count)
    gate.set_result(None)
    await asyncio.gather(resume, newer, return_exceptions=True)
    stale_callback()
    await h.tick(100)
    assert (h.session.round_id, h.session.phase, h.session.owned, h.cancel.call_count) == snapshot
    assert h.session._estimated_end is None


@pytest.mark.parametrize("mode", ["standard", "compatibility"])
@pytest.mark.parametrize("service", ["media_pause", "media_stop"])
@pytest.mark.parametrize("fails", [False, True])
@pytest.mark.parametrize("action", ["next", "close"])
async def test_stale_control_completion_cannot_clean_up_new_generation(
    make, mode, service, fails, action
):
    h = make(profile=OutputProfile(feedback_mode=mode))
    task = await h.begin()
    h.byte()
    h.playing()
    await task
    gate = asyncio.get_running_loop().create_future()

    async def command(name, data):
        if name == service:
            await gate

    h.output.hook = command
    old = asyncio.create_task(getattr(h.session, service.removeprefix("media_"))())
    await h.settle()
    newer = asyncio.create_task(getattr(h.session, action)())
    await h.settle()
    if action == "next":
        h.byte()
        h.playing()
    await newer
    snapshot = (
        h.session.round_id,
        h.session.generation,
        h.session.phase,
        h.session.reason,
        h.session.owned,
        h.session._controlled,
        h.cancel.call_count,
        h.session._notify.call_count,
    )
    if fails:
        gate.set_exception(HomeAssistantError("synthetic stale control failure"))
    else:
        gate.set_result(None)
    result = (await asyncio.gather(old, return_exceptions=True))[0]
    assert (
        h.session.round_id,
        h.session.generation,
        h.session.phase,
        h.session.reason,
        h.session.owned,
        h.session._controlled,
        h.cancel.call_count,
        h.session._notify.call_count,
    ) == snapshot
    assert isinstance(result, asyncio.CancelledError)


@pytest.mark.parametrize("confirmed", [False, True])
async def test_compatibility_buffering_survives_pause_resume_until_new_playing(make, confirmed):
    h = make(estimated=True)
    task = await h.begin()
    h.byte()
    await h.expire(task)
    if confirmed:
        h.playing(position=20)
    h.output.report("buffering", h.session._expected)
    await h.session.pause()
    frozen = h.session.timeline.position()

    async def command(service, data):
        if service == "media_play":
            h.output.report("paused", h.session._expected)

    h.output.hook = command
    await h.session.start()
    h.output.report("paused", h.session._expected)
    await h.tick(50)
    assert h.session.phase == "buffering"
    assert h.session.timeline.position() == frozen
    assert h.session._estimated_end is None
    h.playing(position=21)
    assert h.session.phase == "playing" and not h.session._estimate_buffering
    assert h.session.confirmation_stage == "confirmed"
    await h.tick(1)
    assert h.session.timeline.position() == 22


@pytest.mark.parametrize("action", ["next", "stop", "close"])
async def test_buffering_observation_does_not_survive_round_or_session_end(make, action):
    h = make(estimated=True)
    task = await h.begin()
    h.byte()
    await h.expire(task)
    h.playing()
    h.output.report("buffering", h.session._expected)
    assert h.session._estimate_buffering
    operation = asyncio.create_task(getattr(h.session, action)())
    await h.settle()
    if action == "next":
        h.byte()
        await h.expire(operation)
        assert h.session.phase == "playing" and h.session.round_id == 2
    else:
        await operation
        assert not h.session.owned and h.session._estimated_end is None
    assert not h.session._estimate_buffering
