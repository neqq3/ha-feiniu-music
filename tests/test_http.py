"""Real loopback HTTP and HA authentication, not a mocked stream iterator."""

from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from aiohttp import web
from didl_lite import didl_lite
from homeassistant.components.http.auth import async_sign_path
from homeassistant.components.media_player import (
    DATA_COMPONENT,
    MediaPlayerEntity,
    MediaPlayerState,
)
from homeassistant.components.media_source import MediaSourceItem
from homeassistant.setup import async_setup_component

from custom_components.feiniu_music.client import FeiNiuClient, ProtocolProfile
from custom_components.feiniu_music.const import DOMAIN
from custom_components.feiniu_music.http import FeiNiuArtworkView, FeiNiuAudioView, FeiNiuImageView
from custom_components.feiniu_music.media_source import FeiNiuMediaSource
from custom_components.feiniu_music.runtime import ARTWORK_LIFETIME, FeiNiuRuntime

from .conftest import track

pytestmark = pytest.mark.enable_socket
AUDIO = b"fLaC" + bytes(range(256)) * 600


@pytest.fixture
async def delivery(hass, runtime, aiohttp_server, hass_client_no_auth):
    calls = []
    behavior = {"status": 200, "body": AUDIO, "type": "audio/flac"}

    async def native(request):
        calls.append(
            {"range": request.headers.get("Range"), "cookie": request.headers.get("Cookie")}
        )
        status, payload = behavior["status"], behavior["body"]
        headers = {"Content-Type": behavior["type"], "Accept-Ranges": "bytes"}
        if status == 200 and payload == AUDIO and (value := request.headers.get("Range")):
            start, end = value[6:].split("-")
            start = int(start) if start else max(0, len(AUDIO) - int(end))
            end = min(int(end), len(AUDIO) - 1) if end and value[6] != "-" else len(AUDIO) - 1
            if start >= len(AUDIO):
                return web.Response(status=416, headers={"Content-Range": f"bytes */{len(AUDIO)}"})
            payload = AUDIO[start : end + 1]
            status = 206
            headers["Content-Range"] = f"bytes {start}-{end}/{len(AUDIO)}"
        if status == 302:
            headers["Location"] = behavior["location"]
        return web.Response(status=status, body=payload, headers=headers)

    app = web.Application()
    app.router.add_get("/music/api/v1/track/stream", native)
    server = await aiohttp_server(app)
    client = FeiNiuClient(
        str(server.make_url("/music/")), ProtocolProfile("/music/api/v1", "salt", "key")
    )
    await client.__aenter__()
    client._token = "SYNTHETIC_TOKEN"
    client.detail = AsyncMock(return_value={"track": track()})
    client.login = AsyncMock(return_value={"guid": "account-one"})
    runtime.client = client
    assert await async_setup_component(hass, "http", {})
    hass.http.register_view(FeiNiuAudioView(hass))
    hass.http.register_view(FeiNiuImageView(hass))
    hass.http.register_view(FeiNiuArtworkView(hass))
    browser = await hass_client_no_auth()
    path = f"/api/{DOMAIN}/{runtime.entry.entry_id}/{runtime.scope}/audio/track-one"
    signed = async_sign_path(hass, path, timedelta(minutes=10))
    yield browser, path, signed, calls, behavior
    await runtime.close()


@pytest.mark.parametrize(
    "byte_range,start,end",
    [
        (None, 0, len(AUDIO) - 1),
        ("bytes=0-65535", 0, 65535),
        ("bytes=100000-106553", 100000, 106553),
        ("bytes=-100", len(AUDIO) - 100, len(AUDIO) - 1),
        ("bytes=0-1", 0, 1),
        ("bytes=127-255", 127, 255),
    ],
)
async def test_signed_playback_and_range(delivery, byte_range, start, end):
    browser, _, signed, calls, _ = delivery
    response = await browser.get(signed, headers={"Range": byte_range} if byte_range else {})
    assert response.status == (206 if byte_range else 200)
    assert await response.read() == AUDIO[start : end + 1]
    assert calls == [{"range": byte_range, "cookie": "music-token=SYNTHETIC_TOKEN"}]
    assert "SYNTHETIC_TOKEN" not in str(response.headers)


async def test_unsigned_expired_changed_and_reloaded_paths_cannot_play(hass, delivery, runtime):
    browser, path, signed, calls, _ = delivery
    for url in [
        path,
        async_sign_path(hass, path, timedelta(seconds=-1)),
        signed.replace("track-one", "track-two"),
    ]:
        assert (await browser.get(url)).status == 401
    runtime.scope = "new-scope"
    assert (await browser.get(signed)).status == 404
    assert calls == []


@pytest.mark.parametrize(
    "status,body,kind,expected",
    [
        (403, b"PRIVATE_RESPONSE", "text/plain", 403),
        (200, b'{"code":100004,"msg":"PRIVATE_RESPONSE"}', "application/json", 403),
        (200, b'{"code":100005}', "application/json", 404),
        (200, b"<html>PRIVATE_RESPONSE</html>", "text/html", 502),
    ],
)
async def test_error_bodies_never_become_audio(delivery, runtime, status, body, kind, expected):
    browser, _, signed, calls, behavior = delivery
    behavior.update(status=status, body=body, type=kind)
    response = await browser.get(signed)
    assert response.status == expected
    assert b"PRIVATE_RESPONSE" not in await response.read()
    assert len(calls) == 1
    runtime.client.login.assert_not_called()


async def test_401_has_only_one_reauthentication_attempt(delivery, runtime):
    browser, _, signed, calls, behavior = delivery
    behavior.update(status=401, body=b"expired", type="text/plain")
    response = await browser.get(signed)
    assert response.status == 503 and len(calls) == 2
    runtime.client.login.assert_awaited_once()


async def test_redirect_does_not_forward_cookie(delivery, aiohttp_server):
    browser, _, signed, calls, behavior = delivery
    received = []

    async def unintended(request):
        received.append(dict(request.headers))
        return web.Response(body=AUDIO)

    app = web.Application()
    app.router.add_get("/target", unintended)
    second = await aiohttp_server(app)
    behavior.update(status=302, location=str(second.make_url("/target")), body=b"")
    assert (await browser.get(signed)).status == 502
    assert len(calls) == 1 and received == []


async def test_denied_metadata_stops_before_native_audio(delivery, runtime):
    browser, _, signed, calls, _ = delivery
    runtime.client.detail.return_value = {"track": track(accessStatus=2)}
    assert (await browser.get(signed)).status == 403
    assert calls == []


async def test_invalid_ranges_and_416(delivery):
    browser, _, signed, calls, _ = delivery
    for value in ["bytes=1-2,4-5", "bytes=10-1", "bytes=-0"]:
        assert (await browser.get(signed, headers={"Range": value})).status == 416
    assert calls == []
    response = await browser.get(signed, headers={"Range": "bytes=9999999-"})
    assert response.status == 416 and await response.read() == b""


async def test_head_releases_upstream_without_body(delivery, runtime):
    browser, _, signed, _, _ = delivery
    response = await browser.head(signed)
    assert response.status == 200 and await response.read() == b""
    assert int(response.headers["Content-Length"]) == len(AUDIO)
    assert not runtime._active
    assert not runtime.client._session.connector._acquired


async def test_early_audio_context_exit_releases_response(delivery, runtime):
    async with runtime.client.open_audio("track-one") as upstream:
        assert await anext(upstream.chunks()) == AUDIO[:4096]
        response = upstream.response
    assert response.closed
    assert not runtime.client._session.connector._acquired


