"""Registry identity and native HA storage; neither restoration nor rename sends audio."""

from copy import deepcopy
from itertools import product

import pytest
from homeassistant.components.media_player import MediaPlayerEntityFeature as Feature
from homeassistant.helpers import entity_registry as er

from custom_components.feiniu_music.output import OutputAdapter, OutputBinding, validate_output
from custom_components.feiniu_music.queue import QueueError, QueueItem, QueueModel
from custom_components.feiniu_music.session import OutputProfile
from custom_components.feiniu_music.storage import QueueStorage, SavedSession


@pytest.mark.parametrize(
    "case,reason",
    [
        ("not_media", "output_not_media_player"),
        ("self", "output_self"),
        ("state_self", "output_self"),
        ("missing_registry", "output_missing_registry"),
        ("offline", "output_unavailable"),
        ("missing", "output_unavailable"),
        ("unsupported", "output_no_play_media"),
        ("bad_flags", "output_no_play_media"),
        ("loop", "output_wrapper_loop"),
        ("wrapped", "output_wrapped_feiniu"),
    ],
)
def test_output_validation_classifies_real_backend_failures(hass, case, reason):
    from custom_components.feiniu_music.const import DOMAIN
    from custom_components.feiniu_music.output import OutputValidationError

    entity_id = "light.invalid" if case == "not_media" else "media_player.synthetic"
    registry = er.async_get(hass)
    if case == "self":
        entry = registry.async_get_or_create(
            "media_player", DOMAIN, "test", suggested_object_id="synthetic"
        )
        entity_id = entry.entity_id
    attrs = {"supported_features": Feature.PLAY_MEDIA}
    if case == "unsupported":
        attrs["supported_features"] = Feature.PLAY | Feature.PAUSE | Feature.VOLUME_SET
    if case == "bad_flags":
        attrs["supported_features"] = True
    if case == "state_self":
        attrs["feiniu_queue"] = True
    if case == "loop":
        attrs["entity_id"] = [entity_id]
    if case == "wrapped":
        attrs["entity_id"] = ["media_player.proxy"]
        hass.states.async_set("media_player.proxy", "idle", {"feiniu_queue": True})
    if case != "missing":
        hass.states.async_set(entity_id, "unavailable" if case == "offline" else "idle", attrs)
    with pytest.raises(OutputValidationError) as raised:
        binding = OutputBinding.from_entity(hass, entity_id)
        if case == "missing_registry":
            binding = OutputBinding("registry:deleted", entity_id)
        validate_output(hass, binding)
    assert raised.value.reason == reason
    if case in {"offline", "missing", "missing_registry"}:
        validate_output(hass, binding, existing=True)


def test_output_validation_logs_only_anonymous_binding_context(hass, caplog):
    import logging

    from custom_components.feiniu_music.output import OutputValidationError

    caplog.set_level(logging.DEBUG, logger="custom_components.feiniu_music")
    hass.states.async_set(
        "media_player.private_account_mac",
        "idle",
        {
            "supported_features": Feature.PAUSE,
            "friendly_name": "PRIVATE_PAYLOAD",
            "xiaoai_id": "PRIVATE_PAYLOAD",
            "source": "PRIVATE_PAYLOAD",
        },
    )
    with pytest.raises(OutputValidationError):
        validate_output(hass, OutputBinding.from_entity(hass, "media_player.private_account_mac"))
    assert "output_no_play_media" in caplog.text
    own = " ".join(
        r.getMessage()
        for r in caplog.records
        if r.name.startswith("custom_components.feiniu_music")
    )
    assert "private_account_mac" not in own and "PRIVATE_PAYLOAD" not in own


async def test_registry_uuid_tracks_rename_and_offline_without_changing_binding(hass):
    registry = er.async_get(hass)
    entry = registry.async_get_or_create(
        "media_player", "test", "output-one", suggested_object_id="one"
    )
    hass.states.async_set(entry.entity_id, "idle", {"supported_features": Feature.PLAY_MEDIA})
    binding = OutputBinding.from_entity(hass, entry.entity_id)
    validate_output(hass, binding)
    changes = []
    output = OutputAdapter(hass, binding)
    output.subscribe(lambda old, new: changes.append(new))
    registry.async_update_entity(entry.entity_id, new_entity_id="media_player.renamed")
    await hass.async_block_till_done()
    assert output.entity_id == "media_player.renamed" and binding.key == f"registry:{entry.id}"
    hass.states.async_set(output.entity_id, "unavailable", {"supported_features": 0})
    await hass.async_block_till_done()
    validate_output(hass, binding, existing=True)
    assert not output.available and changes[-1].state == "unavailable"
    registry.async_remove(output.entity_id)
    await hass.async_block_till_done()
    assert output.entity_id is None and changes[-1] is None
    output.close()


def test_unregistered_output_has_explicit_entity_id_fallback_and_no_name_guess(hass):
    hass.states.async_set("media_player.plain", "idle", {"supported_features": Feature.PLAY_MEDIA})
    binding = OutputBinding.from_entity(hass, "media_player.plain")
    assert binding.key == "entity:media_player.plain"
    hass.states.async_remove("media_player.plain")
    hass.states.async_set("media_player.other", "idle", {"supported_features": Feature.PLAY_MEDIA})
    assert binding.resolve(hass) == "media_player.plain"
    assert not OutputAdapter(hass, binding).available


