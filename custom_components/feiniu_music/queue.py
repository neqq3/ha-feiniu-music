"""Local queue order and occurrence identities; no HA calls or playback decisions."""

from __future__ import annotations

import random
import re
from dataclasses import asdict, dataclass
from typing import Any
from uuid import uuid4

MAX_QUEUE_ITEMS = 10000
_ID = re.compile(r"[A-Za-z0-9_.:-]{1,160}\Z")
_SOURCE = re.compile(r"media-source://feiniu_music/[A-Za-z0-9_.:/-]{1,1024}\Z")


class QueueError(ValueError):
    """Invalid local edit, without changing any queue state."""


class RevisionConflict(QueueError):
    """The browser must refresh before applying an edit to a different revision."""


@dataclass(frozen=True, slots=True)
class QueueItem:
    """One occurrence of a track, not an authorization or a playable URL."""

    item_id: str
    track_id: str
    source: str | None = None

    def __post_init__(self) -> None:
        if not all(
            isinstance(value, str) and _ID.fullmatch(value)
            for value in (self.item_id, self.track_id)
        ):
            raise QueueError("Invalid queue item identity")
        if self.source is not None and (
            not isinstance(self.source, str) or not _SOURCE.fullmatch(self.source)
        ):
            raise QueueError("Queue context must be a local FeiNiu media-source ID")

    @classmethod
    def create(cls, track_id: str, source: str | None = None) -> QueueItem:
        """Repeated track IDs deliberately receive distinct occurrence IDs."""
        return cls(uuid4().hex, track_id, source)