async def test_dlna_artwork_survives_uri_limit_and_ha_image_proxy(
    hass, runtime, client, hass_client_no_auth
):
    """Fetch real bytes through HA's player image proxy, not just an image field."""
    assert await async_setup_component(hass, "http", {})
    assert await async_setup_component(hass, "media_player", {})
    hass.http.register_view(FeiNiuArtworkView(hass))
    browser = await hass_client_no_auth()
    hass.config.internal_url = str(browser.make_url("/")).rstrip("/")
    image = bytes.fromhex(
        "89504e470d0a1a0a0000000d4948445200000001000000010804000000b51c0c02"
        "0000000b4944415478da6364f80f00010501012718e3660000000049454e44ae426082"
    )
    client.detail.return_value = {"track": track(coverId="cover-one")}
    client.cover.return_value = image
    result = await FeiNiuMediaSource(hass).async_resolve_media(
        MediaSourceItem(hass, DOMAIN, f"{runtime.entry.entry_id}/track/track-one", None)
    )
    returned = didl_lite.from_xml_string(didl_lite.to_xml_string(result.didl_metadata))[0]
    assert len(returned.album_art_uri) < 256

    player = MediaPlayerEntity()
    player.entity_id = "media_player.synthetic_dlna"
    player._attr_state = MediaPlayerState.PLAYING
    # Emulate only the observed device URI limit; use HA's real proxy/fetch implementation.
    player._attr_media_image_url = returned.album_art_uri[:256]
    await hass.data[DATA_COMPONENT].async_add_entities([player])
    response = await browser.get(player.entity_picture)
    assert response.status == 200 and response.content_type == "image/png"
    assert await response.read() == image
    client.cover.assert_awaited_once_with("cover-one")
    client.page.assert_not_called()


async def test_short_artwork_requires_exact_entry_grant_and_expiry(
    hass, delivery, runtime, monkeypatch
):
    browser, _, _, _, _ = delivery
    clock = [100.0]
    monkeypatch.setattr("custom_components.feiniu_music.runtime.monotonic", lambda: clock[0])
    token = runtime.grant_artwork("track", "track-one", "cover-one")
    path = f"/api/{DOMAIN}/{runtime.entry.entry_id}/artwork"
    assert (await browser.get(path)).status == 404
    assert (await browser.get(path + "?token=forged")).status == 404
    assert (await browser.get(f"/api/{DOMAIN}/different-entry/artwork?token={token}")).status == 404
    # Another entry cannot consume a token minted for the first account.
    other = FeiNiuRuntime(hass, runtime.entry, runtime.client)
    hass.data[DOMAIN]["entries"]["other-entry"] = other
    assert (await browser.get(f"/api/{DOMAIN}/other-entry/artwork?token={token}")).status == 404
    clock[0] += ARTWORK_LIFETIME
    assert (await browser.get(path + f"?token={token}")).status == 404
    runtime.client.detail.assert_not_called()


@pytest.mark.parametrize("status,cover", [(2, "cover-one"), (0, "different-cover")])
async def test_short_artwork_still_checks_owner_access_and_exact_cover(
    delivery, runtime, status, cover
):
    browser, _, _, _, _ = delivery
    token = runtime.grant_artwork("track", "track-one", "cover-one")
    runtime.client.detail.return_value = {"track": track(accessStatus=status, coverId=cover)}
    runtime.client.cover = AsyncMock()
    path = f"/api/{DOMAIN}/{runtime.entry.entry_id}/artwork?token={token}"
    response = await browser.get(path)
    assert response.status == 403
    runtime.client.cover.assert_not_called()


async def test_short_artwork_reload_and_unload_invalidate_grants(hass, delivery, runtime):
    browser, _, _, _, _ = delivery
    token = runtime.grant_artwork("track", "track-one", "cover-one")
    path = f"/api/{DOMAIN}/{runtime.entry.entry_id}/artwork?token={token}"
    await runtime.close()
    assert (await browser.get(path)).status == 404
    replacement = FeiNiuRuntime(hass, runtime.entry, runtime.client)
    hass.data[DOMAIN]["entries"][runtime.entry.entry_id] = replacement
    assert (await browser.get(path)).status == 404
    runtime.client.detail.assert_not_called()
