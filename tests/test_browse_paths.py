"""Every browser entry point, whole-grid reuse and navigation cancellation."""

import asyncio

import pytest

from custom_components.feiniu_music import runtime as runtime_module
from custom_components.feiniu_music.client import NetworkError, PermissionDeniedError, ProtocolError

from .conftest import track


@pytest.fixture
def clock(monkeypatch):
    value = [100.0]
    monkeypatch.setattr(runtime_module, "monotonic", lambda: value[0])
    return value


@pytest.mark.parametrize("kind", ["track", "album", "artist", "playlist"])
async def test_root_collections_reuse_complete_rows_for_covers(runtime, client, kind, clock):
    # Account-filtered native collection rows need not have metadata's accessStatus.
    row = {"guid": "item", "name": "Item", "title": "Item", "coverId": "cover"}
    client.page.return_value = {"list": [row], "total": 1}
    client.playlists.return_value = [row]
    client.cover.return_value = b"image"
    rows = await runtime.collection(kind)
    rows[0]["coverId"] = "client-forged"
    assert (await runtime.collection(kind))[0]["coverId"] == "cover"
    assert await runtime.cover(kind, "item", "cover") == b"image"
    assert client.page.await_count + client.playlists.await_count == 1
    client.detail.assert_not_called()
    # The returned copy cannot grant another image by altering the saved association.
    original = {**row, "coverId": "cover"}
    client.detail.return_value = {"track": original} if kind == "track" else original
    if kind == "track":
        client.detail.return_value["track"] = {**original, "accessStatus": 0}
    with pytest.raises(PermissionDeniedError):
        await runtime.cover(kind, "item", "client-forged")
    client.cover.assert_awaited_once()


@pytest.mark.parametrize(
    "kind,albums,row_kind",
    [
        ("album", False, "track"),
        ("artist", False, "track"),
        ("artist", True, "album"),
        ("playlist", False, "track"),
    ],
)
async def test_related_browsing_reuses_rows_without_per_item_detail(
    runtime, client, kind, albums, row_kind
):
    row = {"guid": "item", "title": "Item", "name": "Item", "coverId": "cover"}
    if kind == "playlist":
        row["accessStatus"] = 0
    client.related.return_value = {"list": [row], "total": 1}
    client.cover.return_value = b"image"
    assert await runtime.related(kind, "parent", albums=albums) == [row]
    assert await runtime.related(kind, "parent", albums=albums) == [row]
    assert await runtime.cover(row_kind, "item", "cover") == b"image"
    client.related.assert_awaited_once()
    client.detail.assert_not_called()
    client.page.assert_not_called()


@pytest.mark.parametrize("kind", ["track", "album", "artist", "playlist"])
async def test_search_reuses_results_but_keeps_queries_separate(runtime, client, kind):
    row = {"guid": "item", "name": "Item", "coverId": "cover"}
    client.search.return_value = {"list": [row], "total": 1}
    client.cover.return_value = b"image"
    assert await runtime.search(kind, "first") == [row]
    assert await runtime.search(kind, "first") == [row]
    assert await runtime.cover(kind, "item", "cover") == b"image"
    client.detail.assert_not_called()
    await runtime.search(kind, "second")
    assert client.search.await_count == 2


async def test_whole_164_track_grid_retains_all_owners_and_realistic_sized_covers(
    runtime, client, clock
):
    rows = [track(str(i), coverId=f"cover-{i}") for i in range(164)]
    client.page.side_effect = [
        {"list": rows[:100], "total": 164},
        {"list": rows[100:], "total": 164},
    ]
    # Roughly 20 MiB for this grid, matching the observed order of magnitude.
    # Tiny mock images would hide repeated eviction under the former 16 MiB cap.
    client.cover.return_value = b"x" * (128 * 1024)
    assert await runtime.collection("track") == rows
    for _ in range(2):
        assert await runtime.collection("track") == rows
        for row in rows:
            await runtime.cover("track", row["guid"], row["coverId"])
    assert client.page.await_count == 2
    assert client.cover.await_count == 164
    client.detail.assert_not_called()
    assert not runtime._details  # Browse rows never masquerade as complete track metadata.


async def test_repeated_browse_does_not_extend_owner_access_window(runtime, client, clock):
    client.page.return_value = {"list": [track(coverId="cover")], "total": 1}
    client.cover.return_value = b"image"
    await runtime.collection("track")
    await runtime.cover("track", "track-one", "cover")
    clock[0] += 20
    await runtime.collection("track")
    clock[0] += 11
    client.detail.return_value = {"track": track(accessStatus=2, coverId="cover")}
    with pytest.raises(PermissionDeniedError):
        await runtime.cover("track", "track-one", "cover")
    client.detail.assert_awaited_once()
    client.cover.assert_awaited_once()


