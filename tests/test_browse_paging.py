"""Controlled browse work: no NAS, speakers or wall-clock performance assertions."""

import asyncio

import pytest

from custom_components.feiniu_music import runtime as runtime_module
from custom_components.feiniu_music.client import NetworkError, ProtocolError

from .conftest import track


async def test_slow_sidebar_does_not_block_another_collection(runtime, client):
    started, release = asyncio.Event(), asyncio.Event()

    async def playlists():
        started.set()
        await release.wait()
        return []

    client.playlists.side_effect = playlists
    client.page.return_value = {"list": [{"guid": "test", "name": "test"}], "total": 1}
    sidebar = asyncio.create_task(runtime.collection("playlist"))
    await started.wait()
    main = asyncio.create_task(runtime.collection("album"))
    try:
        async with asyncio.timeout(1):
            assert (await main)[0]["guid"] == "test"
    finally:
        release.set()
        await asyncio.gather(sidebar, main, return_exceptions=True)


async def test_slow_result_has_display_ttl_from_completion_not_permission_renewal(
    runtime, client, monkeypatch
):
    clock = [100.0]
    monkeypatch.setattr(runtime_module, "monotonic", lambda: clock[0])

    async def page(kind, number):
        clock[0] += 31
        return {"list": [track("test", coverId="test")], "total": 1}

    client.page.side_effect = page
    assert await runtime.collection("track") == await runtime.collection("track")
    assert client.page.await_count == 1
    assert runtime._cover_owner("track", "test") is None


@pytest.mark.parametrize("total", [100, 1000, 5000])
async def test_first_page_reads_only_one_native_page(runtime, client, total):
    client.page.return_value = {"list": [track(f"test-{i}") for i in range(100)], "total": total}
    result = await runtime.browse_page("track")
    assert len(result.rows) == 100 and result.total == total and result.offset == 0
    client.page.assert_awaited_once_with("track", 1, 100)
    result.rows[0]["title"] = "changed"
    assert (await runtime.browse_page("track")).rows[0]["title"] != "changed"
    assert client.page.await_count == 1


async def test_twenty_waiters_share_work_and_one_cancel_keeps_others(runtime, client):
    started, release = asyncio.Event(), asyncio.Event()

    async def page(*args):
        started.set()
        await release.wait()
        return {"list": [track("test")], "total": 1}

    client.page.side_effect = page
    requests = [asyncio.create_task(runtime.browse_page("track")) for _ in range(20)]
    await started.wait()
    await asyncio.sleep(0)
    requests[0].cancel()
    with pytest.raises(asyncio.CancelledError):
        await requests[0]
    release.set()
    results = await asyncio.gather(*requests[1:])
    assert client.page.await_count == 1
    assert len({id(value.rows) for value in results}) == 19
    assert not runtime._browse_flights and not runtime._browse_waiters


async def test_page_failure_is_not_cached_as_empty_success(runtime, client):
    client.page.side_effect = NetworkError("test")
    with pytest.raises(NetworkError):
        await runtime.browse_page("album")
    assert not runtime._browse_results and not runtime._browse_flights
    client.page.side_effect = None
    client.page.return_value = {"list": [], "total": 0}
    assert (await runtime.browse_page("album")).rows == []


@pytest.mark.parametrize("status", [None, True, False, "0", 3, 99])
async def test_unknown_playlist_status_fails_visibly(runtime, client, status):
    client.related.return_value = {"list": [track("test", accessStatus=status)], "total": 1}
    with pytest.raises(ProtocolError):
        await runtime.related("playlist", "test")
    assert not runtime._browse_results
