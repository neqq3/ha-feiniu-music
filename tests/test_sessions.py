"""Cancellable sessions exercised through actual HA output services and state events."""

import asyncio
from unittest.mock import AsyncMock, Mock

import pytest
from homeassistant.components.media_player import DATA_COMPONENT, MediaPlayerState
from homeassistant.components.media_player import MediaPlayerEntityFeature as Feature
from homeassistant.core import State
from homeassistant.exceptions import HomeAssistantError
from homeassistant.setup import async_setup_component

from custom_components.feiniu_music.output import OutputAdapter, OutputBinding, OutputLeases
from custom_components.feiniu_music.queue import QueueItem
from custom_components.feiniu_music.session import OutputProfile, PlaybackRequest, PlaybackSession

from .test_media_player import TestOutput


async def test_playback_debug_reconstructs_delivery_without_sensitive_metadata(
    hass, sessions, caplog
):
    import logging

    caplog.set_level(logging.DEBUG, logger="custom_components.feiniu_music")
    session, output = await sessions(profile=OutputProfile())
    task = asyncio.create_task(session.start())
    await hass.async_block_till_done()
    for event in ("head", "get", "first_byte", "eof"):
        session.stream_event(session.round_id, event)
    await task
    messages = [
        r.getMessage()
        for r in caplog.records
        if r.name.startswith("custom_components.feiniu_music")
    ]
    assert any("event=command " in m for m in messages)
    assert any("event=command_returned " in m for m in messages)
    assert any("event=confirmed " in m for m in messages)
    assert session.diagnostics()["stream_events"] == {
        "head": 1,
        "get": 1,
        "first_byte": 1,
        "eof": 1,
    }
    assert all(
        "authSig" not in m and "http://" not in m and output.entity_id not in m for m in messages
    )
    # A repeated device snapshot adds neither a log entry nor an invented transition.
    caplog.clear()
    for _ in range(10):
        session.observe(None, session.output.state)
    assert not [r for r in caplog.records if r.name.startswith("custom_components.feiniu_music")]


async def test_debug_failure_keeps_category_not_service_payload(sessions, caplog):
    import logging

    caplog.set_level(logging.DEBUG, logger="custom_components.feiniu_music")
    session, _ = await sessions()
    session.output.send = AsyncMock(
        side_effect=HomeAssistantError("PRIVATE_URL?authSig=PRIVATE_TOKEN")
    )
    with pytest.raises(HomeAssistantError):
        await session.start()
    records = [r for r in caplog.records if r.name.startswith("custom_components.feiniu_music")]
    assert any("event=failure reason=HomeAssistantError" in r.getMessage() for r in records)
    assert "PRIVATE_" not in str([(r.msg, r.args, r.exc_info) for r in records])
    assert "PRIVATE_" not in str(session.diagnostics())


@pytest.fixture
async def sessions(hass):
    assert await async_setup_component(hass, "media_player", {})
    leases = OutputLeases()
    created = []

    async def make(name="one", *, output=None, profile=None):
        if output is None:
            output = TestOutput()
            output.entity_id = f"media_player.synthetic_{name}"
            await hass.data[DATA_COMPONENT].async_add_entities([output])
        binding = OutputBinding.from_entity(hass, output.entity_id)

        async def resolve(item, round_id):
            return PlaybackRequest(
                f"http://ha.invalid/session/{name}/{round_id}/{item.track_id}?authSig=synthetic",
                "audio/mpeg",
                {},
                10,
            )

        session = PlaybackSession(
            hass,
            OutputAdapter(hass, binding),
            leases,
            resolve,
            Mock(),
            profile=profile or OutputProfile(confirmation="reported"),
        )
        session.queue.replace([QueueItem.create(key) for key in ("one", "two", "three")])
        created.append(session)
        return session, output

    yield make
    for session in created:
        await session.close()


async def test_two_fixed_outputs_have_independent_queues_controls_and_progress(hass, sessions):
    first, a = await sessions("a")
    second, b = await sessions("b")
    await asyncio.gather(first.start(), second.start())
    await first.next()
    await first.seek(4)
    await hass.async_block_till_done()
    assert len(a.calls) == 2 and len(b.calls) == 1
    assert first.queue.current.track_id == "two" and second.queue.current.track_id == "one"
    assert first.timeline.position() >= 4 and second.timeline.position() < 1
    await first.stop(clear=True)
    assert not first.queue.items and len(second.queue.items) == 3
    assert second.phase == "playing" and second.owned


async def test_second_account_claim_disarms_previous_session_without_clearing_queue(hass, sessions):
    first, output = await sessions("account_a")
    second, _ = await sessions("account_b", output=output)
    await first.start()
    old_generation = first.generation
    await second.start()
    assert first.phase == "detached" and not first.owned
    assert len(first.queue.items) == 3 and second.owned
    await first._auto_advance(old_generation)
    assert len(output.calls) == 2 and "account_b" in output.calls[-1][0]
    await first.stop()
    assert output.state == MediaPlayerState.PLAYING


async def test_stop_interrupts_slow_resolution_without_waiting_for_start_timeout(sessions):
    session, output = await sessions()
    entered = asyncio.Event()

    async def resolve(item, round_id):
        entered.set()
        await asyncio.Event().wait()

    session.resolve = resolve
    loading = asyncio.create_task(session.start())
    await entered.wait()
    await asyncio.wait_for(session.stop(), 0.5)
    await loading
    assert not output.calls and session.phase == "idle" and not session.owned
    assert session.queue.current.track_id == "one"


async def test_pause_interrupts_start_wait_and_never_sends_fallback_play(hass, sessions):
    session, output = await sessions(profile=OutputProfile(play_once=True))
    output.async_media_play = AsyncMock()
    loading = asyncio.create_task(session.start())
    await hass.async_block_till_done()
    assert output.calls and session.phase == "loading"
    await asyncio.wait_for(session.pause(), 0.5)
    await loading
    await hass.async_block_till_done()
    assert output.state == MediaPlayerState.PAUSED and session.phase == "paused"
    output.async_media_play.assert_not_called()


async def test_explicit_play_uses_output_paused_observation_not_cached_proxy_state(hass, sessions):
    session, output = await sessions()
    await session.start()
    await output.async_media_pause()
    await hass.async_block_till_done()
    session.phase = "playing"  # Simulate the earlier stale wrapper state.
    await session.start()
    assert output.state == MediaPlayerState.PLAYING
    assert len(output.calls) == 1


async def test_rapid_next_drops_late_resolution_but_keeps_both_user_operations(sessions):
    session, output = await sessions()
    await session.start()
    entered, release = asyncio.Event(), asyncio.Event()
    original = session.resolve

    async def resolve(item, round_id):
        if item.track_id == "two":
            entered.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                # A poorly cancellable underlying operation must still fail its generation check.
                await release.wait()
        return await original(item, round_id)

    session.resolve = resolve
    first_next = asyncio.create_task(session.next())
    await entered.wait()
    await session.next()
    release.set()
    await first_next
    assert session.queue.current.track_id == "three"
    assert len(output.calls) == 2 and "/three?" in output.calls[-1][0]


async def test_delivery_confirmation_distinguishes_head_reported_playing_and_audio(hass, sessions):
    session, output = await sessions(profile=OutputProfile())
    loading = asyncio.create_task(session.start())
    await hass.async_block_till_done()
    assert output.state == MediaPlayerState.PLAYING
    assert session.phase == "loading" and session.reason == "reported_without_delivery"
    session.stream_event(session.round_id, "head")
    assert not loading.done() and not session.started
    session.stream_event(session.round_id, "get")
    assert not session.started
    session.stream_event(session.round_id, "first_byte")
    await loading
    assert session.phase == "playing" and session.confirmation == "delivery"
    session.stream_event(session.round_id, "eof")
    assert len(output.calls) == 1 and session.queue.current.track_id == "one"


async def test_unknown_uri_can_use_delivery_evidence_without_claiming_strong_identity(
    hass, sessions
):
    session, output = await sessions(profile=OutputProfile())
    original = output.async_play_media

    async def transformed(*args, **kwargs):
        await original(*args, **kwargs)
        output._attr_media_content_id = "device-local:current"
        output.async_write_ha_state()

    output.async_play_media = transformed
    loading = asyncio.create_task(session.start())
    await hass.async_block_till_done()
    session.stream_event(session.round_id, "first_byte")
    await loading
    assert session.identity == "unknown" and session.phase == "playing"
    await output.async_media_seek(10)
    await hass.async_block_till_done()
    await output.async_media_stop()
    await hass.async_block_till_done()
    assert len(output.calls) == 1 and session.phase == "detached"


async def test_old_round_events_and_business_query_never_authorize_current_playback(sessions):
    session, output = await sessions()
    await session.start()
    old_url = output.calls[0][0]
    await session.jump(session.queue.current_id, session.queue.revision)
    current_round = session.round_id
    assert output.calls[-1][0] != old_url
    session.observe(None, State(output.entity_id, "idle", {"media_content_id": old_url}))
    session.stream_event(current_round - 1, "error")
    assert session.phase == "playing" and session.round_id == current_round
    current = output.calls[-1][0]
    assert (
        session._matches(
            State(
                output.entity_id,
                "playing",
                {"media_content_id": current.replace("authSig=synthetic", "authSig=rotated")},
            )
        )
        == "matched"
    )
    session.observe(
        None, State(output.entity_id, "playing", {"media_content_id": current + "&track=other"})
    )
    assert session.phase == "detached"


async def test_natural_end_once_but_explicit_stop_at_end_does_not_advance(hass, sessions):
    session, output = await sessions()
    await session.start()
    await output.async_media_seek(10)
    await hass.async_block_till_done()
    await output.async_media_stop()
    await hass.async_block_till_done()
    if session._advance:
        await session._advance
    assert len(output.calls) == 2 and session.queue.current.track_id == "two"
    await session.seek(9.9)
    await hass.async_block_till_done()
    await session.stop()
    await hass.async_block_till_done()
    assert len(output.calls) == 2 and session.phase == "idle"


async def test_dynamic_output_features_at_end_do_not_lose_queue_advance(hass, sessions):
    """DLNA removes Pause/Seek at STOPPED, updating the registry before state events."""
    output = TestOutput()
    output._attr_unique_id = "synthetic_dynamic_dmr"
    await hass.data[DATA_COMPONENT].async_add_entities([output])
    session, _ = await sessions(output=output)
    await session.start()
    await output.async_media_seek(10)
    await hass.async_block_till_done()
    output._attr_supported_features &= ~(Feature.PAUSE | Feature.SEEK)
    await output.async_media_stop()
    await hass.async_block_till_done()
    if session._advance:
        await session._advance
    assert len(output.calls) == 2
    assert session.queue.current.track_id == "two"
    assert session.phase == "playing"


async def test_stop_failure_still_invalidates_control_and_preserves_queue(sessions):
    session, output = await sessions()
    await session.start()
    output.async_media_stop = AsyncMock(side_effect=HomeAssistantError("synthetic refusal"))
    with pytest.raises(HomeAssistantError):
        await session.stop()
    assert session.phase == "failed" and session.reason == "stop_unconfirmed"
    assert not session.owned and len(session.queue.items) == 3
    assert "synthetic refusal" not in str(session.diagnostics())


async def test_unload_cancels_pending_start_and_stops_entity_notifications(sessions):
    session, output = await sessions()
    entered = asyncio.Event()

    async def resolve(item, round_id):
        entered.set()
        await asyncio.Event().wait()

    session.resolve = resolve
    loading = asyncio.create_task(session.start())
    await entered.wait()
    await session.close()
    count = session._notify.call_count
    await loading
    session.observe(None, State(output.entity_id, "playing", {}))
    assert session._notify.call_count == count and not output.calls


