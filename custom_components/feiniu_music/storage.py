"""Versioned HA queue storage, with no transport URLs or automatic playback on restore."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN
from .output import OutputBinding
from .queue import QueueError, QueueModel
from .session import OutputProfile
from .timeline import number


@dataclass(slots=True)
class SavedSession:
    binding: OutputBinding
    queue: QueueModel
    profile: OutputProfile
    position: float | None = None
    lyric_offset: float = 0

    def snapshot(self) -> dict[str, Any]:
        position = number(self.position)
        offset = number(self.lyric_offset)
        if (position is not None and position < 0) or offset is None or abs(offset) > 30:
            raise QueueError("Invalid saved position or lyric offset")
        return {
            "binding": self.binding.snapshot(),
            "queue": self.queue.snapshot(),
            "profile": asdict(self.profile),
            "position": position,
            "lyric_offset": offset,
        }

    @classmethod
    def restore(cls, data: Any, account_id: str) -> SavedSession:
        if not isinstance(data, dict) or set(data) != {
            "binding",
            "queue",
            "profile",
            "position",
            "lyric_offset",
        }:
            raise QueueError("Invalid saved output session")
        binding = OutputBinding.restore(data["binding"])
        queue = QueueModel.restore(data["queue"])
        prefix = f"media-source://{DOMAIN}/{account_id}/"
        if any(item.source and not item.source.startswith(prefix) for item in queue.items.values()):
            raise QueueError("Saved media context belongs to another account")
        profile = data["profile"]
        if not isinstance(profile, dict) or set(profile) - {"end_offset"} != {
            "confirmation",
            "play_once",
            "end_state",
            "weak_end",
            "feedback_mode",
            "unconfirmed_end",
        }:
            raise QueueError("Invalid saved output profile")
        if data["position"] is not None and number(data["position"]) is None:
            raise QueueError("Invalid saved position")
        restored = cls(
            binding, queue, OutputProfile(**profile), data["position"], data["lyric_offset"]
        )
        restored.snapshot()  # Validate numeric bounds before exposing any restored state.
        return restored


def _restore_outputs(data: Any, entry_id: str) -> dict[str, SavedSession]:
    if (
        not isinstance(data, dict)
        or set(data) != {"outputs"}
        or not isinstance(data["outputs"], dict)
    ):
        raise QueueError("Invalid queue storage")
    restored = {}
    for key, value in data["outputs"].items():
        item = SavedSession.restore(value, entry_id)
        if item.binding.key != key:
            raise QueueError("Queue output identity mismatch")
        restored[key] = item
    return restored


class _QueueStore(Store[dict[str, Any]]):
    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self.entry_id = entry_id
        super().__init__(
            hass,
            2,
            f"{DOMAIN}.queues.{entry_id}",
            private=True,
            atomic_writes=True,
            serialize_in_event_loop=False,
        )

    async def _async_migrate_func(self, old_major_version, old_minor_version, old_data):
        """HA saves only after every record validates; never partially migrate a file."""
        if old_major_version not in {1, 2}:
            raise QueueError("Unsupported queue storage version")
        data = deepcopy(old_data)
        if old_major_version == 1:
            if not isinstance(data, dict) or not isinstance(data.get("outputs"), dict):
                raise QueueError("Invalid queue storage")
            for value in data["outputs"].values():
                if not isinstance(value, dict) or not isinstance(value.get("profile"), dict):
                    raise QueueError("Invalid saved output profile")
                profile = value["profile"]
                if set(profile) != {"confirmation", "play_once", "end_state", "weak_end"}:
                    raise QueueError("Invalid saved output profile")
                profile.update(feedback_mode="standard", unconfirmed_end="manual", end_offset=0)
        _restore_outputs(data, self.entry_id)
        return data


class QueueStorage:
    """One account's output records; deselection retains data, account removal deletes it."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self.entry_id = entry_id
        self.store = _QueueStore(hass, entry_id)
        self.records: dict[str, dict[str, Any]] = {}
        self.corrupt = False

    async def load(self) -> dict[str, SavedSession]:
        try:
            data = await self.store.async_load()
            if data is None:
                return {}
            restored = _restore_outputs(data, self.entry_id)
        except (ValueError, TypeError, KeyError):
            # Preserve a syntactically readable but semantically corrupt file. A repair
            # action must explicitly clear/restore it; never silently overwrite it.
            self.corrupt = True
            return {}
        self.records = deepcopy(data["outputs"])
        return restored

    def stage(self, session: SavedSession) -> None:
        if self.corrupt:
            raise QueueError("Queue storage requires repair; the original file is preserved")
        self.records[session.binding.key] = session.snapshot()
        # Frozen copies can safely serialize on HA's executor, not on the UI event loop.
        snapshot = {"outputs": deepcopy(self.records)}
        self.store.async_delay_save(lambda: snapshot, 1)

    async def flush(self) -> None:
        if not self.corrupt:
            await self.store.async_save({"outputs": deepcopy(self.records)})

    async def delete(self) -> None:
        """Only for explicit account/queue-data deletion, not unload or deselection."""
        self.records.clear()
        self.corrupt = False
        await self.store.async_remove()
