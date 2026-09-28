"""Real HTTP bodies stay open while other native request lanes proceed."""

import asyncio

import pytest
from aiohttp import web

from custom_components.feiniu_music.client import FeiNiuClient

from .conftest import image_bytes
from .test_client import PROFILE

pytestmark = pytest.mark.enable_socket


async def test_four_distinct_covers_do_not_block_metadata_or_audio(aiohttp_server):
    started, release = asyncio.Event(), asyncio.Event()
    active = peak = total = 0
    image = image_bytes()

    async def cover(request):
        nonlocal active, peak, total
        assert request.query["size"] == "600"
        total += 1
        active += 1
        peak = max(active, peak)
        response = web.StreamResponse(headers={"Content-Type": "image/png"})
        await response.prepare(request)
        await response.write(image[:16])
        if active == 4:
            started.set()
        try:
            await release.wait()
            await response.write(image[16:])
            return response
        finally:
            active -= 1

    async def metadata(request):
        return web.json_response({"code": 0, "data": {"guid": "synthetic"}})

    async def audio(request):
        return web.Response(body=b"fLaC" + b"x" * 4092, content_type="audio/flac")

    app = web.Application()
    app.router.add_get("/music/api/v1/static/cover", cover)
    app.router.add_get("/music/api/v1/user/me", metadata)
    app.router.add_get("/music/api/v1/track/stream", audio)
    server = await aiohttp_server(app)
    async with FeiNiuClient(str(server.make_url("/music/")), PROFILE) as client:
        client._token = "synthetic-token"
        tasks = [asyncio.create_task(client.cover(str(i))) for i in range(8)]
        try:
            await asyncio.wait_for(started.wait(), 2)
            assert total == 4 and peak == 4
            assert await asyncio.wait_for(client.current_user(), 1) == {"guid": "synthetic"}
            async with asyncio.timeout(1), client.open_audio("synthetic-track") as response:
                assert response.prefix.startswith(b"fLaC")
            assert total == 4, "Interactive requests must not wait for image completion"
        finally:
            release.set()
            assert await asyncio.gather(*tasks) == [image] * 8
        assert peak == 4 and not client._session.connector._acquired


async def test_late_old_session_error_does_not_clear_reauthenticated_token(aiohttp_server, runtime):
    all_old, logged_in = asyncio.Event(), asyncio.Event()
    old_count = new_count = logins = 0

    async def current(request):
        nonlocal old_count, new_count
        if request.headers.get("Cookie") == "music-token=synthetic-new":
            new_count += 1
            return web.json_response({"code": 0, "data": {"guid": "account-one"}})
        old_count += 1
        index = old_count
        if index == 4:
            all_old.set()
        await all_old.wait()
        if index == 4:
            await logged_in.wait()
        return web.json_response({"code": 120001, "data": {}})

    async def login(request):
        nonlocal logins
        logins += 1
        return web.json_response(
            {"code": 0, "data": {"userToken": "synthetic-new", "user": {"guid": "account-one"}}}
        )

    app = web.Application()
    app.router.add_get("/music/api/v1/user/me", current)
    app.router.add_post("/music/api/v1/user/password-login", login)
    server = await aiohttp_server(app)
    async with FeiNiuClient(str(server.make_url("/music/")), PROFILE) as client:
        runtime.client = client
        client._token = "synthetic-old"
        native_login = client.login

        async def observed_login(*args):
            user = await native_login(*args)
            logged_in.set()
            return user

        client.login = observed_login
        results = await asyncio.wait_for(
            asyncio.gather(*(runtime.call(client.current_user) for _ in range(4))), 4
        )
        assert results == [{"guid": "account-one"}] * 4
        assert (old_count, new_count, logins) == (4, 4, 1)
        assert client._token == "synthetic-new" and runtime.generation == 1