async def test_empty_queue_only_enqueue_does_not_claim_or_start_output(sessions):
    session, output = await sessions()
    session.queue.clear()
    for mode in ("add", "next"):

        async def read():
            return [QueueItem.create("one")], 0

        await session.replace_or_enqueue(read, mode)
    assert len(session.queue.items) == 2 and not session.owned and not output.calls


async def test_unsupported_pause_is_explicit_not_a_reload(sessions):
    session, output = await sessions()
    await session.start()
    output._attr_supported_features &= ~Feature.PAUSE
    output.async_write_ha_state()
    with pytest.raises(HomeAssistantError, match="cannot pause"):
        await session.pause()
    assert len(output.calls) == 1 and session.reason == "pause_unsupported"


async def test_stop_during_replacement_read_still_stops_previously_owned_output(hass, sessions):
    session, output = await sessions()
    await session.start()
    reached = asyncio.Event()

    async def read():
        reached.set()
        await asyncio.Event().wait()

    operation = asyncio.create_task(session.replace_or_enqueue(read, "replace"))
    await reached.wait()
    await asyncio.wait_for(session.stop(), 0.5)
    await operation
    assert output.state == MediaPlayerState.IDLE and session.phase == "idle"
    assert len(output.calls) == 1 and not session.owned


async def test_pause_during_replacement_read_cannot_leave_loading_forever(hass, sessions):
    session, output = await sessions()
    await session.start()
    reached = asyncio.Event()

    async def read():
        reached.set()
        await asyncio.Event().wait()

    operation = asyncio.create_task(session.replace_or_enqueue(read, "replace"))
    await reached.wait()
    await asyncio.wait_for(session.pause(), 0.5)
    await operation
    assert output.state == MediaPlayerState.PAUSED
    assert session.phase == "idle" and session.reason == "loading_cancelled"
    assert not session.owned and len(output.calls) == 1


async def test_close_cancels_queue_only_read_and_no_late_mutation(sessions):
    session, output = await sessions()
    reached, cancelled = asyncio.Event(), asyncio.Event()

    async def read():
        reached.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    revision = session.queue.revision
    operation = asyncio.create_task(session.replace_or_enqueue(read, "add"))
    await reached.wait()
    await session.close()
    await operation
    assert cancelled.is_set() and session.queue.revision == revision and not output.calls


async def test_paused_seek_does_not_resume_or_turn_pause_into_end(hass, sessions):
    session, output = await sessions()
    await session.start()
    await session.pause()
    await hass.async_block_till_done()
    await session.seek(8)
    await hass.async_block_till_done()
    assert session.phase == "paused" and session.intent == "pause"
    assert output.state == MediaPlayerState.PAUSED and session.timeline.position() == 8
    assert len(output.calls) == 1


async def test_compatibility_profile_sends_at_most_one_standard_play(monkeypatch, hass, sessions):
    monkeypatch.setattr("custom_components.feiniu_music.session.COMPAT_PLAY_DELAY", 0.001)
    monkeypatch.setattr("custom_components.feiniu_music.session.START_TIMEOUT", 0.01)
    session, output = await sessions(profile=OutputProfile(play_once=True))
    output.async_media_play = AsyncMock()
    with pytest.raises(HomeAssistantError, match="confirm"):
        await session.start()
    output.async_media_play.assert_awaited_once()
    assert len(output.calls) == 1 and session.phase == "failed"
    assert session.reason == "start_unconfirmed" and not session.owned


async def test_two_second_track_and_duplicate_idle_advance_only_once(hass, sessions):
    session, output = await sessions()
    original = session.resolve

    async def short(item, round_id):
        value = await original(item, round_id)
        return PlaybackRequest(value.url, value.content_type, {}, 2)

    session.resolve = short
    await session.start()
    await output.async_media_seek(2)
    await hass.async_block_till_done()
    ended = State(output.entity_id, "idle", dict(output.state_attributes))
    old = session.output.state
    session.observe(old, ended)
    session.observe(old, ended)
    await hass.async_block_till_done()
    assert len(output.calls) == 2 and session.queue.current.track_id == "two"