async def test_refreshed_root_supplies_new_owner_check_without_detail(runtime, client, clock):
    row = track(coverId="cover")
    client.page.return_value = {"list": [row], "total": 1}
    client.cover.return_value = b"image"
    await runtime.collection("track")
    await runtime.cover("track", "track-one", "cover")
    clock[0] += 31
    await runtime.collection("track")
    await runtime.cover("track", "track-one", "cover")
    assert client.page.await_count == 2
    client.detail.assert_not_called()
    client.cover.assert_awaited_once()


async def test_root_refresh_failure_discards_partial_result(runtime, client, clock):
    client.page.return_value = {"list": [track(coverId="cover")], "total": 1}
    await runtime.collection("track")
    clock[0] += 31
    client.page.side_effect = [{"list": [track("partial")], "total": 2}, NetworkError("offline")]
    with pytest.raises(NetworkError):
        await runtime.collection("track")
    assert not runtime._browse_results
    client.detail.side_effect = NetworkError("offline")
    with pytest.raises(NetworkError):
        await runtime.cover("track", "track-one", "cover")
    client.cover.assert_not_called()


@pytest.mark.parametrize("status,error", [(2, PermissionDeniedError), (True, ProtocolError)])
async def test_fresh_playback_refusal_invalidates_older_browse_authority(
    runtime, client, status, error
):
    client.page.return_value = {"list": [track(coverId="cover")], "total": 1}
    await runtime.collection("track")
    client.detail.return_value = {"track": track(accessStatus=status, coverId="cover")}
    with pytest.raises(error):
        await runtime.detail("track", "track-one", fresh=True)
    with pytest.raises(error):
        await runtime.cover("track", "track-one", "cover")
    assert not runtime._browse_results and not runtime._details
    client.cover.assert_not_called()


async def test_more_recent_detail_supersedes_browse_cover_association(runtime, client, clock):
    client.page.return_value = {"list": [track(coverId="old")], "total": 1}
    await runtime.collection("track")
    clock[0] += 1
    client.detail.return_value = {"track": track(coverId="new")}
    client.cover.return_value = b"image"
    await runtime.detail("track", "track-one", fresh=True)
    with pytest.raises(PermissionDeniedError):
        await runtime.cover("track", "track-one", "old")
    assert await runtime.cover("track", "track-one", "new") == b"image"
    client.cover.assert_awaited_once_with("new")


async def test_browse_row_cannot_authorize_a_different_owner(runtime, client):
    client.page.return_value = {"list": [track("visible", coverId="cover")], "total": 1}
    await runtime.collection("track")
    client.detail.return_value = {"track": track("denied", accessStatus=2, coverId="cover")}
    with pytest.raises(PermissionDeniedError):
        await runtime.cover("track", "denied", "cover")
    client.cover.assert_not_called()


async def test_slow_pagination_does_not_extend_first_page_authority(runtime, client, clock):
    async def page(kind, number):
        clock[0] += 31
        return {"list": [track(coverId="cover")], "total": 1}

    client.page.side_effect = page
    await runtime.collection("track")
    client.detail.return_value = {"track": track(accessStatus=2)}
    with pytest.raises(PermissionDeniedError):
        await runtime.cover("track", "track-one", "cover")
    client.detail.assert_awaited_once()


async def test_last_cancelled_consumer_releases_download_immediately(runtime, client):
    started, cleaned = asyncio.Event(), asyncio.Event()
    client.detail.return_value = {"track": track(coverId="cover")}

    async def fetch(cover):
        try:
            started.set()
            await asyncio.Event().wait()
        finally:
            cleaned.set()

    client.cover.side_effect = fetch
    request = asyncio.create_task(runtime.cover("track", "track-one", "cover"))
    await started.wait()
    request.cancel()
    with pytest.raises(asyncio.CancelledError):
        await request
    assert cleaned.is_set() and not runtime._cover_tasks and not runtime._cover_waiters


async def test_image_concurrency_keeps_navigation_out_of_thumbnail_backlog(runtime, client):
    rows = [track(str(i), coverId=str(i)) for i in range(3)]
    client.page.return_value = {"list": rows, "total": 3}
    await runtime.collection("track")
    started = asyncio.Event()
    active = 0

    async def fetch(cover):
        nonlocal active
        active += 1
        if active == 2:
            started.set()
        try:
            await asyncio.Event().wait()
        finally:
            active -= 1

    client.cover.side_effect = fetch
    requests = [asyncio.create_task(runtime.cover("track", str(i), str(i))) for i in range(3)]
    await started.wait()
    assert client.cover.await_count == 2
    # Navigation proceeds while both image slots are occupied; third image stays out
    # of the native client's shared request queue altogether.
    client.playlists.return_value = []
    assert await runtime.collection("playlist") == []
    client.playlists.assert_awaited_once()
    for request in requests:
        request.cancel()
    await asyncio.gather(*requests, return_exceptions=True)
    assert not active and not runtime._cover_tasks and not runtime._cover_waiters
