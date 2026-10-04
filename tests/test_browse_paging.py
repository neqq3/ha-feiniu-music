"""Controlled browse work: no NAS, speakers or wall-clock performance assertions."""

import asyncio

import pytest

from custom_components.feiniu_music import runtime as runtime_module
from custom_components.feiniu_music.client import NetworkError, PermissionDeniedError, ProtocolError
from custom_components.feiniu_music.runtime import FeiNiuRuntime

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


async def test_last_waiter_cancel_cleans_flight_and_retry_succeeds(runtime, client):
    started, cleaned = asyncio.Event(), asyncio.Event()

    async def fetch(*args):
        try:
            started.set()
            await asyncio.Event().wait()
        finally:
            cleaned.set()

    client.page.side_effect = fetch
    request = asyncio.create_task(runtime.browse_page("track"))
    await started.wait()
    request.cancel()
    with pytest.raises(asyncio.CancelledError):
        await request
    assert cleaned.is_set() and not runtime._browse_flights and not runtime._browse_waiters
    client.page.side_effect = None
    client.page.return_value = {"list": [], "total": 0}
    assert (await runtime.browse_page("track")).total == 0


@pytest.mark.parametrize("request_count", [20, 40])
async def test_different_requests_are_bounded_and_unload_cancels_queued_work(
    runtime, client, request_count
):
    started = asyncio.Event()
    active = peak = 0

    async def fetch(*args, **kwargs):
        nonlocal active, peak
        active += 1
        peak = max(active, peak)
        if active == 4:
            started.set()
        try:
            await asyncio.Event().wait()
        finally:
            active -= 1

    client.related.side_effect = fetch
    requests = [
        asyncio.create_task(runtime.browse_page("album", guid=f"test-{i}"))
        for i in range(request_count)
    ]
    await started.wait()
    await asyncio.sleep(0)
    assert client.related.await_count == peak == 4
    assert len(runtime._browse_waiters) == min(32, request_count)
    await runtime.close()
    results = await asyncio.gather(*requests, return_exceptions=True)
    assert all(isinstance(result, asyncio.CancelledError) for result in results[:32])
    assert all(isinstance(result, NetworkError) for result in results[32:])
    assert not active and not runtime._browse_flights and not runtime._browse_waiters


async def test_timeout_includes_waiting_for_admission(runtime, client, monkeypatch):
    monkeypatch.setattr(runtime_module, "BROWSE_TIMEOUT", 0.02)
    for _ in range(4):
        await runtime._browse_slots.acquire()
    try:
        with pytest.raises(NetworkError, match="timed out"):
            await runtime.browse_page("track")
        client.page.assert_not_called()
        assert not runtime._browse_flights and not runtime._browse_waiters
        record = runtime.browse_diagnostics()["recent"][-1]
        assert record["error"] == "timeout" and record["queue_ms"] == record["total_ms"]
        assert record["upstream_ms"] == 0
    finally:
        for _ in range(4):
            runtime._browse_slots.release()
    client.page.return_value = {"list": [], "total": 0}
    assert (await runtime.browse_page("track")).total == 0


@pytest.mark.parametrize("invalidation", ["login", "denial", "fresh"])
async def test_late_result_cannot_revive_invalidated_metadata(runtime, client, invalidation):
    started, release = asyncio.Event(), asyncio.Event()

    async def fetch(*args):
        started.set()
        await release.wait()
        return {"list": [track("old-test", coverId="test")], "total": 1}

    client.page.side_effect = fetch
    old = asyncio.create_task(runtime.browse_page("track"))
    await started.wait()
    if invalidation == "login":
        await runtime.login()
    elif invalidation == "denial":
        client.detail.return_value = {"track": track("old-test", accessStatus=2)}
        with pytest.raises(PermissionDeniedError):
            await runtime.detail("track", "old-test", fresh=True)
    else:
        client.page.side_effect = None
        client.page.return_value = {"list": [track("new-test")], "total": 1}
        assert (await runtime.browse_page("track", fresh=True)).rows[0]["guid"] == "new-test"
    release.set()
    with pytest.raises(NetworkError):
        await old
    assert runtime._cover_owner("track", "old-test") is None
    assert "old-test" not in repr(runtime._browse_results)


