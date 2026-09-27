"""Authenticated HA endpoints for original audio and owner-bound artwork."""

import asyncio
import re

import aiohttp
from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant

from .client import (
    AuthenticationError,
    FeiNiuError,
    NetworkError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
    StreamRejectedError,
    classify_media,
)
from .const import DOMAIN, KINDS
from .media import mime_type, valid_id
from .runtime import FeiNiuRuntime


def runtime_for(hass: HomeAssistant, entry_id: str, scope: str) -> FeiNiuRuntime:
    """A removed or reloaded entry must not serve a previously signed media path."""
    runtime = hass.data[DOMAIN]["entries"].get(entry_id)
    if runtime is None or runtime.closed or scope != runtime.scope:
        raise web.HTTPNotFound
    return runtime


def http_error(err: FeiNiuError) -> web.HTTPException:
    """Expose useful error categories without upstream bodies, paths or credentials."""
    if isinstance(err, NotFoundError):
        return web.HTTPNotFound(text="Music item unavailable")
    if isinstance(err, PermissionDeniedError | StreamRejectedError):
        return web.HTTPForbidden(text="Music service refused access")
    if isinstance(err, RateLimitError):
        return web.HTTPTooManyRequests(
            text="Music service rate limit", headers={"Retry-After": str(err.backoff_time)}
        )
    if isinstance(err, AuthenticationError):
        return web.HTTPServiceUnavailable(text="Reauthenticate this music source in Home Assistant")
    if isinstance(err, NetworkError):
        return web.HTTPServiceUnavailable(text="Music service temporarily unavailable")
    return web.HTTPBadGateway(text="Invalid music service response")


class FeiNiuAudioView(HomeAssistantView):
    """Stream one native resource through HA's existing authenticated web server."""

    url = "/api/feiniu_music/{entry_id}/{scope}/audio/{guid}"
    name = "api:feiniu_music:audio"
    requires_auth = True

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass

    async def head(
        self, request: web.Request, entry_id: str, scope: str, guid: str
    ) -> web.StreamResponse:
        """Validate the same bounded prefix as GET, without delivering a response body."""
        return await self._serve(request, entry_id, scope, guid, head=True)

    async def get(
        self, request: web.Request, entry_id: str, scope: str, guid: str
    ) -> web.StreamResponse:
        """Forward a single Range while keeping the native URL and Cookie server-side."""
        return await self._serve(request, entry_id, scope, guid, head=False)

    async def _serve(
        self, request: web.Request, entry_id: str, scope: str, guid: str, *, head: bool
    ) -> web.StreamResponse:
        runtime = runtime_for(self.hass, entry_id, scope)
        byte_range = request.headers.get("Range")
        if byte_range:
            if len(byte_range) > 100 or not re.fullmatch(r"bytes=(?:\d+-\d*|-\d+)", byte_range):
                raise web.HTTPRequestRangeNotSatisfiable
            start, end = byte_range[6:].split("-")
            if (start and end and int(start) > int(end)) or (not start and int(end) == 0):
                raise web.HTTPRequestRangeNotSatisfiable
        delivered: web.StreamResponse | None = None
        try:
            valid_id(guid)
            async with runtime.activity():
                row = await runtime.detail("track", guid, fresh=True)
                audio_type = mime_type(row)
                generation = runtime.generation
                for attempt in range(2):
                    try:
                        async with runtime.client.open_audio(guid, byte_range) as upstream:
                            native = upstream.response
                            headers = {
                                "Content-Type": audio_type,
                                "Cache-Control": "private, no-store",
                                "X-Content-Type-Options": "nosniff",
                            }
                            if native.status == 416:
                                content_range = native.headers.get("Content-Range", "")
                                if re.fullmatch(r"bytes \*/\d+", content_range):
                                    headers["Content-Range"] = content_range
                                return web.Response(status=416, headers=headers)
                            for key in ("Content-Length", "Content-Range", "Accept-Ranges"):
                                if value := native.headers.get(key):
                                    headers[key] = value
                            if head:
                                return web.Response(status=native.status, headers=headers)
                            delivered = web.StreamResponse(status=native.status, headers=headers)
                            await delivered.prepare(request)
                            async for chunk in upstream.chunks():
                                await delivered.write(chunk)
                            await delivered.write_eof()
                            return delivered
                    except AuthenticationError:
                        if attempt or delivered is not None:
                            raise
                        await runtime.reauthenticate(generation)
        except FeiNiuError as err:
            if delivered is None:
                raise http_error(err) from err
            delivered.force_close()
            if request.transport:
                request.transport.close()
            return delivered
        except aiohttp.ClientError, OSError, TimeoutError:
            if delivered is not None:
                delivered.force_close()
                if request.transport:
                    request.transport.close()
                return delivered
            raise web.HTTPServiceUnavailable(text="Music stream connection failed") from None
        except asyncio.CancelledError:
            if delivered is not None:
                delivered.force_close()
            raise
        raise web.HTTPServiceUnavailable(text="Music authentication failed")


class FeiNiuImageView(HomeAssistantView):
    """Serve a cover only after validating its current native owner relationship."""

    url = "/api/feiniu_music/{entry_id}/{scope}/image/{kind}/{guid}/{cover}"
    name = "api:feiniu_music:image"
    requires_auth = True

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass

    async def get(
        self, request: web.Request, entry_id: str, scope: str, kind: str, guid: str, cover: str
    ) -> web.Response:
        """Do not accept arbitrary native URLs or unrelated cover IDs."""
        runtime = runtime_for(self.hass, entry_id, scope)
        if kind not in KINDS:
            raise web.HTTPNotFound
        try:
            valid_id(guid)
            valid_id(cover)
            return await image_response(runtime, kind, guid, cover)
        except FeiNiuError as err:
            raise http_error(err) from err


class FeiNiuArtworkView(HomeAssistantView):
    """Short DLNA artwork links, authenticated by an exact, expiring image grant."""

    url = "/api/feiniu_music/{entry_id}/artwork"
    name = "api:feiniu_music:artwork"
    requires_auth = False

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass

    async def get(self, request: web.Request, entry_id: str) -> web.Response:
        """A grant cannot select arbitrary owners or bypass the music account's access."""
        runtime = self.hass.data[DOMAIN]["entries"].get(entry_id)
        if runtime is None:
            raise web.HTTPNotFound
        try:
            owner = runtime.artwork_owner(request.query.get("token", ""))
            return await image_response(runtime, *owner)
        except FeiNiuError as err:
            raise http_error(err) from err


async def image_response(runtime: FeiNiuRuntime, kind: str, guid: str, cover: str) -> web.Response:
    """Both image URL forms use the same owner check and authenticated native request."""
    async with runtime.activity():
        data = await runtime.cover(kind, guid, cover)
    content_type = {"jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}[
        classify_media(data)
    ]
    return web.Response(
        body=data,
        content_type=content_type,
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )
