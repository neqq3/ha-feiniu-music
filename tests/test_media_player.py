"""Exercise queues against real HA entity services and state events, without a NAS."""

import asyncio
from types import MethodType, SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from xml.etree import ElementTree as ET

import pytest
from async_upnp_client.profiles.dlna import DmrDevice, TransportState
from homeassistant.components.dlna_dmr.media_player import DlnaDmrEntity
from homeassistant.components.media_player import (
    DATA_COMPONENT,
    MediaPlayerEntity,
    MediaPlayerState,
    RepeatMode,
)
from homeassistant.components.media_player import (
    MediaPlayerEntityFeature as Feature,
)
from homeassistant.exceptions import (
    HomeAssistantError,
    ServiceNotSupported,
    ServiceValidationError,
)
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.feiniu_music.const import DOMAIN
from custom_components.feiniu_music.media_player import FeiNiuPlayer
from custom_components.feiniu_music.output import OutputBinding, OutputLeases
from custom_components.feiniu_music.queue import QueueModel
from custom_components.feiniu_music.session import OutputProfile
from custom_components.feiniu_music.storage import SavedSession

from .conftest import track


class TestOutput(MediaPlayerEntity):
    """Small output device: queue behavior must come from the integration under test."""

    __test__ = False
    _attr_should_poll = False
    _attr_name = "Synthetic speaker"
    _attr_state = MediaPlayerState.IDLE
    _attr_supported_features = (
        Feature.PLAY_MEDIA
        | Feature.PLAY
        | Feature.PAUSE
        | Feature.STOP
        | Feature.SEEK
        | Feature.VOLUME_SET
        | Feature.VOLUME_MUTE
    )
    _attr_volume_level = 0.2
    _attr_is_volume_muted = False

    def __init__(self):
        self.calls = []
        self.entity_id = "media_player.synthetic_output"

    async def async_play_media(self, media_type, media_id, **kwargs):
        self.calls.append((media_id, kwargs))
        self._attr_media_content_id = media_id
        self._attr_media_duration = 10
        self._attr_media_position = 0
        self._attr_media_position_updated_at = dt_util.utcnow()
        self._attr_state = MediaPlayerState.PLAYING
        self.async_write_ha_state()

    async def async_media_pause(self):
        self._attr_state = MediaPlayerState.PAUSED
        self.async_write_ha_state()

    async def async_media_play(self):
        self._attr_state = MediaPlayerState.PLAYING
        self.async_write_ha_state()

    async def async_media_stop(self):
        self._attr_state = MediaPlayerState.IDLE
        self.async_write_ha_state()

    async def async_media_seek(self, position):
        self._attr_media_position = position
        self._attr_media_position_updated_at = dt_util.utcnow()
        self.async_write_ha_state()

    async def async_set_volume_level(self, volume):
        self._attr_volume_level = volume
        self.async_write_ha_state()

    async def async_mute_volume(self, mute):
        self._attr_is_volume_muted = mute
        self.async_write_ha_state()


@pytest.fixture
async def player(hass, runtime, client):
    assert await async_setup_component(hass, "http", {})
    assert await async_setup_component(hass, "media_player", {})
    hass.config.internal_url = "http://ha-test.invalid:8123"

    async def detail(kind, guid):
        assert kind == "track"
        return {
            "track": track(
                guid,
                title=f"Title {guid}",
                duration=10000,
                coverId=f"cover-{guid}",
                artists=[{"name": "Artist"}],
                album={"name": "Album"},
            )
        }

    client.detail.side_effect = detail
    client.related.return_value = {"list": [track("one"), track("two"), track("three")], "total": 3}
    client.page.return_value = client.related.return_value
    speaker = TestOutput()
    await hass.data[DATA_COMPONENT].async_add_entities([speaker])
    saved = SavedSession(
        OutputBinding.from_entity(hass, speaker.entity_id),
        QueueModel(),
        OutputProfile(confirmation="reported"),
    )
    controller = FeiNiuPlayer(runtime, saved, OutputLeases(), Mock())
    controller.entity_id = "media_player.feiniu_test"
    await hass.data[DATA_COMPONENT].async_add_entities([controller])
    await hass.async_block_till_done()
    yield controller, speaker
    await controller.async_remove()


def uri(runtime, path="album/album-one"):
    return f"media-source://{DOMAIN}/{runtime.entry.entry_id}/{path}"


