"""Real pixel/disk tests; cached bytes never replace current owner authorization."""

import asyncio
from io import BytesIO
from unittest.mock import AsyncMock

import pytest
from PIL import Image
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.feiniu_music import artwork as module
from custom_components.feiniu_music.artwork import ArtworkCache, CachedImage, resize_image
from custom_components.feiniu_music.client import NetworkError, PermissionDeniedError, ProtocolError
from custom_components.feiniu_music.runtime import FeiNiuRuntime

from .conftest import image_bytes, track


@pytest.mark.parametrize("size", [128, 256, 512])
async def test_resized_pixels_persist_and_expire_without_extending_source(hass, size, monkeypatch):
    clock = [10000.0]
    monkeypatch.setattr(module, "time", lambda: clock[0])
    cache = ArtworkCache(hass, "synthetic-identity")
    source = CachedImage.build(image_bytes())
    thumb = await cache.executor(resize_image, source, size)
    with Image.open(BytesIO(thumb.data)) as im:
        assert im.size == (size, size * 3 // 4)
    key = cache.key("opaque", size)
    await cache.put(key, thumb)
    other = ArtworkCache(hass, "synthetic-identity")
    assert await other.get(key) == thumb
    clock[0] += module.RESOURCE_TTL
    assert await other.get(key) is None
    assert await cache.get(key) is None


async def test_disk_and_memory_bounds_and_corrupt_recovery(hass, monkeypatch):
    monkeypatch.setattr(module, "MAX_DISK_FILES", 2)
    monkeypatch.setattr(module, "MAX_MEMORY_FILES", 1)
    cache = ArtworkCache(hass, "synthetic")
    images = [CachedImage.build(image_bytes(c)) for c in ("red", "green", "blue")]
    monkeypatch.setattr(
        module, "MAX_DISK_BYTES", sum(len(v.data) + module._HEADER.size for v in images[1:])
    )
    for i, value in enumerate(images):
        await cache.put(cache.key(str(i)), value)
    assert len(cache._memory) == 1
    assert len(list(cache.path.glob("*.cache"))) == 2
    assert cache._disk_bytes <= module.MAX_DISK_BYTES
    cache.clear_memory()
    assert await cache.get(cache.key("0")) is None
    target = cache.path / (cache.key("1") + ".cache")
    await hass.async_add_executor_job(target.write_bytes, b"corrupt")
    assert await cache.get(cache.key("1")) is None
    await cache.put(cache.key("1"), images[1])
    assert await cache.get(cache.key("1")) == images[1]
    assert not list(cache.path.glob("*.tmp"))


async def test_reload_reuses_disk_but_refusal_precedes_disk_lookup(
    hass, runtime, client, monkeypatch
):
    client.detail.return_value = {"track": track(coverId="cover")}
    client.cover.return_value = image_bytes()
    first = await runtime.thumbnail("track", "track-one", "cover", 256)
    await runtime.close()
    replacement = FeiNiuRuntime(hass, runtime.entry, client)
    assert await replacement.thumbnail("track", "track-one", "cover", 256) == first
    assert client.cover.await_count == 1
    # New access evidence is needed after 30 seconds, even for a persisted file.
    monkeypatch.setattr("custom_components.feiniu_music.runtime.monotonic", lambda: 10**12)
    client.detail.return_value = {"track": track(coverId="cover", accessStatus=2)}
    lookup = AsyncMock(wraps=replacement.artwork_cache.get)
    replacement.artwork_cache.get = lookup
    with pytest.raises(PermissionDeniedError):
        await replacement.thumbnail("track", "track-one", "cover", 256)
    lookup.assert_not_called()
    await replacement.close()


async def test_account_and_entry_disk_namespaces_are_separate(hass, runtime, client):
    client.detail.return_value = {"track": track(coverId="cover")}
    client.cover.return_value = image_bytes()
    await runtime.thumbnail("track", "track-one", "cover", 256)
    entry = MockConfigEntry(
        domain="feiniu_music", data={**runtime.entry.data, "account_id": "another-account"}
    )
    other = FeiNiuRuntime(hass, entry, client)
    assert other.artwork_cache.path != runtime.artwork_cache.path
    await other.thumbnail("track", "track-one", "cover", 256)
    assert client.cover.await_count == 2
    # Even reusing an entry ID cannot reuse bytes after changing the account identity.
    changed = MockConfigEntry(
        domain="feiniu_music", entry_id=runtime.entry.entry_id, data=entry.data
    )
    assert FeiNiuRuntime(hass, changed, client).artwork_cache.path != runtime.artwork_cache.path
    assert "synthetic-user" not in str(runtime.artwork_cache.path)
    assert "SYNTHETIC_PASSWORD" not in str(runtime.artwork_cache.path)
    await other.close()


async def test_negative_cache_is_short_and_does_not_cache_auth_or_permissions(
    runtime, client, monkeypatch
):
    clock = [100.0]
    monkeypatch.setattr("custom_components.feiniu_music.runtime.monotonic", lambda: clock[0])
    client.detail.return_value = {"track": track(coverId="cover")}
    client.cover.side_effect = [NetworkError("offline"), image_bytes()]
    for _ in range(2):
        with pytest.raises(NetworkError):
            await runtime.thumbnail("track", "track-one", "cover", 256)
    assert client.cover.await_count == 1
    clock[0] += 30
    assert (
        await runtime.thumbnail("track", "track-one", "cover", 256)
    ).content_type == "image/webp"
    assert client.cover.await_count == 2
    client.detail.return_value = {"track": track(coverId="cover", accessStatus=2)}
    clock[0] += 31
    with pytest.raises(PermissionDeniedError):
        await runtime.thumbnail("track", "track-one", "cover", 256)
    assert not runtime._image_failures


async def test_thumbnail_dedupe_and_unload_cleanup(runtime, client):
    client.detail.return_value = {"track": track(coverId="cover")}
    started, release = asyncio.Event(), asyncio.Event()

    async def fetch(_):
        started.set()
        await release.wait()
        return image_bytes()

    client.cover.side_effect = fetch
    first = asyncio.create_task(runtime.thumbnail("track", "track-one", "cover", 256))
    await started.wait()
    second = asyncio.create_task(runtime.thumbnail("track", "track-one", "cover", 256))
    await asyncio.sleep(0)
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    release.set()
    await second
    client.cover.assert_awaited_once()
    assert not runtime._thumbnail_tasks and not runtime._thumbnail_waiters
    await runtime.close()
    assert not runtime.artwork_cache._memory


async def test_invalid_image_negative_cache_and_no_fake_thumbnail(runtime, client):
    client.detail.return_value = {"track": track(coverId="cover")}
    client.cover.return_value = b"\x89PNG\r\n\x1a\ninvalid pixels"
    for _ in range(2):
        with pytest.raises(ProtocolError):
            await runtime.thumbnail("track", "track-one", "cover", 256)
    client.cover.assert_awaited_once()
    assert not runtime._covers
    assert not list(runtime.artwork_cache.path.glob("*.cache"))


async def test_unload_waits_for_thumbnail_download_cleanup(runtime, client):
    started, cleaned = asyncio.Event(), asyncio.Event()
    client.detail.return_value = {"track": track(coverId="cover")}

    async def fetch(_):
        try:
            started.set()
            await asyncio.Event().wait()
        finally:
            cleaned.set()

    client.cover.side_effect = fetch
    request = asyncio.create_task(runtime.thumbnail("track", "track-one", "cover", 256))
    await started.wait()
    await runtime.close()
    with pytest.raises(asyncio.CancelledError):
        await request
    assert cleaned.is_set()
    assert not runtime._thumbnail_tasks and not runtime._thumbnail_waiters
    assert not runtime._cover_tasks and not runtime._cover_waiters


async def test_disk_error_falls_back_to_bounded_memory(hass, monkeypatch):
    cache = ArtworkCache(hass, "synthetic")

    def denied():
        raise PermissionError("synthetic")

    monkeypatch.setattr(cache, "_initialize", denied)
    key = cache.key("cover")
    assert await cache.get(key) is None
    image = CachedImage.build(image_bytes())
    await cache.put(key, image)
    assert await cache.get(key) == image


async def test_account_removal_only_deletes_own_cache(hass, runtime):
    from custom_components.feiniu_music import async_remove_entry

    first = runtime.artwork_cache
    other = ArtworkCache(hass, "other")
    for cache in (first, other):
        await cache.put(cache.key("cover"), CachedImage.build(image_bytes()))
    await async_remove_entry(hass, runtime.entry)
    assert not first.path.exists()
    assert len(list(other.path.glob("*.cache"))) == 1


async def test_memory_byte_limit_evicts_without_losing_persisted_resource(hass, monkeypatch):
    cache = ArtworkCache(hass, "synthetic")
    first = CachedImage.build(image_bytes("red"))
    second = CachedImage.build(image_bytes("blue"))
    monkeypatch.setattr(module, "MAX_MEMORY_BYTES", max(len(first.data), len(second.data)))
    await cache.put(cache.key("one"), first)
    await cache.put(cache.key("two"), second)
    assert cache._bytes <= module.MAX_MEMORY_BYTES and len(cache._memory) == 1
    assert await cache.get(cache.key("one")) == first


async def test_owner_index_is_bounded_and_does_not_scan_browse_rows(runtime, client, monkeypatch):
    monkeypatch.setattr("custom_components.feiniu_music.runtime.MAX_BROWSE_ROWS", 3)
    for i in range(5):
        runtime._remember_owner("track", track(str(i), coverId=str(i)), 100)
    assert len(runtime._cover_owners) == 3
    monkeypatch.setattr("custom_components.feiniu_music.runtime.monotonic", lambda: 101)

    class NoRead(dict):
        def values(self):
            raise AssertionError("Artwork must not scan cached lists")

    runtime._browse_results = NoRead()
    client.cover.return_value = image_bytes()
    await runtime.thumbnail("track", "4", "4", 128)
    client.detail.assert_not_called()


async def test_browser_window_tracks_original_evidence_not_image_hits(runtime, client, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr("custom_components.feiniu_music.runtime.monotonic", lambda: clock[0])
    client.page.return_value = {"list": [track(coverId="cover")], "total": 1}
    client.cover.return_value = image_bytes()
    await runtime.collection("track")
    clock[0] += 20
    await runtime.thumbnail("track", "track-one", "cover", 256)
    assert runtime.image_max_age("track", "track-one") == 10
    clock[0] += 5
    await runtime.thumbnail("track", "track-one", "cover", 256)
    assert runtime.image_max_age("track", "track-one") == 5
    client.detail.assert_not_called()


async def test_new_variant_does_not_reset_age_of_old_source_bytes(runtime, client, monkeypatch):
    clock = [10000.0]
    monkeypatch.setattr(module, "time", lambda: clock[0])
    monkeypatch.setattr("custom_components.feiniu_music.runtime.monotonic", lambda: clock[0])
    client.detail.return_value = {"track": track(coverId="cover")}
    client.cover.return_value = image_bytes()
    await runtime.cover("track", "track-one", "cover")
    clock[0] += 1800
    image = await runtime.thumbnail("track", "track-one", "cover", 128)
    assert image.created == 10000
    client.cover.assert_awaited_once()
