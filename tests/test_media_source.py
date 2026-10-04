"""Real HA media models with synthetic native responses."""

from unittest.mock import AsyncMock

import pytest
from didl_lite import didl_lite
from homeassistant.components.media_player import SearchMediaQuery
from homeassistant.components.media_source import MediaSourceItem, Unresolvable
from homeassistant.setup import async_setup_component

from custom_components.feiniu_music.const import DOMAIN
from custom_components.feiniu_music.media_source import FeiNiuMediaSource
from custom_components.feiniu_music.selection import Selection

from .conftest import track


def item(hass, path):
    return MediaSourceItem(hass, DOMAIN, path, None)


async def test_roots_are_lightweight_even_when_optional_sidebar_is_slow(hass, runtime, client):
    source = FeiNiuMediaSource(hass)
    roots = await source.async_browse_media(item(hass, runtime.entry.entry_id))
    assert len(roots.children) == 4
    for method in (client.page, client.playlists, client.detail, client.cover):
        method.assert_not_called()


async def test_native_pages_global_queue_positions_and_complete_play_all(hass, runtime, client):
    rows = [track(f"test-{i}") for i in range(102)]

    async def page(kind, number, size=100):
        return {"list": rows[(number - 1) * size : number * size], "total": len(rows)}

    client.page.side_effect = page
    selection = Selection(runtime, "media_player.test")
    context = f"media-source://feiniu_music/{runtime.entry.entry_id}/track"
    first = await selection.browse(media_content_id=context)
    assert client.page.await_count == 1
    assert first.can_play and len(first.children) == 101
    link = first.children[-1]
    assert link.media_class == "directory" and not link.can_play
    second = await selection.browse(media_content_id=link.media_content_id)
    assert client.page.await_count == 2
    assert not second.can_play
    assert second.children[0].media_content_id == f"{context}/queue/100/test-100"
    assert second.as_dict()["feiniu_paging"]["total"] == 102
    items, position = await selection.items(second.children[0].media_content_id)
    assert len(items) == 102 and position == 100 and items[position].track_id == "test-100"
    items, position = await selection.items(context)
    assert len(items) == 102 and position == 0
    items, position = await selection.items(
        second.children[0].media_content_id, expand_context=False
    )
    assert len(items) == 1 and position == 0 and items[0].track_id == "test-100"
    rows[100], rows[101] = rows[101], rows[100]
    from homeassistant.exceptions import ServiceValidationError

    with pytest.raises(ServiceValidationError, match="changed"):
        await selection.items(second.children[0].media_content_id)
    with pytest.raises(ServiceValidationError):
        await selection.items(link.media_content_id)


@pytest.mark.parametrize(
    "path", ["album", "artist", "artist/test/tracks", "artist/test/albums", "album/test"]
)
async def test_category_and_relation_page_reads_do_not_scan(hass, runtime, client, path):
    data = {
        "list": [{"guid": f"test-{i}", "name": "test", "title": "test"} for i in range(100)],
        "total": 5000,
    }
    client.page.return_value = client.related.return_value = data
    source = FeiNiuMediaSource(hass)
    result = await source.async_browse_media(item(hass, f"{runtime.entry.entry_id}/{path}"))
    assert len(result.children) == 101
    assert client.page.await_count + client.related.await_count == 1
    assert result.children[-1].media_content_type == "feiniu_page"
    client.detail.assert_not_called()
    client.cover.assert_not_called()


async def test_shared_raw_page_generates_artwork_per_ha_session(hass, runtime, client):
    from types import SimpleNamespace

    from homeassistant.components import websocket_api

    assert await async_setup_component(hass, "http", {})
    client.page.return_value = {"list": [track("test", coverId="test")], "total": 1}
    source = FeiNiuMediaSource(hass)
    urls = []
    for issuer in ("test-1", "test-2", "test-1"):
        token = websocket_api.current_connection.set(SimpleNamespace(refresh_token_id=issuer))
        try:
            page = await source.async_browse_media(item(hass, f"{runtime.entry.entry_id}/track"))
            urls.append(page.children[0].thumbnail)
        finally:
            websocket_api.current_connection.reset(token)
    assert urls[0] != urls[1] and urls[0] == urls[2]
    client.page.assert_awaited_once()
    assert "authSig" not in repr(runtime._browse_results)


async def test_artist_has_native_tracks_and_albums_without_library_scan(hass, runtime, client):
    source = FeiNiuMediaSource(hass)
    base = runtime.entry.entry_id
    client.detail.return_value = {"guid": "artist-one", "name": "Artist"}
    folder = await source.async_browse_media(item(hass, f"{base}/artist/artist-one"))
    assert [child.title for child in folder.children] == ["Tracks", "Albums"]
    client.related.return_value = {"list": [{"guid": "song", "title": "Song"}], "total": 1}
    songs = await source.async_browse_media(item(hass, f"{base}/artist/artist-one/tracks"))
    assert songs.children[0].title == "Song" and songs.children[0].can_play
    client.related.assert_awaited_once_with("artist", "artist-one", 1, 100, albums=False)
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
