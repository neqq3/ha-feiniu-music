"""Real loopback HTTP and HA authentication, not a mocked stream iterator."""

import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock

import aiohttp
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

from custom_components.feiniu_music.artwork import CachedImage, resize_image
from custom_components.feiniu_music.client import FeiNiuClient, ProtocolProfile
from custom_components.feiniu_music.const import DOMAIN
from custom_components.feiniu_music.http import (
    FeiNiuArtworkView,
    FeiNiuAudioView,
    FeiNiuImageView,
    FeiNiuSessionAudioView,
    image_response,
)
from custom_components.feiniu_music.media_source import FeiNiuMediaSource
from custom_components.feiniu_music.runtime import ARTWORK_LIFETIME, FeiNiuRuntime

from .conftest import image_bytes, track

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
        if controls := behavior.get("streaming"):
            index = len(calls) - 1
            response = web.StreamResponse(
                status=status, headers={**headers, "Content-Length": str(len(payload))}
            )
            await response.prepare(request)
            try:
                await response.write(payload[:4096])
                controls["started"][index].set()
                await controls["release"][index].wait()
                await response.write(payload[4096:])
                await response.write_eof()
            except ConnectionResetError:
                pass
            finally:
                controls["finished"][index].set()
            return response
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
    hass.http.register_view(FeiNiuSessionAudioView(hass))
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
    assert response.status == 200 and response.content_type == "image/webp"
    assert await response.read() == resize_image(CachedImage.build(image), 512).data
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


async def test_image_revalidation_checks_owner_before_304(delivery, runtime, monkeypatch):
    browser, _, _, _, _ = delivery
    clock = [100.0]
    monkeypatch.setattr("custom_components.feiniu_music.runtime.monotonic", lambda: clock[0])
    runtime.client.detail.return_value = {"track": track(coverId="cover-one")}
    runtime.client.cover = AsyncMock(return_value=image_bytes())
    token = runtime.grant_artwork("track", "track-one", "cover-one")
    path = f"/api/{DOMAIN}/{runtime.entry.entry_id}/artwork?token={token}"
    first = await browser.get(path)
    assert (
        first.status == 200
        and await first.read()
        == resize_image(CachedImage.build(runtime.client.cover.return_value), 512).data
    )
    assert first.headers["Cache-Control"] == "private, max-age=30, must-revalidate"
    etag = first.headers["ETag"]
    for condition in (etag, f"W/{etag}", "*"):
        repeated = await browser.get(path, headers={"If-None-Match": condition})
        assert repeated.status == 304 and await repeated.read() == b""
        assert repeated.headers["ETag"] == etag
    runtime.client.cover.assert_awaited_once()
    # A matching browser ETag never authorizes an owner or cover by itself.
    clock[0] += 31
    runtime.client.detail.return_value = {"track": track(coverId="cover-one", accessStatus=2)}
    denied = await browser.get(path, headers={"If-None-Match": etag})
    assert denied.status == 403
    runtime.client.cover.assert_awaited_once()


async def test_image_changed_after_cache_expiry_returns_new_body(delivery, runtime, monkeypatch):
    from custom_components.feiniu_music.runtime import COVER_TTL

    browser, _, _, _, _ = delivery
    clock = [100.0]
    monkeypatch.setattr("custom_components.feiniu_music.runtime.monotonic", lambda: clock[0])
    monkeypatch.setattr("custom_components.feiniu_music.artwork.time", lambda: clock[0])
    runtime.client.detail.return_value = {"track": track(coverId="cover-one")}
    runtime.client.cover = AsyncMock(return_value=image_bytes("red"))
    path = f"/api/{DOMAIN}/{runtime.entry.entry_id}/{runtime.scope}/image/track/track-one/cover-one"
    path = async_sign_path(runtime.hass, path, timedelta(minutes=10))
    first = await browser.get(path)
    assert first.status == 200
    etag = first.headers["ETag"]
    clock[0] += COVER_TTL
    runtime.client.cover.return_value = image_bytes("blue")
    changed = await browser.get(path, headers={"If-None-Match": etag})
    assert changed.status == 200 and changed.headers["ETag"] != etag
    assert (
        await changed.read()
        == resize_image(CachedImage.build(runtime.client.cover.return_value), 256).data
    )
    assert runtime.client.cover.await_count == 2


async def test_thumbnail_cache_window_cannot_outlive_signed_url(delivery, runtime):
    browser, _, _, _, _ = delivery
    runtime.client.detail.return_value = {"track": track(coverId="cover-one")}
    runtime.client.cover = AsyncMock(return_value=image_bytes())
    path = f"/api/{DOMAIN}/{runtime.entry.entry_id}/{runtime.scope}/image/track/track-one/cover-one"
    signed = async_sign_path(runtime.hass, path + "?size=128", timedelta(seconds=3))
    response = await browser.get(signed)
    assert response.status == 200
    assert response.headers["Cache-Control"].startswith("private, max-age=")
    max_age = int(response.headers["Cache-Control"].split("max-age=")[1].split(",")[0])
    assert 0 <= max_age <= 3
    expired = async_sign_path(runtime.hass, path, timedelta(seconds=-1))
    assert (await browser.get(expired)).status == 401
    changed = signed.replace("size=128", "size=512")
    assert (await browser.get(changed)).status == 401
    unsupported = async_sign_path(runtime.hass, path + "?size=4096", timedelta(minutes=1))
    assert (await browser.get(unsupported)).status == 400
    runtime.client.cover.assert_awaited_once()


