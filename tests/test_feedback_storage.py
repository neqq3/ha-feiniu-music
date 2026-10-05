"""Migration transforms are atomic and preserve all non-profile saved data."""

from copy import deepcopy
from dataclasses import asdict
from itertools import product

import pytest

from custom_components.feiniu_music.output import OutputBinding
from custom_components.feiniu_music.queue import QueueError, QueueItem, QueueModel
from custom_components.feiniu_music.session import OutputProfile
from custom_components.feiniu_music.storage import SavedSession, _QueueStore, _restore_outputs


def legacy_record(account, output, profile):
    queue = QueueModel()
    queue.replace(
        [
            QueueItem.create(str(i), f"media-source://feiniu_music/{account}/album/synthetic")
            for i in range(4)
        ]
    )
    queue.set_repeat("all")
    queue.set_shuffle(True)
    binding = OutputBinding(f"entity:media_player.{output}", f"media_player.{output}")
    data = SavedSession(binding, queue, profile, 12.5, -0.5).snapshot()
    data["profile"].pop("feedback_mode")
    data["profile"].pop("unconfirmed_end")
    return binding.key, data


def migrator(account):
    store = object.__new__(_QueueStore)
    store.entry_id = account
    return store


@pytest.mark.parametrize("policy", ["manual", "estimated_duration", "duration_fallback"])
def test_v2_profiles_round_trip_without_playback_runtime(policy):
    profile = OutputProfile(feedback_mode="compatibility", unconfirmed_end=policy)
    _, data = legacy_record("a", "synthetic", profile)
    data["profile"] = asdict(profile)
    restored = SavedSession.restore(data, "a")
    assert restored.profile == profile
    assert restored.snapshot() == data
    assert not any(key in str(data) for key in ("timer", "confirmation_stage", "estimated_elapsed"))


@pytest.mark.parametrize(
    "values",
    list(
        product(("delivery", "reported"), (False, True), ("idle", "paused", "off"), (False, True))
    ),
)
async def test_all_24_v1_profiles_migrate_atomically_with_offline_records(values):
    profile = OutputProfile(*values)
    data = {
        "outputs": dict(
            legacy_record("a", output, profile) for output in ("selected", "offline", "deselected")
        )
    }
    original = deepcopy(data)
    migrated = await migrator("a")._async_migrate_func(1, 1, data)
    assert data == original
    assert len(_restore_outputs(migrated, "a")) == 3
    for key, row in migrated["outputs"].items():
        assert row["profile"] == asdict(profile)
        expected = deepcopy(original["outputs"][key])
        expected["profile"].update(feedback_mode="standard", unconfirmed_end="manual")
        assert row == expected  # Includes occurrence IDs, order, revision, binding and position.
    assert await migrator("a")._async_migrate_func(2, 1, migrated) == migrated
    assert not any(
        token in str(migrated) for token in ("confirmation_stage", "monotonic", "timer", "authSig")
    )
    with pytest.raises(QueueError, match="another account"):
        _restore_outputs(migrated, "b")


@pytest.mark.parametrize(
    "damage", ["profile_extra", "profile_invalid", "queue", "binding", "numeric", "outer"]
)
async def test_invalid_migration_never_changes_source_data(damage):
    key, row = legacy_record("a", "speaker", OutputProfile())
    if damage == "profile_extra":
        row["profile"]["secret"] = "PRIVATE"
    elif damage == "profile_invalid":
        row["profile"]["confirmation"] = "arbitrary"
    elif damage == "queue":
        row["queue"] = "broken"
    elif damage == "binding":
        row["binding"] = {}
    elif damage == "numeric":
        row["position"] = float("inf")
    data = {"outputs": {key: row}}
    if damage == "outer":
        data["extra"] = "broken"
    original = deepcopy(data)
    with pytest.raises((QueueError, ValueError, TypeError, KeyError)):
        await migrator("a")._async_migrate_func(1, 1, data)
    assert data == original