async def finish(hass, speaker):
    await speaker.async_media_seek(10)
    await hass.async_block_till_done()
    await speaker.async_media_stop()
    await hass.async_block_till_done()


def played_ids(speaker):
    return [url.split("?")[0].rsplit("/", 1)[-1] for url, _ in speaker.calls]


async def test_ha_full_player_artwork_does_not_change_speaker_thumbnail(hass, player, runtime):
    controller, speaker = player
    await controller.async_play_media("music", uri(runtime, "track/one"))
    await hass.async_block_till_done()
    speaker_artwork = speaker.calls[-1][1]["extra"]["thumb"]
    assert speaker_artwork and "size=" not in speaker_artwork
    assert controller.media_image_url == speaker_artwork + "&size=1024"


async def test_queue_metadata_survives_actual_dlna_serialization(hass, player, runtime):
    """Keep HA and UPnP metadata conversion real; stub only the device/network boundary."""
    controller, speaker = player
    with patch.object(speaker, "async_play_media", wraps=speaker.async_play_media) as play:
        await controller.async_play_media("music", uri(runtime, "track/one"))
        await hass.async_block_till_done()
    device = SimpleNamespace(
        can_stop=False,
        profile_device=SimpleNamespace(available=True),
        transport_state=TransportState.PLAYING,
        _fetch_headers=AsyncMock(return_value={"Content-Type": "audio/flac"}),
        async_set_transport_uri=AsyncMock(),
    )
    device.construct_play_media_metadata = MethodType(
        DmrDevice.construct_play_media_metadata, device
    )
    dlna = DlnaDmrEntity(
        "uuid:synthetic",
        "urn:schemas-upnp-org:device:MediaRenderer:1",
        "Synthetic",
        0,
        None,
        False,
        "http://output.invalid/description",
        None,
        False,
        MockConfigEntry(domain="dlna_dmr"),
    )
    dlna.hass = hass
    dlna._device = device
    await dlna.async_play_media(**play.await_args.kwargs)
    wire = ET.fromstring(device.async_set_transport_uri.await_args.args[2])
    fields = {node.tag.rsplit("}", 1)[-1]: node for node in wire.iter() if len(node) == 0}
    assert fields["class"].text == "object.item.audioItem.musicTrack"
    assert fields["title"].text == "Title one"
    assert fields["artist"].text == "Artist"
    assert fields["album"].text == "Album"
    assert fields["albumArtURI"].text == play.await_args.kwargs["extra"]["thumb"]
    assert len(fields["albumArtURI"].text) < 256
    assert fields["res"].attrib["protocolInfo"] == "http-get:*:audio/flac:*"


async def test_browse_song_carries_list_context_and_starts_at_selected_position(
    hass, player, runtime, client
):
    controller, speaker = player
    result = await controller.async_browse_media(media_content_id=uri(runtime))
    assert result.can_play and len(result.children) == 3
    await controller.async_play_media("music", result.children[1].media_content_id)
    await hass.async_block_till_done()
    assert played_ids(speaker) == ["two"]
    assert controller.extra_state_attributes["queue_length"] == 3
    assert controller.extra_state_attributes["queue_position"] == 2
    assert controller.media_title == "Title two" and controller.media_artist == "Artist"
    await controller.async_media_next_track()
    await controller.async_media_previous_track()
    assert played_ids(speaker) == ["two", "three", "two"]
    client.page.assert_not_called()
    assert client.detail.await_count == 3
    assert "authSig" not in repr(hass.states.get(controller.entity_id).attributes)
    assert "music-token" not in repr(hass.states.get(controller.entity_id).attributes)


async def test_changed_browse_context_does_not_silently_play_another_track(player, runtime, client):
    controller, speaker = player
    result = await controller.async_browse_media(media_content_id=uri(runtime))
    client.related.return_value = {"list": [track("new"), track("three")], "total": 2}
    with pytest.raises(ServiceValidationError, match="list changed"):
        await controller.async_play_media("music", result.children[1].media_content_id)
    assert speaker.calls == []


async def test_playlist_filtering_keeps_duplicate_queue_positions(player, runtime, client):
    controller, speaker = player
    client.related.return_value = {
        "list": [track("one"), track("denied", accessStatus=2), track("one"), track("two")],
        "total": 4,
    }
    await controller.async_play_media("playlist", uri(runtime, "playlist/list-one"))
    await controller.async_media_next_track()
    await controller.async_media_next_track()
    assert played_ids(speaker) == ["one", "one", "two"]
    assert controller.extra_state_attributes["queue_length"] == 3
    client.page.assert_not_called()


