"""Occurrence-based local queue semantics, including persistence and stale UI edits."""

from copy import deepcopy
from unittest.mock import patch

import pytest

from custom_components.feiniu_music.queue import QueueError, QueueItem, QueueModel, RevisionConflict


def items(*names):
    return [QueueItem.create(name) for name in names]


def names(queue):
    return [queue.items[key].track_id for key in queue.order]


def test_duplicates_keep_occurrence_identity_and_original_context():
    queue = QueueModel()
    queue.replace(items("one", "one", "two"), start=1)
    assert len(queue.items) == 3 and queue.current.track_id == "one" and queue.position == 1
    first, second, third = queue.order
    queue.remove(first, queue.revision)
    assert queue.current_id == second and queue.position == 0
    assert queue.advance().item_id == third
    assert queue.previous().item_id == second


@pytest.mark.parametrize(
    "mode,play", [("add", False), ("next", False), ("play", True), ("replace", True)]
)
def test_empty_enqueue_has_explicit_play_intent(mode, play):
    queue = QueueModel()
    assert queue.enqueue(items("one", "two"), mode) is play
    assert names(queue) == ["one", "two"]


@pytest.mark.parametrize(
    "mode,expected,current",
    [
        ("add", ["one", "two", "three", "new"], "two"),
        ("next", ["one", "two", "new", "three"], "two"),
        ("play", ["one", "two", "new", "three"], "new"),
        ("replace", ["new"], "new"),
    ],
)
def test_enqueue_modes_preserve_or_replace_context(mode, expected, current):
    queue = QueueModel()
    queue.replace(items("one", "two", "three"), start=1)
    queue.enqueue(items("new"), mode)
    assert names(queue) == expected and queue.current.track_id == current


def test_shuffle_preserves_history_and_current_then_restores_pending_only():
    queue = QueueModel()
    queue.replace(items("past", "current", "three", "four", "five"), start=1)
    prefix = queue.order[:2]
    with patch(
        "custom_components.feiniu_music.queue.random.shuffle",
        side_effect=lambda rows: rows.reverse(),
    ):
        queue.set_shuffle(True)
    assert queue.order[:2] == prefix
    assert names(queue) == ["past", "current", "five", "four", "three"]
    queue.advance()
    queue.set_shuffle(False)
    assert names(queue) == ["past", "current", "five", "three", "four"]
    assert queue.current.track_id == "five"


def test_repeat_one_applies_only_to_natural_end_and_all_wraps():
    queue = QueueModel()
    queue.replace(items("one", "two"))
    queue.set_repeat("one")
    assert queue.advance(natural=True).track_id == "one"
    assert queue.advance().track_id == "two"
    assert queue.advance() is None
    queue.set_repeat("all")
    assert queue.advance(natural=True).track_id == "one"
    assert queue.previous().track_id == "two"
    queue.set_repeat("off")
    queue.previous()
    assert queue.previous().track_id == "one"


def test_revision_conflict_and_invalid_move_are_atomic():
    queue = QueueModel()
    queue.replace(items("one", "two", "three"))
    before = queue.snapshot()
    for revision in (-1, True, "1", 0):
        with pytest.raises(RevisionConflict):
            queue.remove(queue.current_id, revision)
    with pytest.raises(QueueError):
        queue.move(queue.current_id, queue.order[-1], queue.revision)
    assert queue.snapshot() == before
    queue.move(queue.order[-1], queue.order[1], queue.revision)
    assert names(queue) == ["one", "three", "two"]
    assert queue.current.track_id == "one"


def test_remove_current_selects_successor_or_none_without_playback_effect():
    queue = QueueModel()
    queue.replace(items("one", "two", "three"))
    assert queue.remove(queue.current_id, queue.revision)
    assert queue.current.track_id == "two"
    queue.advance()
    assert queue.remove(queue.current_id, queue.revision)
    assert queue.current is None and names(queue) == ["two"]


def test_restore_is_lossless_but_contains_no_playback_authority():
    queue = QueueModel()
    queue.replace(items("one", "one", "three"), start=1)
    queue.set_repeat("all")
    queue.set_shuffle(True)
    state = queue.snapshot()
    restored = QueueModel.restore(state)
    assert restored.snapshot() == state
    state["order"].reverse()
    assert restored.order != state["order"]
    assert set(restored.snapshot()) == {
        "schema",
        "items",
        "order",
        "current_id",
        "shuffle",
        "repeat",
        "revision",
    }


@pytest.mark.parametrize(
    "changes",
    [
        {"schema": 2},
        {"schema": True},
        {"items": "bad"},
        {"order": []},
        {"current_id": "missing"},
        {"shuffle": 1},
        {"revision": True},
        {"revision": -1},
        {"repeat": []},
        {"order": [{}]},
    ],
)
def test_corrupt_snapshot_never_partially_restores(changes):
    queue = QueueModel()
    queue.replace(items("one", "two"))
    state = deepcopy(queue.snapshot())
    state.update(changes)
    with pytest.raises(QueueError):
        QueueModel.restore(state)


def test_persistence_rejects_playback_url_and_grant_fields():
    with pytest.raises(QueueError):
        QueueItem.create("one", "https://music.invalid/audio?token=sentinel")
    queue = QueueModel()
    queue.replace(items("one"))
    state = queue.snapshot()
    state["items"][0]["url"] = "https://music.invalid/audio?token=sentinel"
    with pytest.raises(QueueError):
        QueueModel.restore(state)


def test_capacity_and_duplicate_occurrence_fail_before_mutation(monkeypatch):
    queue = QueueModel()
    queue.replace(items("one"))
    monkeypatch.setattr("custom_components.feiniu_music.queue.MAX_QUEUE_ITEMS", 2)
    before = queue.snapshot()
    with pytest.raises(QueueError):
        queue.enqueue(items("two", "three"), "add")
    with pytest.raises(QueueError):
        queue.enqueue([queue.current], "add")
    assert queue.snapshot() == before