async def test_unload_while_waiting_for_relogin(runtime, client):
    from custom_components.feiniu_music.client import AuthenticationError

    started = asyncio.Event()

    async def fetch(*args):
        started.set()
        raise AuthenticationError("test")

    client.page.side_effect = fetch
    await runtime._login_lock.acquire()
    request = asyncio.create_task(runtime.browse_page("track"))
    await started.wait()
    await asyncio.sleep(0)
    await runtime.close()
    with pytest.raises(asyncio.CancelledError):
        await request
    runtime._login_lock.release()
    client.login.assert_not_called()
    assert not runtime._browse_waiters


async def test_invalidation_between_worker_completion_and_consumer_resume(runtime, client):
    async def fetch(*args):
        # Complete the native read, then invalidate in the callback turn before
        # shield() wakes its consumer. A writer-only epoch check misses this race.
        asyncio.current_task().add_done_callback(lambda task: runtime._invalidate_metadata())
        return {"list": [track("old-test")], "total": 1}

    client.page.side_effect = fetch
    with pytest.raises(NetworkError, match="access changed"):
        await runtime.browse_page("track")
    assert not runtime._browse_results and not runtime._cover_owners
    assert not runtime._browse_flights and not runtime._browse_waiters


async def test_success_cleanup_does_not_yield_between_access_check_and_delivery(runtime, client):
    invalidated = False

    def invalidate():
        nonlocal invalidated
        runtime._invalidate_metadata()
        invalidated = True

    async def fetch(*args):
        # Schedule invalidation one callback turn later. Successful delivery must
        # finish before that turn, not yield again while cleaning an already-done job.
        asyncio.current_task().add_done_callback(
            lambda task: asyncio.get_running_loop().call_soon(invalidate)
        )
        return {"list": [track("test")], "total": 1}

    client.page.side_effect = fetch
    result = await runtime.browse_page("track")
    assert result.rows[0]["guid"] == "test" and not invalidated
    assert not runtime._browse_flights and not runtime._browse_waiters
    await asyncio.sleep(0)
    assert invalidated and not runtime._browse_results


async def test_page_cache_is_account_local_and_metadata_is_compact(runtime, client, hass):
    row = track("test", coverId="test", filePath="PRIVATE", tags=["PRIVATE"] * 100)
    row["artists"] = [{"guid": "test", "name": "test", "coverId": "test", "albums": [row.copy()]}]
    client.page.return_value = {"list": [row], "total": 1}
    first = await runtime.browse_page("track")
    other = FeiNiuRuntime(hass, runtime.entry, client)
    second = await other.browse_page("track")
    assert client.page.await_count == 2 and first == second
    assert "PRIVATE" not in repr(runtime._browse_results)
    assert first.rows[0]["artists"] == [{"guid": "test", "name": "test", "coverId": "test"}]


async def test_page_budget_is_not_library_limit(runtime, client, monkeypatch):
    monkeypatch.setattr(runtime_module, "MAX_BROWSE_ROWS", 2)
    client.page.return_value = {"list": [track(f"test-{i}") for i in range(100)], "total": 5000}
    assert len((await runtime.browse_page("track")).rows) == 100
    assert not runtime._browse_results
    assert len(runtime._cover_owners) <= 2


async def test_browse_diagnostics_and_logs_never_contain_query_ids_or_payload(
    runtime, client, caplog
):
    import logging

    caplog.set_level(logging.DEBUG, logger="custom_components.feiniu_music")
    client.search.return_value = {
        "list": [track("PRIVATE_GUID", title="PRIVATE_TITLE")],
        "total": 1,
    }
    await runtime.search("track", "PRIVATE_QUERY")
    await runtime.search("track", "PRIVATE_QUERY")
    client.playlists.return_value = []
    for _ in range(40):
        await runtime.collection("playlist", fresh=True)
    client.search.assert_awaited_once()
    value = runtime.browse_diagnostics()
    assert len(value["recent"]) == 32 and value["hit"] == 1
    assert "PRIVATE_" not in repr(value) + caplog.text
