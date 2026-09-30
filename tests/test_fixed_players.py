"""Fixed sessions through HA platform lifecycle, options, services and authenticated WS."""

import asyncio
from dataclasses import asdict
from unittest.mock import patch

import pytest
from homeassistant.components.media_player import DATA_COMPONENT
from homeassistant.components.media_player import MediaPlayerEntityFeature as Feature
from homeassistant.const import __version__ as HA_VERSION
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component

from custom_components.feiniu_music.const import DOMAIN
from custom_components.feiniu_music.output import OutputBinding
from custom_components.feiniu_music.queue import QueueItem
from custom_components.feiniu_music.session import OutputProfile
from custom_components.feiniu_music.websocket import register

from .conftest import track
from .test_media_player import TestOutput


@pytest.fixture
async def installed(hass, entry, client):
    assert await async_setup_component(hass, "http", {})
    assert await async_setup_component(hass, "media_player", {})
    hass.config.internal_url = "http://ha-test.invalid:8123"
    outputs = []
    for name in ("a", "b", "c"):
        output = TestOutput()
        output.entity_id = f"media_player.fixture_{name}"
        output._attr_unique_id = f"fixture_{name}"
        outputs.append(output)
    await hass.data[DATA_COMPONENT].async_add_entities(outputs)
    entry.add_to_hass(hass)
    selected = [OutputBinding.from_entity(hass, o.entity_id).snapshot() for o in outputs[:2]]
    hass.config_entries.async_update_entry(entry, options={"outputs": selected})

    async def detail(kind, guid):
        return {kind: track(guid, title=f"Title {guid}", duration=10000)}

    client.detail.side_effect = detail
    client.related.return_value = {"list": [track("one"), track("two")], "total": 2}
    with patch("custom_components.feiniu_music.create_client", return_value=client):
        assert await async_setup_component(hass, DOMAIN, {})
        await hass.async_block_till_done()
        manager = hass.data[DOMAIN]["players"][entry.entry_id]
        for player in manager.entities.values():
            player.control.profile = OutputProfile(confirmation="reported")
        yield manager, outputs
        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()


def uri(entry, track_id="one"):
    return f"media-source://feiniu_music/{entry.entry_id}/track/{track_id}"


async def play(hass, player, entry, track_id="one", **kwargs):
    await hass.services.async_call(
        "media_player",
        "play_media",
        {
            "entity_id": player.entity_id,
            "media_content_type": "music",
            "media_content_id": uri(entry, track_id),
            **kwargs,
        },
        blocking=True,
    )
    await hass.async_block_till_done()


async def test_two_entities_services_and_incremental_options_preserve_other_session(
    hass, installed, entry
):
    manager, outputs = installed
    first, second = list(manager.entities.values())
    await asyncio.gather(play(hass, first, entry), play(hass, second, entry, "two"))
    old_session = second.control
    signed_round = outputs[1].calls[-1][0]
    # Remove A and add C while B is playing. This must not reload the account.
    selected = [
        OutputBinding.from_entity(hass, output.entity_id).snapshot() for output in outputs[1:]
    ]
    hass.config_entries.async_update_entry(entry, options={"outputs": selected})
    await hass.async_block_till_done()
    assert first.session.closed
    assert second.control is old_session and second.control.phase == "playing"
    assert outputs[1].calls[-1][0] == signed_round and len(outputs[1].calls) == 1
    assert len(manager.entities) == 2 and not outputs[2].calls
    assert second.saved.queue.current.track_id == "two"
    assert len(entry.runtime_data.audio_rounds) == 1
    assert first.saved.binding.key in manager.storage.records


async def test_reload_restores_queue_preferences_and_position_without_any_output_command(
    hass, installed, entry
):
    manager, outputs = installed
    first = next(iter(manager.entities.values()))
    await play(hass, first, entry)
    await play(hass, first, entry, "two", enqueue="add")
    await first.async_set_repeat("all")
    await first.async_set_shuffle(True)
    await first.async_media_seek(4)
    entity_id, item_id = first.entity_id, first.saved.queue.current_id
    before = list(outputs[0].calls)
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    current = hass.data[DOMAIN]["players"][entry.entry_id]
    restored = current.entities[first.saved.binding.key]
    assert restored.entity_id == entity_id
    assert restored.saved.queue.current_id == item_id and len(restored.saved.queue.items) == 2
    assert restored.saved.queue.repeat == "all" and restored.saved.queue.shuffle
    assert restored.control.phase == "restored" and not restored.control.owned
    assert not entry.runtime_data.audio_rounds and outputs[0].calls == before
    assert restored.saved.position >= 4
    restored.control.profile = OutputProfile(confirmation="reported")
    await hass.services.async_call(
        "media_player", "media_play", {"entity_id": entity_id}, blocking=True
    )
    await hass.async_block_till_done()
    assert len(outputs[0].calls) == len(before) + 1
    assert restored.control.timeline.position() >= 4