async def test_short_grant_cache_window_cannot_outlive_token(delivery, runtime, monkeypatch):
    browser, _, _, _, _ = delivery
    clock = [100.0]
    monkeypatch.setattr("custom_components.feiniu_music.runtime.monotonic", lambda: clock[0])
    runtime.client.detail.return_value = {"track": track(coverId="cover-one")}
    runtime.client.cover = AsyncMock(return_value=image_bytes())
    token = runtime.grant_artwork("track", "track-one", "cover-one")
    clock[0] += ARTWORK_LIFETIME - 2
    path = f"/api/{DOMAIN}/{runtime.entry.entry_id}/artwork?token={token}"
    response = await browser.get(path)
    assert response.status == 200
    assert response.headers["Cache-Control"] == "private, max-age=2, must-revalidate"
    clock[0] += 2
    assert (await browser.get(path)).status == 404


async def test_disconnected_image_request_cancels_unneeded_download(
    runtime, client, aiohttp_server
):
    """Use HA's actual handler_cancellation=True server behavior with a real socket."""
    started, cleaned, handler_done = asyncio.Event(), asyncio.Event(), asyncio.Event()
    client.detail.return_value = {"track": track(coverId="cover")}

    async def fetch(cover):
        try:
            started.set()
            await asyncio.Event().wait()
        finally:
            cleaned.set()

    client.cover.side_effect = fetch

    async def serve(request):
        try:
            return await image_response(runtime, "track", "track-one", "cover", request)
        finally:
            handler_done.set()

    app = web.Application()
    app.router.add_get("/image", serve)
    # This aiohttp TestServer already enables handler cancellation, as HA does.
    server = await aiohttp_server(app)
    async with aiohttp.ClientSession() as session:
        request = asyncio.create_task(session.get(server.make_url("/image")))
        await started.wait()
        request.cancel()
        with pytest.raises(asyncio.CancelledError):
            await request
        await asyncio.wait_for(handler_done.wait(), timeout=2)
    assert cleaned.is_set() and not runtime._cover_tasks and not runtime._cover_waiters


def session_path(runtime, owner, events):
    from custom_components.feiniu_music.streaming import AudioRound

    route = AudioRound(owner, "track-one", 1, lambda round_id, event: events.append((owner, event)))
    token = runtime.grant_audio(route)
    path = f"/api/{DOMAIN}/{runtime.entry.entry_id}/{runtime.scope}/session/{token}/track-one"
    return route, path, async_sign_path(runtime.hass, path, timedelta(minutes=10))


async def test_output_round_head_get_range_expiry_and_revocation_are_independent(delivery, runtime):
    browser, _, _, calls, _ = delivery
    events = []
    a, raw_a, url_a = session_path(runtime, "a", events)
    b, _, url_b = session_path(runtime, "b", events)
    assert (await browser.get(raw_a)).status == 401
    head = await browser.head(url_a)
    assert head.status == 200 and await head.read() == b""
    assert events == [("a", "head")]
    partial = await browser.get(url_a, headers={"Range": "bytes=100000-106553"})
    assert partial.status == 206 and await partial.read() == AUDIO[100000:106554]
    assert ("a", "first_byte") in events and ("a", "eof") in events
    response = await browser.get(url_b, headers={"Range": "bytes=9999999-"})
    assert response.status == 416 and response.headers["Content-Range"] == f"bytes */{len(AUDIO)}"
    runtime.cancel_audio("a")
    count = len(calls)
    assert (await browser.get(url_a)).status == 404 and len(calls) == count
    response = await browser.get(url_b)
    assert response.status == 200 and await response.read() == AUDIO
    b.expires = 0
    assert (await browser.get(url_b)).status == 404
    assert a.closed and not a.tasks and not b.tasks


async def test_two_active_deliveries_cancel_only_the_stopped_output(hass, delivery, runtime):
    browser, _, _, _, behavior = delivery
    controls = {
        name: [asyncio.Event(), asyncio.Event()] for name in ("started", "release", "finished")
    }
    behavior["streaming"] = controls
    events = []
    a, _, url_a = session_path(runtime, "a", events)
    b, _, url_b = session_path(runtime, "b", events)
    first = await browser.get(url_a)
    assert await first.content.readexactly(4096) == AUDIO[:4096]
    second = await browser.get(url_b)
    assert await second.content.readexactly(4096) == AUDIO[:4096]
    assert len(a.tasks) == len(b.tasks) == 1
    closed_tasks = tuple(a.tasks)
    runtime.cancel_audio("a")
    await asyncio.gather(*closed_tasks, return_exceptions=True)
    assert not a.tasks and len(b.tasks) == 1 and not b.closed
    controls["release"][1].set()
    assert await second.read() == AUDIO[4096:]
    assert ("b", "eof") in events and ("a", "eof") not in events
    first.close()
    controls["release"][0].set()
    await asyncio.gather(*(event.wait() for event in controls["finished"]))
    assert not runtime._active and not runtime.client._session.connector._acquired


@pytest.mark.parametrize(
    "status,body,mime",
    [
        (401, b"Denied", "text/plain"),
        (403, b"Denied", "text/plain"),
        (200, b'{"code":100004}', "application/json"),
        (200, b"<html>Denied</html>", "text/html"),
    ],
)
async def test_session_audio_failure_never_reports_first_byte_or_eof(
    delivery, runtime, status, body, mime
):
    browser, _, _, _, behavior = delivery
    behavior.update(status=status, body=body, type=mime)
    events = []
    route, _, url = session_path(runtime, "a", events)
    response = await browser.get(url)
    assert response.status >= 400
    assert events == [("a", "get"), ("a", "error")]
    assert not route.tasks
    assert runtime.client.login.await_count <= 1
