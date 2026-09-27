"""Account-local, revocable playback rounds on the existing HA audio endpoint."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from time import monotonic

from .client import NotFoundError


@dataclass(slots=True)
class AudioRound:
    """One output's current transport, never a persistent credential or queue item."""

    owner: str
    guid: str
    round_id: int
    observe: Callable[[int, str], None]
    expires: float = field(default_factory=lambda: monotonic() + 2 * 60 * 60)
    tasks: set[asyncio.Task] = field(default_factory=set)
    closed: bool = False

    def check(self) -> None:
        if self.closed or monotonic() >= self.expires:
            raise NotFoundError("Playback round has expired")

    def event(self, label: str) -> None:
        if not self.closed:
            self.observe(self.round_id, label)

    def close(self) -> None:
        self.closed = True
        current = asyncio.current_task()
        for task in self.tasks:
            if task is not current and not task.done():
                task.cancel()
