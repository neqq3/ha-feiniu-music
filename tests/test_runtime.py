"""Access checks, complete pagination and instance isolation without a NAS."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from custom_components.feiniu_music.client import (
    AuthenticationError,
    NetworkError,
    NotFoundError,
    PermissionDeniedError,
    ProtocolError,
    StreamRejectedError,
)
from custom_components.feiniu_music.runtime import (
    ARTWORK_LIFETIME,
    MAX_ARTWORK_GRANTS,
    FeiNiuRuntime,
    require_track,
)

from .conftest import track


@pytest.mark.parametrize(
    "status,error",
    [
        (2, PermissionDeniedError),
        (3, NotFoundError),
        (None, ProtocolError),
        (True, ProtocolError),
        ("0", ProtocolError),
        (4, ProtocolError),
    ],
)
async def test_denied_detail_never_cached(runtime, client, status, error):
    client.detail.return_value = {"track": track(accessStatus=status)}
    with pytest.raises(error):
        await runtime.detail("track", "track-one")
    assert not runtime._details
    client.page.assert_not_called()
    client.playlists.assert_not_called()


def test_allowed_track():
    require_track(track())


async def test_detail_cache_isolated_and_expires(runtime, client, hass, entry):
    client.detail.return_value = {"track": track()}
    with patch("custom_components.feiniu_music.runtime.monotonic", return_value=10):
        first = await runtime.detail("track", "track-one")
        first["title"] = "modified"
        assert (await runtime.detail("track", "track-one"))["title"] == "Synthetic track"
    other = FeiNiuRuntime(hass, entry, client)
    assert not other._details and other.scope != runtime.scope
    with patch("custom_components.feiniu_music.runtime.monotonic", return_value=41):
        await runtime.detail("track", "track-one")
    assert client.detail.await_count == 2


@pytest.mark.parametrize("kind,albums", [("album", False), ("artist", False), ("artist", True)])
async def test_native_relations_missing_status_paginate_without_full_scan(
    runtime, client, kind, albums
):
    rows = [{"guid": f"item-{i}", "title": str(i), "name": str(i)} for i in range(102)]
    client.related.side_effect = [
        {"list": rows[:100], "total": 102},
        {"list": rows[100:], "total": 102},
    ]
    assert await runtime.related(kind, "parent", albums=albums) == rows
    assert [call.args[2] for call in client.related.await_args_list] == [1, 2]
    client.detail.assert_not_called()
    client.page.assert_not_called()
    client.playlists.assert_not_called()


async def test_playlist_filters_raw_pages_and_retains_duplicate_positions(runtime, client):
    denied = [track(f"denied-{i}", accessStatus=2) for i in range(100)]
    visible = track("same")
    client.related.side_effect = [
        {"list": denied, "total": 104},
        {
            "list": [
                visible,
                track("bad", accessStatus=True),
                visible,
                track("missing", accessStatus=None),
            ],
            "total": 104,
        },
    ]
    # Unknown status must be reported, not silently treated as an inaccessible row.
    with pytest.raises(ProtocolError):
        await runtime.related("playlist", "parent")
    assert client.related.await_count == 2
    assert not runtime._browse_results
    # Retain the original duplicate/order and filtered-empty-page assertions
    # after retrying with the endpoint's only verified denied status.
    client.related.side_effect = [
        {"list": denied, "total": 102},
        {"list": [visible, visible], "total": 102},
    ]
    assert await runtime.related("playlist", "parent") == [visible, visible]
    assert client.related.await_count == 4
    client.detail.assert_not_called()
    client.page.assert_not_called()


async def test_full_enumeration_failure_cannot_return_partial_result(runtime, client):
    client.page.side_effect = [{"list": [track()], "total": 2}, NetworkError("offline")]
    with pytest.raises(NetworkError):
        await runtime.collection("track")
    assert client.page.await_count == 2


@pytest.mark.parametrize(
    "final", [{"list": [], "total": 2}, {"list": [track()], "total": 2}, {"list": [], "total": 1}]
)
async def test_broken_pagination_is_not_empty_success(runtime, client, final):
    client.page.side_effect = [{"list": [track()], "total": 2}, final]
    with pytest.raises(ProtocolError):
        await runtime.collection("track")


async def test_cover_requires_exact_owner_and_only_one_detail(runtime, client):
    client.detail.return_value = {"track": track(coverId="own", album={"coverId": "album"})}
    client.cover.return_value = b"synthetic-image"
    assert await runtime.cover("track", "track-one", "album") == b"synthetic-image"
    with pytest.raises(PermissionDeniedError):
        await runtime.cover("track", "track-one", "unrelated")
    client.cover.assert_awaited_once_with("album")
    client.detail.assert_awaited_once()
    client.page.assert_not_called()


def test_artwork_grants_are_bounded_and_expire(runtime, monkeypatch):
    clock = [10.0]
    monkeypatch.setattr("custom_components.feiniu_music.runtime.monotonic", lambda: clock[0])
    tokens = [
        runtime.grant_artwork("track", "track-one", "cover-one")
        for _ in range(MAX_ARTWORK_GRANTS + 1)
    ]
    with pytest.raises(NotFoundError):
        runtime.artwork_owner(tokens[0])
    assert runtime.artwork_owner(tokens[-1]) == ("track", "track-one", "cover-one")
    clock[0] += ARTWORK_LIFETIME
    with pytest.raises(NotFoundError):
        runtime.artwork_owner(tokens[-1])
    runtime.grant_artwork("track", "track-two", "cover-two")
    assert len(runtime._artwork_grants) == 1


async def test_reauth_is_once_and_concurrent_generation_is_reused(runtime, client):
    runtime.generation = 1
    action = AsyncMock(side_effect=[AuthenticationError("expired"), "ok"])
    assert await runtime.call(action) == "ok"
    await asyncio.gather(runtime.reauthenticate(1), runtime.reauthenticate(1))
    client.login.assert_awaited_once()
    action = AsyncMock(side_effect=AuthenticationError("still expired"))
    with pytest.raises(AuthenticationError):
        await runtime.call(action)
    assert action.await_count == 2


@pytest.mark.parametrize(
    "error",
    [PermissionDeniedError("denied"), StreamRejectedError("100004"), NotFoundError("100005")],
)
async def test_permission_and_playback_errors_never_reauthenticate(runtime, client, error):
    with pytest.raises(type(error)):
        await runtime.call(AsyncMock(side_effect=error))
    client.login.assert_not_called()


async def test_unload_cancels_active_delivery_and_closes_session(runtime, client):
    started = asyncio.Event()
    cleaned = asyncio.Event()

    async def deliver():
        async with runtime.activity():
            try:
                started.set()
                await asyncio.Event().wait()
            finally:
                cleaned.set()

    task = asyncio.create_task(deliver())
    await started.wait()
    await runtime.close()
    assert task.cancelled() and cleaned.is_set() and not runtime._active
    client.__aexit__.assert_awaited_once()
    with pytest.raises(NotFoundError):
        await runtime.detail("track", "track-one")
