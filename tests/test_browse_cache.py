"""Bounded browse/artwork reuse without skipping owner checks or pagination."""

import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from homeassistant.setup import async_setup_component

from custom_components.feiniu_music import runtime as runtime_module
from custom_components.feiniu_music.client import NetworkError, PermissionDeniedError
from custom_components.feiniu_music.media import thumbnail
from custom_components.feiniu_music.runtime import FeiNiuRuntime

from .conftest import track


@pytest.fixture
def clock(monkeypatch):
    value = [100.0]
    monkeypatch.setattr(runtime_module, "monotonic", lambda: value[0])
    return value


async def test_cover_reuses_bytes_but_checks_each_owner(runtime, client, clock):
    client.detail.side_effect = lambda kind, guid: {"track": track(guid, coverId="shared")}
    client.cover.return_value = b"image"
    assert await runtime.cover("track", "first", "shared") == b"image"
    assert await runtime.cover("track", "second", "shared") == b"image"
    client.cover.assert_awaited_once_with("shared")
    assert client.detail.await_count == 2
    with pytest.raises(PermissionDeniedError):
        await runtime.cover("track", "second", "forged")
    clock[0] += 31
    client.detail.side_effect = lambda kind, guid: {"track": track(guid, accessStatus=2)}
    with pytest.raises(PermissionDeniedError):
        await runtime.cover("track", "first", "shared")
    assert client.cover.await_count == 1


async def test_cover_expiry_failure_retries_and_instance_isolation(runtime, client, clock, hass):
    client.detail.return_value = {"track": track(coverId="cover")}
    client.cover.side_effect = [b"old", NetworkError("offline"), b"new", b"other"]
    assert await runtime.cover("track", "track-one", "cover") == b"old"
    clock[0] += runtime_module.COVER_TTL
    with pytest.raises(NetworkError):
        await runtime.cover("track", "track-one", "cover")
    assert not runtime._cover_tasks
    assert await runtime.cover("track", "track-one", "cover") == b"new"
    other = FeiNiuRuntime(hass, runtime.entry, client)
    assert await other.cover("track", "track-one", "cover") == b"other"
    assert client.cover.await_count == 4


async def test_cover_cache_is_byte_and_count_bounded(runtime, client, monkeypatch):
    monkeypatch.setattr(runtime_module, "MAX_COVER_BYTES", 6)
    monkeypatch.setattr(runtime_module, "MAX_COVERS", 2)
    client.detail.side_effect = lambda kind, guid: {"track": track(guid, coverId=guid)}
    client.cover.side_effect = [b"1111", b"2222", b"3", b"4", b"oversize"]
    for guid in ("one", "two", "three", "four", "five"):
        await runtime.cover("track", guid, guid)
        assert len(runtime._covers) <= 2
        assert sum(len(value[1]) for value in runtime._covers.values()) <= 6
    assert set(runtime._covers) == {"three", "four"}


async def test_cover_download_is_shared_and_one_cancel_does_not_cancel_other(runtime, client):
    started, joined, finish = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def detail(kind, guid):
        if guid == "second":
            joined.set()
        return {"track": track(guid, coverId="cover")}

    client.detail.side_effect = detail

    async def fetch(cover):
        started.set()
        await finish.wait()
        return b"image"

    client.cover.side_effect = fetch
    first = asyncio.create_task(runtime.cover("track", "track-one", "cover"))
    await started.wait()
    second = asyncio.create_task(runtime.cover("track", "second", "cover"))
    await joined.wait()
    assert list(runtime._cover_waiters.values()) == [2]
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    # The remaining consumer keeps the shared download alive.
    finish.set()
    assert await second == b"image"
    client.cover.assert_awaited_once()
    assert not runtime._cover_tasks


async def test_unload_cancels_shared_cover_and_clears_caches(runtime, client):
    client.detail.return_value = {"track": track(coverId="cover")}
    started, cleaned = asyncio.Event(), asyncio.Event()

    async def fetch(cover):
        try:
            started.set()
            await asyncio.Event().wait()
        finally:
            cleaned.set()

    client.cover.side_effect = fetch
    request = asyncio.create_task(runtime.cover("track", "track-one", "cover"))
    await started.wait()
    await runtime.close()
    with pytest.raises(asyncio.CancelledError):
        await request
    assert cleaned.is_set() and not runtime._cover_tasks
    assert not runtime._covers and not runtime._browse_results and not runtime._thumbnail_paths


async def test_playlist_reuses_complete_filtered_pages_and_preserves_duplicates(
    runtime, client, clock
):
    denied = [track(f"denied-{i}", accessStatus=2) for i in range(100)]
    visible = [track("same"), track("same"), track("last")]
    client.related.side_effect = [
        {"list": denied, "total": 103},
        {"list": visible, "total": 103},
    ]
    first = await runtime.related("playlist", "list")
    assert first == visible
    first[0]["title"] = "mutated"
    assert await runtime.related("playlist", "list") == [
        track("same"),
        track("same"),
        track("last"),
    ]
    assert [call.args[2] for call in client.related.await_args_list] == [1, 2]
    client.page.assert_not_called()
    client.detail.assert_not_called()
    clock[0] += runtime_module.BROWSE_TTL
    client.related.side_effect = None
    client.related.return_value = {"list": [track("new")], "total": 1}
    assert await runtime.related("playlist", "list") == [track("new")]
    assert client.related.await_count == 3


