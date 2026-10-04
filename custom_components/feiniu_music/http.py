"""Authenticated HA endpoints for original audio and owner-bound artwork."""

import asyncio
import logging
import re
from time import time

import aiohttp
import jwt
from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant

from .artwork import SIZES
from .client import (
    AuthenticationError,
    FeiNiuError,
    NetworkError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
    StreamRejectedError,
)
from .const import DOMAIN, KINDS
from .media import mime_type, valid_id
from .runtime import FeiNiuRuntime
from .streaming import AudioRound
from .support import private_id

_LOGGER = logging.getLogger(__name__)


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
        self,
        request: web.Request,
        entry_id: str,
        scope: str,
        guid: str,
        *,
        head: bool,
        route: AudioRound | None = None,
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
        task = asyncio.current_task()
        if route:
            try:
                route.check()
            except NotFoundError as err:
                raise http_error(err) from err
            if task:
                route.tasks.add(task)
            route.event("head" if head else "get")
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
                            first = True
                            async for chunk in upstream.chunks():
                                if route:
                                    route.check()
                                try:
                                    await delivered.write(chunk)
                                except ConnectionResetError:
                                    # A player may close an old Range request when seeking.
                                    # Downstream disconnect is not an upstream media refusal.
                                    if route:
                                        route.event("cancelled")
                                    delivered.force_close()
                                    return delivered
                                if first and chunk:
                                    first = False
                                    if route:
                                        route.event("first_byte")
                            try:
                                await delivered.write_eof()
                            except ConnectionResetError:
                                if route:
                                    route.event("cancelled")
                                return delivered
                            if route:
                                route.event("eof")
                            return delivered
                    except AuthenticationError:
                        if attempt or delivered is not None:
                            raise
                        await runtime.reauthenticate(generation)
        except FeiNiuError as err:
            _LOGGER.debug(
                "Audio request failed client=%s output=%s round=%s category=%s",
                runtime.client.debug_ref,
                private_id(route.owner) if route else None,
                route.round_id if route else None,
                type(err).__name__,
            )
            if route:
                route.event("error")
            if delivered is None:
                raise http_error(err) from err
            delivered.force_close()
            if request.transport:
                request.transport.close()
            return delivered
        except (aiohttp.ClientError, OSError, TimeoutError) as err:
            _LOGGER.debug(
                "Audio request failed client=%s output=%s round=%s category=%s",
                runtime.client.debug_ref,
                private_id(route.owner) if route else None,
                route.round_id if route else None,
                type(err).__name__,
            )
            if route:
                route.event("error")
            if delivered is not None:
                delivered.force_close()
                if request.transport:
                    request.transport.close()
                return delivered
            raise web.HTTPServiceUnavailable(text="Music stream connection failed") from None
        except asyncio.CancelledError:
            _LOGGER.debug(
                "Audio request cancelled output=%s round=%s",
                private_id(route.owner) if route else None,
                route.round_id if route else None,
            )
            if route:
                route.event("cancelled")
            if delivered is not None:
                delivered.force_close()
            raise
        finally:
            if route and task:
                route.tasks.discard(task)
        raise web.HTTPServiceUnavailable(text="Music authentication failed")


class FeiNiuSessionAudioView(FeiNiuAudioView):
    """Same Range/auth/error handling, with a distinct cancellable output round."""

    url = "/api/feiniu_music/{entry_id}/{scope}/session/{token}/{guid}"
    name = "api:feiniu_music:session_audio"

    async def head(
        self, request: web.Request, entry_id: str, scope: str, guid: str, token: str = ""
    ) -> web.StreamResponse:
        return await self._session(request, entry_id, scope, guid, token, head=True)

    async def get(
        self, request: web.Request, entry_id: str, scope: str, guid: str, token: str = ""
    ) -> web.StreamResponse:
        return await self._session(request, entry_id, scope, guid, token, head=False)

    async def _session(
        self, request: web.Request, entry_id: str, scope: str, guid: str, token: str, *, head: bool
    ) -> web.StreamResponse:
        runtime = runtime_for(self.hass, entry_id, scope)
        route = runtime.audio_rounds.get(token)
        if route is None or route.guid != guid:
            raise web.HTTPNotFound
        return await self._serve(request, entry_id, scope, guid, head=head, route=route)


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
            return await image_response(runtime, kind, guid, cover, request)
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
            token = request.query.get("token", "")
            kind, guid, cover = runtime.artwork_owner(token)
            return await image_response(
                runtime,
                kind,
                guid,
                cover,
                request,
                max_age=runtime.artwork_max_age(token),
                default_size=512,
            )
        except FeiNiuError as err:
            raise http_error(err) from err


async def image_response(
    runtime: FeiNiuRuntime,
    kind: str,
    guid: str,
    cover: str,
    request: web.Request,
    *,
    max_age: int = 30,
    default_size: int = 256,
) -> web.Response:
    """Both image URL forms use the same owner check and authenticated native request."""
    try:
        size = int(request.query.get("size", str(default_size)))
    except ValueError as err:
        raise web.HTTPBadRequest(text="Unsupported thumbnail size") from err
    if size not in SIZES:
        raise web.HTTPBadRequest(text="Unsupported thumbnail size")
    async with runtime.activity():
        image = await runtime.thumbnail(kind, guid, cover, size)
    max_age = min(max_age, runtime.image_max_age(kind, guid))
    if signature := request.query.get("authSig"):
        # HA's middleware already authenticates the signature and exact path.
        # Read exp only to shorten cache lifetime, never to grant access.
        try:
            expires = jwt.decode(signature, options={"verify_signature": False})["exp"]
            max_age = min(max_age, max(0, int(expires - time())))
        except (jwt.InvalidTokenError, KeyError, TypeError, ValueError, OverflowError):
            max_age = 0
    etag = image.etag
    headers = {
        "Cache-Control": f"private, max-age={max_age}, must-revalidate",
        "Vary": "Authorization, Cookie",
        "ETag": f'"{etag}"',
        "X-Content-Type-Options": "nosniff",
    }
    if request.if_none_match and any(tag.value in {etag, "*"} for tag in request.if_none_match):
        return web.Response(status=304, headers=headers)
    return web.Response(
        body=image.data,
        content_type=image.content_type,
        headers=headers,
    )