async def test_registry_rename_and_offline_keep_entity_identity_and_queue(hass, installed, entry):
    manager, outputs = installed
    player = next(iter(manager.entities.values()))
    await play(hass, player, entry, enqueue="add")
    identity, key = player.entity_id, player.saved.binding.key
    registry = er.async_get(hass)
    registry.async_update_entity(outputs[0].entity_id, new_entity_id="media_player.renamed_fixture")
    await hass.async_block_till_done()
    assert player.output.entity_id == "media_player.renamed_fixture"
    hass.states.async_set("media_player.renamed_fixture", "unavailable")
    await hass.async_block_till_done()
    assert player.entity_id == identity and player.saved.binding.key == key
    assert len(player.saved.queue.items) == 1 and not outputs[0].calls
    assert not player.available
    # Existing selected offline entities survive editing options.
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    flow = await hass.config_entries.options.async_configure(
        flow["flow_id"], {"next_step_id": "outputs"}
    )
    result = await hass.config_entries.options.async_configure(
        flow["flow_id"], {"outputs": ["media_player.renamed_fixture", outputs[1].entity_id]}
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert manager.entities[key] is player


async def test_old_entry_migrates_saved_binding_and_preserves_custom_entity_id(hass, entry, client):
    assert await async_setup_component(hass, "http", {})
    assert await async_setup_component(hass, "media_player", {})
    speaker = TestOutput()
    speaker._attr_unique_id = "old-output"
    await hass.data[DATA_COMPONENT].async_add_entities([speaker])
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        entry, options={"output_player": speaker.entity_id, "unrelated": 42}
    )
    registry = er.async_get(hass)
    old = registry.async_get_or_create(
        "media_player",
        DOMAIN,
        f"{entry.entry_id}_player",
        config_entry=entry,
        suggested_object_id="my_old_music",
    )
    registry.async_update_entity(old.entity_id, name="My custom name")
    with patch("custom_components.feiniu_music.create_client", return_value=client):
        assert await async_setup_component(hass, DOMAIN, {})
        await hass.async_block_till_done()
        manager = hass.data[DOMAIN]["players"][entry.entry_id]
        player = next(iter(manager.entities.values()))
        assert player.entity_id == old.entity_id
        assert registry.async_get(old.entity_id).name == "My custom name"
        assert entry.version == 2 and entry.options["unrelated"] == 42
        assert player.output.entity_id == speaker.entity_id and not speaker.calls
        assert entry.data["device_id"] == "a" * 32
        await hass.config_entries.async_unload(entry.entry_id)


async def test_no_saved_output_creates_repair_not_random_binding(hass, entry, client):
    entry.add_to_hass(hass)
    hass.states.async_set(
        "media_player.do_not_choose", "idle", {"supported_features": Feature.PLAY_MEDIA}
    )
    with patch("custom_components.feiniu_music.create_client", return_value=client):
        assert await async_setup_component(hass, DOMAIN, {})
        await hass.async_block_till_done()
        manager = hass.data[DOMAIN]["players"][entry.entry_id]
        assert manager.entities == {} and entry.options["outputs"] == []
        await hass.config_entries.async_unload(entry.entry_id)


async def test_ws_queue_pages_preserve_duplicates_and_reject_stale_or_cross_entity_edits(
    hass, installed, entry, client, hass_ws_client
):
    manager, _ = installed
    first, second = list(manager.entities.values())
    first.saved.queue.replace(
        [QueueItem.create("one"), QueueItem.create("one"), QueueItem.create("two")]
    )
    ws = await hass_ws_client(hass)
    register(hass)
    await ws.send_json(
        {"id": 1, "type": "feiniu_music/queue", "entity_id": first.entity_id, "limit": 2}
    )
    response = await ws.receive_json()
    assert response["success"], response
    page = response["result"]
    assert page["total"] == 3 and len(page["items"]) == 2
    assert page["items"][0]["item_id"] != page["items"][1]["item_id"]
    assert [item["track_id"] for item in page["items"]] == ["one", "one"]
    await ws.send_json(
        {
            "id": 2,
            "type": "feiniu_music/edit_queue",
            "entity_id": second.entity_id,
            "action": "remove",
            "revision": second.saved.queue.revision,
            "item_id": page["items"][0]["item_id"],
        }
    )
    assert not (await ws.receive_json())["success"]
    assert len(first.saved.queue.items) == 3
    first.saved.queue.set_shuffle(True)
    await ws.send_json(
        {
            "id": 3,
            "type": "feiniu_music/edit_queue",
            "entity_id": first.entity_id,
            "action": "remove",
            "revision": page["revision"],
            "item_id": page["items"][0]["item_id"],
        }
    )
    assert (await ws.receive_json())["error"]["code"] == "revision_conflict"
    assert len(first.saved.queue.items) == 3
    assert "SYNTHETIC_PASSWORD" not in str(response) and "authSig" not in str(page["diagnostics"])