async def test_playlist_failed_refresh_never_serves_stale_or_partial_result(runtime, client, clock):
    client.related.return_value = {"list": [track()], "total": 1}
    await runtime.related("playlist", "list")
    clock[0] += runtime_module.BROWSE_TTL
    client.related.side_effect = [
        {"list": [track("partial")], "total": 2},
        NetworkError("offline"),
    ]
    with pytest.raises(NetworkError):
        await runtime.related("playlist", "list")
    assert not runtime._browse_results
    client.related.side_effect = None
    client.related.return_value = {"list": [], "total": 0}
    assert await runtime.related("playlist", "list") == []
    assert await runtime.related("playlist", "list") == []
    assert client.related.await_count == 4


async def test_playlist_cache_is_instance_local_and_bounded(runtime, client, hass, monkeypatch):
    monkeypatch.setattr(runtime_module, "MAX_BROWSE_RESULTS", 2)
    monkeypatch.setattr(runtime_module, "MAX_BROWSE_ROWS", 3)
    client.related.return_value = {"list": [track("a"), track("b")], "total": 2}
    await runtime.related("playlist", "one")
    await runtime.related("playlist", "two")
    assert {key[2] for key in runtime._browse_results} == {"two"}
    other = FeiNiuRuntime(hass, runtime.entry, client)
    await other.related("playlist", "two")
    assert client.related.await_count == 3
    client.related.return_value = {"list": [], "total": 0}
    await runtime.related("playlist", "three")
    await runtime.related("playlist", "four")
    assert {key[2] for key in runtime._browse_results} == {"three", "four"}
    client.related.return_value = {"list": [track(str(i)) for i in range(4)], "total": 4}
    assert len(await runtime.related("playlist", "oversized")) == 4
    assert "oversized" not in {key[2] for key in runtime._browse_results}


async def test_relogin_discards_all_cached_results(runtime, client, hass):
    assert await async_setup_component(hass, "http", {})
    client.detail.return_value = {"track": track(coverId="cover")}
    client.cover.return_value = b"image"
    client.related.return_value = {"list": [track()], "total": 1}
    await runtime.cover("track", "track-one", "cover")
    await runtime.related("playlist", "list")
    thumbnail(runtime, "track", track(coverId="cover"))
    assert runtime._covers and runtime._browse_results and runtime._thumbnail_paths
    await runtime.login()
    assert not runtime._covers and not runtime._browse_results and not runtime._thumbnail_paths
    assert not runtime._details


async def test_thumbnail_reuses_exact_url_and_rotates_before_expiry(
    hass, runtime, clock, monkeypatch
):
    assert await async_setup_component(hass, "http", {})
    sign = Mock(wraps=runtime_module.async_sign_path)
    monkeypatch.setattr(runtime_module, "async_sign_path", sign)
    monkeypatch.setattr(runtime_module, "MAX_THUMBNAIL_PATHS", 2)
    first = thumbnail(runtime, "track", track(coverId="cover"))
    clock[0] += 2
    assert thumbnail(runtime, "track", track(coverId="cover")) == first
    sign.assert_called_once()
    other = FeiNiuRuntime(hass, runtime.entry, runtime.client)
    assert thumbnail(other, "track", track(coverId="cover")) != first
    assert thumbnail(runtime, "track", track("other", coverId="cover")) != first
    thumbnail(runtime, "track", track("third", coverId="cover"))
    assert len(runtime._thumbnail_paths) == 2
    sign.reset_mock()
    clock[0] += runtime_module.THUMBNAIL_LIFETIME - 60
    thumbnail(runtime, "track", track("third", coverId="cover"))
    sign.assert_called_once()
    assert len(runtime._thumbnail_paths) == 1


async def test_thumbnail_links_do_not_cross_ha_browser_sessions(hass, runtime):
    assert await async_setup_component(hass, "http", {})
    urls = []
    for issuer in ("session-one", "session-two", "session-one"):
        context = runtime_module.websocket_api.current_connection.set(
            SimpleNamespace(refresh_token_id=issuer)
        )
        try:
            urls.append(thumbnail(runtime, "track", track(coverId="cover")))
        finally:
            runtime_module.websocket_api.current_connection.reset(context)
    assert urls[0] == urls[2] and urls[0] != urls[1]
    request_context = runtime_module.current_request.set(
        {runtime_module.KEY_HASS_REFRESH_TOKEN_ID: "session-one"}
    )
    try:
        assert thumbnail(runtime, "track", track(coverId="cover")) == urls[0]
    finally:
        runtime_module.current_request.reset(request_context)
