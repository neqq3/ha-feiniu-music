"""One playback round's display timeline; it never decides if a device is playing."""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from time import monotonic
from typing import Any


def number(value: Any) -> float | None:
    """Reject booleans, strings and non-finite device values."""
    return float(value) if type(value) in {int, float} and math.isfinite(value) else None


def utc_timestamp(value: Any) -> datetime | None:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return None
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        return None
    return value.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class Anchor:
    position: float
    utc: datetime
    monotonic: float
    moving: bool
    source: str


class Timeline:
    """Pair position and timestamp, freeze gaps, and ignore anchors from older rounds."""

    def __init__(
        self,
        clock: Callable[[], float] = monotonic,
        utcnow: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.clock = clock
        self.utcnow = utcnow
        self.round_id = 0
        self.duration: float | None = None
        self.anchor: Anchor | None = None
        self.reason = "not_started"
        self.raw_pair: tuple[float, datetime] | None = None
        self.state = "idle"
        self.started_at = self.utcnow()
        self.seek_target: float | None = None
        self.seek_started: datetime | None = None
        self._estimate_elapsed = 0.0
        self._estimate_since: float | None = None
        self._estimate_started = False

    @property
    def source(self) -> str:
        return self.anchor.source if self.anchor else "unavailable"

    def reset(self, round_id: int, duration: Any = None) -> None:
        self.round_id = round_id
        value = number(duration)
        self.duration = value if value is not None and value > 0 else None
        self.anchor = None
        self.reason = "not_started"
        self.raw_pair = None
        self.state = "buffering"
        self.started_at = self.utcnow()
        self.seek_target = None
        self.seek_started = None
        self._estimate_elapsed = 0.0
        self._estimate_since = None
        self._estimate_started = False

    def start_estimate(self, zero: float) -> None:
        """Delivery/command zero, not proof that a speaker has started making sound."""
        if not self._estimate_started:
            self._estimate_started = True
            self._estimate_since = zero

    def estimated_elapsed(self) -> float:
        """Unclamped active time: the end grace must survive pauses after duration."""
        return self._estimate_elapsed + (
            max(0, self.clock() - self._estimate_since) if self._estimate_since is not None else 0
        )

    def freeze_estimate(self) -> None:
        self._estimate_elapsed = self.estimated_elapsed()
        self._estimate_since = None

    def resume_estimate(self) -> None:
        if self._estimate_started and self._estimate_since is None:
            self._estimate_since = self.clock()

    def show_estimate(self, *, moving: bool) -> None:
        self._set(self.estimated_elapsed(), "playing" if moving else "paused", "estimated")
        self.state = "playing" if moving else "paused"
        self.reason = "unconfirmed_estimate"

    def resume(self) -> None:
        position = self.position()
        if position is not None:
            self._set(position, "playing", self.source)
        self.state = "playing"

    def position(self) -> float | None:
        if self.anchor is None:
            return None
        value = self.anchor.position
        if self.anchor.moving:
            value += max(0, self.clock() - self.anchor.monotonic)
        return self._clamp(value)

    def _clamp(self, value: float) -> float:
        return max(0, min(value, self.duration)) if self.duration else max(0, value)

    def _set(self, position: float, state: str, source: str) -> None:
        self.anchor = Anchor(
            self._clamp(position), self.utcnow(), self.clock(), state == "playing", source
        )

    def confirm(self, round_id: int, *, estimate_from_start: bool = False) -> None:
        """The session supplies independent start evidence; a timer cannot confirm it."""
        if round_id != self.round_id:
            return
        if self.anchor is None and estimate_from_start:
            self._set(0, "playing", "estimated")
            self.state = "playing"
            self.reason = "confirmed_start_estimate"

    def observe(self, round_id: int, state: str, attrs: Mapping[str, Any]) -> bool:
        """Return whether a fresh paired raw sample was accepted, not playback evidence."""
        if round_id != self.round_id:
            return False
        now = self.utcnow()
        old_state = self.state
        old_position = self.position()
        position = number(attrs.get("media_position"))
        timestamp = utc_timestamp(attrs.get("media_position_updated_at"))
        fresh = False
        pair = None
        if position is not None and position >= 0 and timestamp is not None:
            pair = (position, timestamp)
            valid = (
                self.started_at - timedelta(seconds=1) <= timestamp <= now + timedelta(seconds=2)
            )
            if self.raw_pair is not None:
                # Never pair a changed value with the old timestamp, or reset progress on
                # volume updates which restamp an unchanged raw position.
                old_value, old_time = self.raw_pair
                valid = valid and timestamp > old_time and position != old_value
                if self.seek_target is not None and self.seek_started is not None:
                    valid = (
                        self.started_at - timedelta(seconds=1)
                        <= timestamp
                        <= now + timedelta(seconds=2)
                        and timestamp > old_time
                        and timestamp >= self.seek_started
                        and abs(position - self.seek_target) <= 2
                    )
            if self.duration is not None and position > self.duration + 2:
                valid = False
            if valid:
                if self.seek_target is None and old_state == "playing" and old_position is not None:
                    # A coherent newer pair can represent an external seek in either direction.
                    self.reason = "native_position"
                age = max(0, (now - timestamp).total_seconds()) if state == "playing" else 0
                self._set(position + age, state, "native")
                self.raw_pair = pair
                self.reason = "native_position"
                self.seek_target = None
                self.seek_started = None
                fresh = True
            elif pair != self.raw_pair:
                self.reason = "ignored_unpaired_or_stale_position"
        if not fresh and state != old_state and old_position is not None:
            # Pause/buffering without a new pair freezes the extrapolated position.
            # Resume uses the frozen point, not the output's old raw sample.
            self._set(old_position, state, self.source)
        self.state = state
        value = number(attrs.get("media_duration"))
        if self.duration is None and fresh and value is not None and value > 0:
            self.duration = value
        return fresh

    def freeze(self, reason: str, *, forget: bool = False) -> None:
        position = self.position()
        if forget:
            self.anchor = None
            self.raw_pair = None
        elif position is not None:
            self._set(position, "paused", self.source)
        self.state = "idle" if forget else "paused"
        self.reason = reason
        self.seek_target = None
        self.seek_started = None

    def request_seek(self, target: float) -> None:
        """A successful command does not authorize displaying its target as confirmed."""
        value = number(target)
        if value is None or value < 0 or (self.duration is not None and value > self.duration):
            raise ValueError("Seek target is outside this track")
        self.seek_target = value
        self.seek_started = self.utcnow()
        self.reason = "awaiting_seek_feedback"

    def reject_seek(self) -> None:
        self.seek_target = None
        self.seek_started = None
        self.reason = "seek_unconfirmed"

    def ha_anchor(self) -> tuple[float | None, datetime | None]:
        """Publish a consistent UTC anchor; monotonic remains process-local."""
        if self.anchor is None:
            return None, None
        # Keep the same pair across unrelated events. Rebase only if the wall clock
        # jumped relative to monotonic elapsed time (including during a pause).
        drift = (self.utcnow() - self.anchor.utc).total_seconds() - (
            self.clock() - self.anchor.monotonic
        )
        if abs(drift) > 2:
            return self.position(), self.utcnow()
        return self.anchor.position, self.anchor.utc

    def saved_position(self) -> float | None:
        """Persist only a useful native estimate, never a monotonic value or timestamp."""
        return self.position() if self.source == "native" else None