async def test_natural_completion_advances_once_and_queue_ends(hass, player, runtime):
    controller, speaker = player
    await controller.async_play_media("album", uri(runtime))
    for _ in range(3):
        await finish(hass, speaker)
    assert played_ids(speaker) == ["one", "two", "three"]
    assert controller.state == MediaPlayerState.IDLE
    assert not controller.extra_state_attributes["queue_active"]


async def test_stop_near_end_and_pause_resume_do_not_advance(hass, player, runtime):
    controller, speaker = player
    await controller.async_play_media("album", uri(runtime))
    await controller.async_media_pause()
    await hass.async_block_till_done()
    assert controller.state == MediaPlayerState.PAUSED
    await controller.async_media_pause()
    await controller.async_media_play()
    await hass.async_block_till_done()
    await controller.async_media_play()
    await controller.async_media_seek(9.5)
    await hass.async_block_till_done()
    await controller.async_media_stop()
    await hass.async_block_till_done()
    assert played_ids(speaker) == ["one"]
    assert controller.state == MediaPlayerState.IDLE


async def test_controls_follow_outputs_dynamic_transport_capabilities(hass, player, runtime):
    controller, speaker = player
    await controller.async_play_media("album", uri(runtime))
    # DLNA may report PLAYING before its available transport actions are updated.
    speaker._attr_supported_features &= ~Feature.PAUSE
    speaker.async_write_ha_state()
    await hass.async_block_till_done()
    assert not controller.supported_features & Feature.PAUSE
    with pytest.raises(ServiceNotSupported):
        await hass.services.async_call(
            "media_player", "media_pause", {"entity_id": controller.entity_id}, blocking=True
        )
    speaker._attr_supported_features |= Feature.PAUSE
    speaker.async_write_ha_state()
    await hass.async_block_till_done()
    assert controller.supported_features & Feature.PAUSE
    await hass.services.async_call(
        "media_player", "media_pause", {"entity_id": controller.entity_id}, blocking=True
    )
    await hass.async_block_till_done()
    assert controller.state == speaker.state == MediaPlayerState.PAUSED
    assert played_ids(speaker) == ["one"]


@pytest.mark.parametrize("interruption", ["early_stop", "unavailable", "foreign"])
async def test_interruption_is_not_mistaken_for_track_end(hass, player, runtime, interruption):
    controller, speaker = player
    await controller.async_play_media("album", uri(runtime))
    await hass.async_block_till_done()
    if interruption == "early_stop":
        await speaker.async_media_stop()
    elif interruption == "unavailable":
        hass.states.async_set(speaker.entity_id, "unavailable", {})
    else:
        await speaker.async_play_media("music", "http://another-service.invalid/track")
    await hass.async_block_till_done()
    assert len(speaker.calls) == (2 if interruption == "foreign" else 1)
    assert not controller.extra_state_attributes["queue_active"]


async def test_repeat_one_and_all_and_manual_next(hass, player, runtime):
    controller, speaker = player
    await controller.async_play_media("album", uri(runtime))
    await controller.async_set_repeat("one")
    await finish(hass, speaker)
    assert played_ids(speaker) == ["one", "one"]
    await controller.async_media_next_track()
    assert played_ids(speaker)[-1] == "two"
    await controller.async_set_repeat("all")
    await controller.async_media_next_track()
    await finish(hass, speaker)
    assert played_ids(speaker)[-2:] == ["three", "one"]
    assert controller.repeat == RepeatMode.ALL


async def test_shuffle_preserves_current_and_duplicate_members_and_can_restore_order(
    player, runtime, client
):
    controller, speaker = player
    client.related.return_value = {
        "list": [track("one"), track("two"), track("one"), track("three")],
        "total": 4,
    }
    await controller.async_play_media("playlist", uri(runtime, "playlist/list-one"))
    with patch(
        "custom_components.feiniu_music.queue.random.shuffle",
        side_effect=lambda values: values.reverse(),
    ):
        await controller.async_set_shuffle(True)
    assert played_ids(speaker) == ["one"]
    await controller.async_media_next_track()
    assert played_ids(speaker)[-1] == "three"
    await controller.async_set_shuffle(False)
    assert controller.extra_state_attributes["queue_position"] == 2
    assert [controller.saved.queue.items[key].track_id for key in controller.saved.queue.order] == [
        "one",
        "three",
        "two",
        "one",
    ]
    await controller.async_media_previous_track()
    assert played_ids(speaker)[-1] == "one"
    assert controller.extra_state_attributes["queue_length"] == 4


