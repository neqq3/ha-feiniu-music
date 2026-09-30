"""Real HA media models with synthetic native responses."""

from unittest.mock import AsyncMock

import pytest
from didl_lite import didl_lite
from homeassistant.components.media_player import SearchMediaQuery
from homeassistant.components.media_source import MediaSourceItem, Unresolvable
from homeassistant.setup import async_setup_component

from custom_components.feiniu_music.const import DOMAIN
from custom_components.feiniu_music.media_source import FeiNiuMediaSource

from .conftest import track


def item(hass, path):
    return MediaSourceItem(hass, DOMAIN, path, None)


async def test_artist_has_native_tracks_and_albums_without_library_scan(hass, runtime, client):
    source = FeiNiuMediaSource(hass)
    base = runtime.entry.entry_id
    client.detail.return_value = {"guid": "artist-one", "name": "Artist"}
    folder = await source.async_browse_media(item(hass, f"{base}/artist/artist-one"))
    assert [child.title for child in folder.children] == ["Tracks", "Albums"]
    client.related.return_value = {"list": [{"guid": "song", "title": "Song"}], "total": 1}
    songs = await source.async_browse_media(item(hass, f"{base}/artist/artist-one/tracks"))
    assert songs.children[0].title == "Song" and songs.children[0].can_play
    client.related.assert_awaited_once_with("artist", "artist-one", 1, albums=False)
    client.page.assert_not_called()
    client.detail.assert_awaited_once_with("artist", "artist-one")


async def test_search_uses_native_filtered_results(hass, runtime, client):
    client.search.return_value = {"list": [track()], "total": 1}
    result = await FeiNiuMediaSource(hass).async_search_media(
        item(hass, f"{runtime.entry.entry_id}/track"), SearchMediaQuery(search_query="Synthetic")
    )
    assert len(result.result) == 1 and result.result[0].title == "Synthetic track"
    client.search.assert_awaited_once_with("track", "Synthetic", 1, 100)
    client.page.assert_not_called()


async def test_resolve_returns_only_signed_ha_url_with_fresh_access_check(hass, runtime, client):
    assert await async_setup_component(hass, "http", {})
    hass.config.internal_url = "http://ha-test.invalid:8123"
    client.detail.return_value = {
        "track": track(filePath="PRIVATE_PATH"),
        "audioSpec": {"format": "flac"},
    }
    original_fields = list(didl_lite.MusicTrack.didl_properties_defs)
    result = await FeiNiuMediaSource(hass).async_resolve_media(
        item(hass, f"{runtime.entry.entry_id}/track/track-one")
    )
    assert didl_lite.MusicTrack.didl_properties_defs == original_fields
    assert result.url.startswith("http://ha-test.invalid:8123/api/feiniu_music/")
    assert "authSig=" in result.url and result.mime_type == "audio/flac"
    assert all(
        secret not in repr(result)
        for secret in ("music.invalid", "SYNTHETIC_PASSWORD", "PRIVATE_PATH", "music-token")
    )
    client.detail.assert_awaited_once()
    client.page.assert_not_called()


async def test_dlna_metadata_contains_title_artist_album_and_ha_artwork(hass, runtime, client):
    assert await async_setup_component(hass, "http", {})
    hass.config.internal_url = "http://ha-test.invalid:8123"
    client.detail.return_value = {
        "track": track(
            title="Title <&>",
            filePath="PRIVATE_PATH",
            coverId="cover-one",
            artists=[{"name": "Artist", "guid": "artist-one"}],
            album={"name": "Album", "guid": "album-one"},
        ),
        "audioSpec": {"format": "flac"},
    }
    resolved = await FeiNiuMediaSource(hass).async_resolve_media(
        item(hass, f"{runtime.entry.entry_id}/track/track-one")
    )
    metadata = resolved.didl_metadata
    assert metadata.title == "Title <&>"
    assert metadata.artist == "Artist" and metadata.album == "Album"
    assert metadata.album_art_uri.startswith("http://ha-test.invalid:8123/api/feiniu_music/")
    assert len(metadata.album_art_uri) < 256
    assert "/artwork?token=" in metadata.album_art_uri
    assert "authSig=" not in metadata.album_art_uri
    assert metadata.resources[0].uri == resolved.url
    wire = didl_lite.to_xml_string(metadata).decode()
    assert "Title &lt;&amp;&gt;" in wire
    assert all(
        secret not in wire
        for secret in ("PRIVATE_PATH", "music.invalid", "music-token", "SYNTHETIC_PASSWORD")
    )


async def test_album_is_browsable_but_not_a_fictitious_queue_player(hass, runtime, client):
    client.page.return_value = {"list": [{"guid": "album-one", "name": "Album"}], "total": 1}
    result = await FeiNiuMediaSource(hass).async_browse_media(
        item(hass, f"{runtime.entry.entry_id}/album")
    )
    assert result.children[0].can_expand and not result.children[0].can_play
    with pytest.raises(Unresolvable):
        await FeiNiuMediaSource(hass).async_resolve_media(
            item(hass, f"{runtime.entry.entry_id}/album/album-one")
        )


async def test_global_browser_keeps_queue_context_but_direct_player_resolves_one_track(
    hass, runtime, client
):
    assert await async_setup_component(hass, "http", {})
    hass.config.internal_url = "http://ha-test.invalid:8123"
    client.related.return_value = {"list": [track("one"), track("two")], "total": 2}
    client.detail.return_value = {"track": track("two")}
    source = FeiNiuMediaSource(hass)
    result = await source.async_browse_media(
        item(hass, f"{runtime.entry.entry_id}/album/album-one")
    )
    selected = result.children[1].media_content_id
    assert selected.endswith("/album/album-one/queue/1/two")
    resolved = await source.async_resolve_media(item(hass, selected.split(f"{DOMAIN}/", 1)[1]))
    assert "/audio/two?" in resolved.url
    client.detail.assert_awaited_once_with("track", "two")
    client.related.assert_awaited_once()


async def test_bad_login_starts_one_reauth_flow_and_does_not_loop(hass, runtime, client):
    from unittest.mock import patch

    from custom_components.feiniu_music.client import AuthenticationError

    client.login.side_effect = AuthenticationError("invalid")
    with patch.object(type(runtime.entry), "async_start_reauth") as reauth:
        for _ in range(2):
            with pytest.raises(AuthenticationError):
                await runtime.call(AsyncMock(side_effect=AuthenticationError("expired")))
        reauth.assert_called_once()
    client.login.assert_awaited_once()