async def test_ws_respects_entity_read_and_output_control_permissions(
    hass, installed, entry, hass_ws_client, hass_admin_user
):
    manager, outputs = installed
    player = next(iter(manager.entities.values()))
    ws = await hass_ws_client(hass)
    register(hass)
    with patch.object(type(hass_admin_user.permissions), "check_entity", return_value=False):
        await ws.send_json({"id": 1, "type": "feiniu_music/queue", "entity_id": player.entity_id})
        assert (await ws.receive_json())["error"]["code"] == "unauthorized"
    with patch.object(
        type(hass_admin_user.permissions),
        "check_entity",
        side_effect=lambda entity, policy: entity != outputs[0].entity_id,
    ):
        await ws.send_json(
            {
                "id": 2,
                "type": "feiniu_music/edit_queue",
                "entity_id": player.entity_id,
                "action": "clear",
                "revision": player.saved.queue.revision,
            }
        )
        assert (await ws.receive_json())["error"]["code"] == "unauthorized"
    assert not outputs[0].calls


async def test_slow_lyrics_for_previous_item_never_become_current(
    hass, installed, entry, client, hass_ws_client
):
    manager, _ = installed
    player = next(iter(manager.entities.values()))
    await play(hass, player, entry)
    reached, release = asyncio.Event(), asyncio.Event()

    async def lyrics(guid):
        reached.set()
        await release.wait()
        return {"list": [{"content": "[00:01]Old line"}]}

    client.lyrics.side_effect = lyrics
    ws = await hass_ws_client(hass)
    register(hass)
    await ws.send_json(
        {
            "id": 1,
            "type": "feiniu_music/lyrics",
            "entity_id": player.entity_id,
            "round": player.control.round_id,
            "item_id": player.saved.queue.current_id,
        }
    )
    await reached.wait()
    await play(hass, player, entry, "two")
    release.set()
    result = await ws.receive_json()
    assert result["error"]["code"] == "revision_conflict"
    assert "Old line" not in str(result) and player.control.phase == "playing"


async def test_diagnostics_contains_only_bounded_operational_context(hass, installed, entry):
    import json

    from custom_components.feiniu_music.diagnostics import async_get_config_entry_diagnostics

    manager, outputs = installed
    player = next(iter(manager.entities.values()))
    await play(hass, player, entry)
    result = await async_get_config_entry_diagnostics(hass, entry)
    encoded = json.dumps(result)
    assert result["integration_version"] == "1.0.0"
    assert result["ha_version"] == HA_VERSION
    assert len(result["sessions"]) == 2
    assert result["sessions"][0]["session"]["phase"] == "playing"
    for forbidden in (entry.entry_id, "http://", "https://", "authSig", "password", "Title one"):
        assert forbidden not in encoded


async def playback_options(hass, entry, player):
    """Use HA's actual menu and forms; no custom card or direct flow-method calls."""
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    assert flow["type"] == FlowResultType.MENU
    flow = await hass.config_entries.options.async_configure(
        flow["flow_id"], {"next_step_id": "playback"}
    )
    selector = next(iter(flow["data_schema"].schema.values()))
    assert any(player.entity_id in option["label"] for option in selector.config["options"])
    flow = await hass.config_entries.options.async_configure(
        flow["flow_id"], {"output": player.saved.binding.key}
    )
    assert flow["step_id"] == "playback_profile"
    return flow