def test_known_group_wrapper_cycle_and_self_proxy_are_rejected(hass):
    hass.states.async_set(
        "media_player.feiniu",
        "idle",
        {"feiniu_queue": True, "supported_features": Feature.PLAY_MEDIA},
    )
    hass.states.async_set(
        "media_player.group",
        "idle",
        {"entity_id": ["media_player.feiniu"], "supported_features": Feature.PLAY_MEDIA},
    )
    from homeassistant.exceptions import ServiceValidationError

    with pytest.raises(ServiceValidationError):
        validate_output(hass, OutputBinding.from_entity(hass, "media_player.group"))


def saved(binding, account="account-one"):
    queue = QueueModel()
    queue.replace(
        [QueueItem.create("track", f"media-source://feiniu_music/{account}/album/example")]
    )
    queue.set_repeat("all")
    return SavedSession(binding, queue, OutputProfile(), 12.5, -0.25)


async def test_store_roundtrip_uses_ha_store_with_no_transport_grants(hass, hass_storage):
    binding = OutputBinding("entity:media_player.one", "media_player.one")
    storage = QueueStorage(hass, "account-one")
    assert await storage.load() == {}
    storage.stage(saved(binding))
    await storage.flush()
    restarted = QueueStorage(hass, "account-one")
    restored = await restarted.load()
    assert restored[binding.key].queue.current.track_id == "track"
    assert restored[binding.key].position == 12.5
    assert restored[binding.key].lyric_offset == -0.25
    stored = hass_storage[storage.store.key]
    assert stored["version"] == 2 and "outputs" in stored["data"]
    assert all(value not in str(stored) for value in ("authSig", "Cookie", "http://", "monotonic"))
    assert restored[binding.key].snapshot() == saved_snapshot(restored[binding.key])


def saved_snapshot(value):
    return SavedSession.restore(value.snapshot(), "account-one").snapshot()


async def test_accounts_and_unselected_output_records_are_isolated(hass):
    a = QueueStorage(hass, "account-one")
    b = QueueStorage(hass, "account-two")
    one = OutputBinding("entity:media_player.one", "media_player.one")
    two = OutputBinding("entity:media_player.two", "media_player.two")
    a.stage(saved(one))
    a.stage(saved(two))
    b.stage(saved(one, "account-two"))
    await a.flush()
    await b.flush()
    # No removal on deselection/unload: record two remains without a live entity.
    a.stage(saved(one))
    await a.flush()
    assert len(await QueueStorage(hass, "account-one").load()) == 2
    await a.delete()
    assert await QueueStorage(hass, "account-one").load() == {}
    assert len(await QueueStorage(hass, "account-two").load()) == 1


async def test_semantically_corrupt_storage_is_not_silently_overwritten(hass, hass_storage):
    storage = QueueStorage(hass, "account-one")
    broken = {"outputs": {"entity:media_player.one": {"queue": "broken"}}}
    hass_storage[storage.store.key] = {
        "version": 1,
        "minor_version": 1,
        "key": storage.store.key,
        "data": deepcopy(broken),
    }
    assert await storage.load() == {} and storage.corrupt
    with pytest.raises(QueueError, match="repair"):
        storage.stage(saved(OutputBinding("entity:media_player.one", "media_player.one")))
    await storage.flush()
    assert hass_storage[storage.store.key]["data"] == broken


def test_persisted_cross_account_source_and_secret_fields_are_rejected():
    data = saved(OutputBinding("entity:media_player.one", "media_player.one")).snapshot()
    with pytest.raises(QueueError, match="another account"):
        SavedSession.restore(data, "account-two")
    data["url"] = "http://invalid/?authSig=SENTINEL"
    with pytest.raises(QueueError):
        SavedSession.restore(data, "account-one")


@pytest.mark.parametrize(
    "values",
    list(
        product(("delivery", "reported"), (False, True), ("idle", "paused", "off"), (False, True))
    ),
)
async def test_real_ha_store_migrates_all_profiles_and_preserves_offline_outputs(
    hass, hass_storage, values
):
    from .test_feedback_storage import legacy_record

    for account in ("account-one", "account-two"):
        storage = QueueStorage(hass, account)
        original = {
            "outputs": dict(
                legacy_record(account, output, OutputProfile(*values))
                for output in ("selected", "offline")
            )
        }
        hass_storage[storage.store.key] = {
            "version": 1,
            "minor_version": 1,
            "key": storage.store.key,
            "data": deepcopy(original),
        }
        restored = await storage.load()
        assert len(restored) == 2
        assert hass_storage[storage.store.key]["version"] == 2
        again = await QueueStorage(hass, account).load()
        assert {k: v.snapshot() for k, v in again.items()} == {
            k: v.snapshot() for k, v in restored.items()
        }
        for key, value in restored.items():
            expected = original["outputs"][key]
            expected["profile"].update(feedback_mode="standard", unconfirmed_end="manual")
            assert value.snapshot() == expected