async def test_standard_enqueue_modes_and_clear(hass, player, runtime):
    controller, speaker = player
    await controller.async_play_media("music", uri(runtime, "track/one"))
    await controller.async_play_media("music", uri(runtime, "track/last"), enqueue="add")
    await controller.async_play_media("music", uri(runtime, "track/next"), enqueue="next")
    assert played_ids(speaker) == ["one"]
    await controller.async_media_next_track()
    await controller.async_play_media("music", uri(runtime, "track/now"), enqueue="play")
    await controller.async_media_next_track()
    assert played_ids(speaker) == ["one", "next", "now", "last"]
    await controller.async_clear_playlist()
    await hass.async_block_till_done()
    assert controller.extra_state_attributes["queue_length"] == 0
    assert controller.state == MediaPlayerState.IDLE


async def test_next_rechecks_permission_and_stops_on_denial(hass, player, runtime, client):
    controller, speaker = player
    await controller.async_play_media("album", uri(runtime))
    client.detail.side_effect = None
    client.detail.return_value = {"track": track("two", accessStatus=2)}
    await finish(hass, speaker)
    assert played_ids(speaker) == ["one"]
    assert controller.extra_state_attributes["last_queue_error"] == "PermissionDeniedError"
    assert not controller.extra_state_attributes["queue_active"]
    client.login.assert_not_called()


async def test_other_account_urls_rejected_before_fetch(player, runtime, client):
    controller, speaker = player
    with pytest.raises(HomeAssistantError):
        await controller.async_play_media("music", "media-source://feiniu_music/other/track/one")
    assert speaker.calls == []
    client.detail.assert_not_called()
    client.related.assert_not_called()


async def test_concurrent_next_preserves_two_intents_but_can_cancel_middle_load(player, runtime):
    controller, speaker = player
    await controller.async_play_media("album", uri(runtime))
    await asyncio.gather(controller.async_media_next_track(), controller.async_media_next_track())
    assert played_ids(speaker) in (["one", "three"], ["one", "two", "three"])
    assert controller.saved.queue.current.track_id == "three"


async def test_fixed_output_does_not_offer_runtime_source_switching(hass, player, runtime):
    controller, speaker = player
    assert controller.output.entity_id == speaker.entity_id
    assert not controller.supported_features & Feature.SELECT_SOURCE
    assert speaker.calls == []
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "media_player",
            "select_source",
            {"entity_id": controller.entity_id, "source": speaker.entity_id},
            blocking=True,
        )


async def test_unload_detaches_end_listener(hass, player, runtime):
    controller, speaker = player
    await controller.async_play_media("album", uri(runtime))
    await controller.async_will_remove_from_hass()
    await finish(hass, speaker)
    assert played_ids(speaker) == ["one"]


async def test_real_entry_setup_loads_and_unloads_player_platform(hass, entry, client):
    hass.states.async_set(
        "media_player.synthetic_output", "idle", {"supported_features": Feature.PLAY_MEDIA}
    )
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        entry, options={"output_player": "media_player.synthetic_output"}
    )
    with patch("custom_components.feiniu_music.create_client", return_value=client):
        assert await async_setup_component(hass, DOMAIN, {})
        await hass.async_block_till_done()
        players = [
            s for s in hass.states.async_all("media_player") if s.attributes.get("feiniu_queue")
        ]
        assert len(players) == 1 and players[0].attributes["queue_length"] == 0
        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
        assert entry.entry_id not in hass.data[DOMAIN]["entries"]
    client.__aexit__.assert_awaited_once()


async def test_add_or_next_context_song_enqueues_only_selected_occurrence(player, client):
    controller, speaker = player
    client.page.return_value = {"list": [track("one"), track("two"), track("three")], "total": 3}
    entry = controller.runtime.entry.entry_id
    selected = f"media-source://feiniu_music/{entry}/track/queue/1/two"
    await controller.async_play_media("music", selected, enqueue="add")
    await controller.async_play_media("music", selected, enqueue="next")
    queue = controller.control.queue
    assert [queue.items[key].track_id for key in queue.order] == ["two", "two"]
    assert len(set(queue.order)) == 2
    assert not speaker.calls