async def test_native_playback_options_are_per_proxy_persistent_and_do_not_restart(
    hass, installed, entry
):
    manager, outputs = installed
    first, second = list(manager.entities.values())
    await asyncio.gather(play(hass, first, entry), play(hass, second, entry, "two"))
    first.saved.lyric_offset = 1.5
    queues = [p.saved.queue.snapshot() for p in (first, second)]
    sessions = [p.control for p in (first, second)]
    options = dict(entry.options)
    with (
        patch.object(first.output, "send", wraps=first.output.send) as first_send,
        patch.object(second.output, "send", wraps=second.output.send) as second_send,
    ):
        flow = await playback_options(hass, entry, first)
        assert flow["data_schema"]({}) == asdict(first.control.profile)
        settings = asdict(OutputProfile(confirmation="delivery", play_once=True, weak_end=True))
        result = await hass.config_entries.options.async_configure(flow["flow_id"], settings)
        assert result["type"] == FlowResultType.CREATE_ENTRY
        await hass.async_block_till_done()
        first_send.assert_not_called()
        second_send.assert_not_called()
    assert [p.control for p in (first, second)] == sessions
    assert [p.saved.queue.snapshot() for p in (first, second)] == queues
    assert first.control.phase == second.control.phase == "playing"
    assert first.control.profile == OutputProfile(**settings)
    assert second.control.profile == OutputProfile(confirmation="reported")
    assert first.saved.lyric_offset == 1.5
    assert hass.states.get(first.entity_id).attributes["playback_profile"] == settings
    assert entry.options == options  # No second preference store in config-entry options.
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    restored = hass.data[DOMAIN]["players"][entry.entry_id]
    assert restored.entities[first.saved.binding.key].control.profile == OutputProfile(**settings)
    assert restored.entities[second.saved.binding.key].control.profile == second.saved.profile
    assert restored.entities[first.saved.binding.key].saved.lyric_offset == 1.5
    assert [len(output.calls) for output in outputs] == [1, 1, 0]


async def test_card_and_native_settings_share_state_without_overwriting_unedited_fields(
    hass, installed, entry, hass_ws_client
):
    manager, outputs = installed
    first, second = list(manager.entities.values())
    ws = await hass_ws_client(hass)
    register(hass)
    flow = await playback_options(hass, entry, first)
    original = flow["data_schema"]({})
    await ws.send_json(
        {
            "id": 1,
            "type": "feiniu_music/preferences",
            "entity_id": first.entity_id,
            "profile": {"end_state": "off"},
        }
    )
    assert (await ws.receive_json())["success"]
    # Native form was open before the card edit. Only its changed field should win.
    result = await hass.config_entries.options.async_configure(
        flow["flow_id"], {**original, "play_once": True}
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    await ws.send_json(
        {
            "id": 2,
            "type": "feiniu_music/preferences",
            "entity_id": first.entity_id,
            "lyric_offset": 2,
        }
    )
    assert (await ws.receive_json())["success"]
    flow = await playback_options(hass, entry, first)
    assert flow["data_schema"]({}) == asdict(
        OutputProfile(confirmation="reported", end_state="off", play_once=True)
    )
    hass.config_entries.options.async_abort(flow["flow_id"])
    assert second.control.profile == OutputProfile(confirmation="reported")
    assert second.saved.lyric_offset == 0 and first.saved.lyric_offset == 2
    assert all(not output.calls for output in outputs)


async def test_native_profile_can_be_configured_offline_and_cancel_does_not_change_it(
    hass, installed, entry
):
    manager, outputs = installed
    player = next(iter(manager.entities.values()))
    hass.states.async_set(outputs[0].entity_id, "unavailable")
    await hass.async_block_till_done()
    flow = await playback_options(hass, entry, player)
    before = player.control.profile
    hass.config_entries.options.async_abort(flow["flow_id"])
    assert player.control.profile == before
    flow = await playback_options(hass, entry, player)
    result = await hass.config_entries.options.async_configure(
        flow["flow_id"], {**flow["data_schema"]({}), "play_once": True}
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert player.control.profile.play_once
    assert all(not output.calls for output in outputs)


async def test_native_profile_rejects_removed_output_and_handles_empty_selection(
    hass, installed, entry
):
    manager, _ = installed
    player = next(iter(manager.entities.values()))
    flow = await playback_options(hass, entry, player)
    original = flow["data_schema"]({})
    hass.config_entries.async_update_entry(entry, options={"outputs": []})
    await hass.async_block_till_done()
    result = await hass.config_entries.options.async_configure(
        flow["flow_id"], {**original, "play_once": True}
    )
    assert result["reason"] == "output_removed"
    assert player.saved.profile == OutputProfile(confirmation="reported")
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        flow["flow_id"], {"next_step_id": "playback"}
    )
    assert result["reason"] == "no_outputs"


async def test_native_profile_refuses_unloaded_account(hass, entry):
    entry.add_to_hass(hass)
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        flow["flow_id"], {"next_step_id": "playback"}
    )
    assert result["reason"] == "not_loaded"


async def test_card_partial_profile_still_requires_admin(
    hass, installed, hass_ws_client, hass_admin_user
):
    manager, _ = installed
    player = next(iter(manager.entities.values()))
    ws = await hass_ws_client(hass)
    register(hass)
    hass_admin_user.is_owner = False
    hass_admin_user.groups = []
    await ws.send_json(
        {
            "id": 1,
            "type": "feiniu_music/preferences",
            "entity_id": player.entity_id,
            "profile": {"play_once": True},
        }
    )
    assert (await ws.receive_json())["error"]["code"] == "unauthorized"
    assert not player.control.profile.play_once
