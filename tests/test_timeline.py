"""Sparse HA anchors and state transitions using independent wall/monotonic clocks."""

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.feiniu_music.timeline import Timeline


@pytest.fixture
def timeline():
    clock = [100.0, datetime(2026, 1, 1, tzinfo=UTC)]
    line = Timeline(lambda: clock[0], lambda: clock[1])
    line.reset(1, 100)
    return line, clock


def advance(clock, seconds):
    clock[0] += seconds
    clock[1] += timedelta(seconds=seconds)


def sample(clock, position, **extra):
    return {"media_position": position, "media_position_updated_at": clock[1], **extra}


def test_no_clock_starts_without_independent_start_evidence(timeline):
    line, clock = timeline
    advance(clock, 20)
    assert line.position() is None and line.source == "unavailable"
    line.confirm(1, estimate_from_start=True)
    advance(clock, 3)
    assert line.position() == 3 and line.source == "estimated"
    assert line.saved_position() is None


def test_sparse_anchor_volume_events_and_wall_clock_jumps(timeline):
    line, clock = timeline
    attrs = sample(clock, 0)
    assert line.observe(1, "playing", attrs)
    original = line.ha_anchor()
    advance(clock, 40)
    assert not line.observe(1, "playing", {**attrs, "volume_level": 0.5})
    assert line.position() == 40 and line.ha_anchor() == original
    clock[1] += timedelta(hours=2)
    assert line.position() == 40
    position, timestamp = line.ha_anchor()
    assert position == 40 and timestamp == clock[1]


def test_state_only_pause_resume_and_buffering_freeze_extrapolated_position(timeline):
    line, clock = timeline
    attrs = sample(clock, 5)
    line.observe(1, "playing", attrs)
    advance(clock, 10)
    line.observe(1, "paused", attrs)
    assert line.position() == 15
    advance(clock, 30)
    line.observe(1, "playing", attrs)
    advance(clock, 2)
    assert line.position() == 17
    line.observe(1, "buffering", attrs)
    advance(clock, 20)
    assert line.position() == 17
    line.observe(1, "playing", attrs)
    advance(clock, 3)
    assert line.position() == 20


def test_changed_value_and_timestamp_must_arrive_as_a_pair(timeline):
    line, clock = timeline
    attrs = sample(clock, 5)
    line.observe(1, "playing", attrs)
    advance(clock, 5)
    assert not line.observe(1, "playing", {**attrs, "media_position": 50})
    assert not line.observe(1, "playing", sample(clock, 5))
    assert line.position() == 10
    assert line.observe(1, "playing", sample(clock, 12))
    assert line.position() == 12


def test_backward_seek_waits_for_valid_feedback_and_rejection_keeps_truth(timeline):
    line, clock = timeline
    line.observe(1, "playing", sample(clock, 60))
    advance(clock, 1)
    line.request_seek(10)
    assert line.position() == 61
    assert line.observe(1, "playing", sample(clock, 10))
    assert line.position() == 10 and line.seek_target is None
    line.request_seek(90)
    advance(clock, 2)
    line.reject_seek()
    assert line.position() == 12 and line.reason == "seek_unconfirmed"


def test_old_round_anchors_and_temporary_zero_duration_are_ignored(timeline):
    line, clock = timeline
    old = sample(clock, 80)
    line.observe(1, "playing", old)
    advance(clock, 5)
    line.reset(2, 200)
    assert not line.observe(1, "playing", sample(clock, 90))
    assert not line.observe(2, "playing", old)
    assert line.position() is None
    line.observe(2, "playing", sample(clock, 0, media_duration=0))
    assert line.duration == 200 and line.position() == 0


@pytest.mark.parametrize("value", [-1, float("nan"), float("inf"), True, "10", None])
def test_invalid_raw_positions_do_not_create_anchors(timeline, value):
    line, clock = timeline
    assert not line.observe(1, "playing", sample(clock, value))
    assert line.position() is None


@pytest.mark.parametrize("value", ["2026-01-01T00:00:00", "bad", datetime(2026, 1, 1), None])
def test_timezone_less_or_missing_timestamps_rejected(timeline, value):
    line, _ = timeline
    assert not line.observe(
        1, "playing", {"media_position": 10, "media_position_updated_at": value}
    )
    assert line.position() is None


def test_future_timestamp_and_future_seek_feedback_do_not_override_anchor(timeline):
    line, clock = timeline
    line.observe(1, "playing", sample(clock, 10))
    advance(clock, 1)
    line.request_seek(20)
    future = {"media_position": 20, "media_position_updated_at": clock[1] + timedelta(hours=1)}
    assert not line.observe(1, "playing", future)
    assert line.position() == 11 and line.seek_target == 20


def test_explicit_seek_to_original_zero_accepts_fresh_matching_pair(timeline):
    line, clock = timeline
    assert line.observe(1, "playing", sample(clock, 0))
    advance(clock, 10)
    line.request_seek(0)
    advance(clock, 0.2)
    assert line.observe(1, "playing", sample(clock, 0))
    assert line.seek_target is None and line.position() == 0