class QueueModel:
    """Original insertion order plus a separately editable playback order."""

    def __init__(self) -> None:
        self.items: dict[str, QueueItem] = {}
        self.original: list[str] = []
        self.order: list[str] = []
        self.current_id: str | None = None
        self.shuffle = False
        self.repeat = "off"
        self.revision = 0

    @property
    def position(self) -> int:
        return self.order.index(self.current_id) if self.current_id is not None else -1

    @property
    def current(self) -> QueueItem | None:
        return self.items.get(self.current_id) if self.current_id else None

    def check_revision(self, revision: int) -> None:
        """A Boolean is not a numeric queue revision."""
        if type(revision) is not int or revision != self.revision:
            raise RevisionConflict("Queue changed; refresh it before editing")

    def _admit(self, items: list[QueueItem], *, replace: bool = False) -> None:
        count = len(items) + (0 if replace else len(self.items))
        if count > MAX_QUEUE_ITEMS:
            raise QueueError(f"Queue limit is {MAX_QUEUE_ITEMS} items; nothing was truncated")
        ids = [item.item_id for item in items]
        if len(set(ids)) != len(ids) or (not replace and set(ids).intersection(self.items)):
            raise QueueError("Queue occurrence IDs must be unique")

    def replace(self, items: list[QueueItem], start: int = 0) -> QueueItem | None:
        """Replace atomically, preserving earlier list context for Previous."""
        self._admit(items, replace=True)
        if type(start) is not int or (items and not 0 <= start < len(items)):
            raise QueueError("Selected queue position is invalid")
        self.items = {item.item_id: item for item in items}
        self.original = list(self.items)
        self.order = self.original.copy()
        self.current_id = self.order[start] if self.order else None
        if self.shuffle:
            self._shuffle_pending()
        self.revision += 1
        return self.current

    def enqueue(self, items: list[QueueItem], mode: str = "replace", start: int = 0) -> bool:
        """Return whether the explicit enqueue mode requests playback, not queue ownership."""
        if mode not in {"replace", "add", "next", "play"}:
            raise QueueError("Unknown enqueue mode")
        if mode == "replace":
            return self.replace(items, start) is not None
        self._admit(items)
        if not items:
            return False
        if type(start) is not int or not 0 <= start < len(items):
            raise QueueError("Selected queue position is invalid")
        ids = [item.item_id for item in items]
        insertion = len(self.order) if mode == "add" else self.position + 1
        self.items.update((item.item_id, item) for item in items)
        self.original.extend(ids)
        self.order[insertion:insertion] = ids
        if self.current_id is None or mode == "play":
            self.current_id = ids[start] if mode == "play" else self.order[0]
        self.revision += 1
        # In particular, add/next on an empty queue never implicitly starts a speaker.
        return mode == "play"

    def jump(self, item_id: str, revision: int) -> QueueItem:
        self.check_revision(revision)
        if item_id not in self.items:
            raise QueueError("Queue occurrence is unavailable")
        self.current_id = item_id
        self.revision += 1
        return self.items[item_id]

    def advance(self, *, natural: bool = False) -> QueueItem | None:
        """Natural repeat-one differs from the user's explicit Next intent."""
        if not self.order:
            return None
        if natural and self.repeat == "one":
            self.revision += 1
            return self.current
        next_position = self.position + 1
        if next_position >= len(self.order):
            if self.repeat != "all":
                return None
            self.order = self.original.copy()
            if self.shuffle:
                random.shuffle(self.order)
            next_position = 0
        self.current_id = self.order[next_position]
        self.revision += 1
        return self.current

    def previous(self) -> QueueItem | None:
        if not self.order:
            return None
        position = self.position - 1
        if position < 0:
            position = len(self.order) - 1 if self.repeat == "all" else 0
        self.current_id = self.order[position]
        self.revision += 1
        return self.current

    def set_shuffle(self, enabled: bool) -> None:
        """History/current stay in place; only unplayed occurrences change order."""
        if type(enabled) is not bool:
            raise QueueError("Shuffle must be a boolean")
        if enabled == self.shuffle:
            return
        self.shuffle = enabled
        if enabled:
            self._shuffle_pending()
        else:
            pending = set(self.order[self.position + 1 :])
            self.order[self.position + 1 :] = [key for key in self.original if key in pending]
        self.revision += 1

    def _shuffle_pending(self) -> None:
        pending = self.order[self.position + 1 :]
        random.shuffle(pending)
        self.order[self.position + 1 :] = pending

    def set_repeat(self, mode: str) -> None:
        if not isinstance(mode, str) or mode not in {"off", "one", "all"}:
            raise QueueError("Unknown repeat mode")
        if mode != self.repeat:
            self.repeat = mode
            self.revision += 1

    def remove(self, item_id: str, revision: int) -> bool:
        """Return whether current changed; the session decides whether to start its successor."""
        self.check_revision(revision)
        if item_id not in self.items:
            raise QueueError("Queue occurrence is unavailable")
        index = self.order.index(item_id)
        changed = item_id == self.current_id
        self.order.remove(item_id)
        self.original.remove(item_id)
        self.items.pop(item_id)
        if changed:
            self.current_id = self.order[index] if index < len(self.order) else None
            if self.current_id is None and self.order and self.repeat == "all":
                self.current_id = self.order[0]
        self.revision += 1
        return changed

    def move(self, item_id: str, before_id: str | None, revision: int) -> None:
        """Only pending items can move; IDs, not obsolete UI array indexes, identify them."""
        self.check_revision(revision)
        pending = self.order[self.position + 1 :]
        if item_id not in pending or (before_id is not None and before_id not in pending):
            raise QueueError("Only pending queue items can be reordered")
        if item_id == before_id:
            return
        self.order.remove(item_id)
        index = self.order.index(before_id) if before_id else len(self.order)
        self.order.insert(index, item_id)
        # User editing establishes the canonical pending order for shuffle-off.
        pending_ids = set(pending)
        original_pending = iter(key for key in self.order if key in pending_ids)
        self.original = [
            next(original_pending) if key in pending_ids else key for key in self.original
        ]
        self.revision += 1

    def clear(self, revision: int | None = None) -> None:
        if revision is not None:
            self.check_revision(revision)
        self.items.clear()
        self.original.clear()
        self.order.clear()
        self.current_id = None
        self.revision += 1

    def snapshot(self) -> dict[str, Any]:
        """Allowlisted persistent representation: no runtime metadata or access grants."""
        return {
            "schema": 1,
            "items": [asdict(self.items[key]) for key in self.original],
            "order": self.order.copy(),
            "current_id": self.current_id,
            "shuffle": self.shuffle,
            "repeat": self.repeat,
            "revision": self.revision,
        }

    @classmethod
    def restore(cls, data: Any) -> QueueModel:
        """Reject corrupt/foreign structure as a whole; never partially restore a queue."""
        if not isinstance(data, dict) or type(data.get("schema")) is not int or data["schema"] != 1:
            raise QueueError("Unsupported queue storage version")
        rows = data.get("items")
        if not isinstance(rows, list) or len(rows) > MAX_QUEUE_ITEMS:
            raise QueueError("Invalid saved queue")
        items = []
        for row in rows:
            if not isinstance(row, dict) or set(row) != {"item_id", "track_id", "source"}:
                raise QueueError("Invalid saved queue item")
            items.append(QueueItem(row["item_id"], row["track_id"], row["source"]))
        model = cls()
        model._admit(items, replace=True)
        order = data.get("order")
        if (
            not isinstance(order, list)
            or any(not isinstance(value, str) for value in order)
            or len(order) != len(items)
            or set(order) != {item.item_id for item in items}
            or (data.get("current_id") is not None and data["current_id"] not in order)
            or type(data.get("revision")) is not int
            or data["revision"] < 0
            or type(data.get("shuffle")) is not bool
            or not isinstance(data.get("repeat"), str)
            or data.get("repeat") not in {"off", "one", "all"}
        ):
            raise QueueError("Saved queue order or preferences are corrupt")
        model.items = {item.item_id: item for item in items}
        model.original = list(model.items)
        model.order = order.copy()
        model.current_id = data.get("current_id")
        model.shuffle = data["shuffle"]
        model.repeat = data["repeat"]
        model.revision = data["revision"]
        return model
