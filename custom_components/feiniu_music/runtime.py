"""Account-scoped native requests and lifecycle, independent of MA's models."""

from __future__ import annotations

import asyncio
import secrets
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import timedelta
from functools import partial
from time import monotonic
from typing import Any
from urllib.parse import urlsplit

from homeassistant.components import websocket_api
from homeassistant.components.http.auth import async_sign_path
from homeassistant.components.http.const import KEY_HASS_REFRESH_TOKEN_ID
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.http import current_request

from .client import (
    AuthenticationError,
    FeiNiuClient,
    NotFoundError,
    PermissionDeniedError,
    ProtocolError,
)
from .const import CONF_ACCOUNT_ID, CONF_DEVICE_ID, PAGE_SIZE
from .lyrics import parse_lyrics
from .streaming import AudioRound

ARTWORK_LIFETIME = 2 * 60 * 60
MAX_ARTWORK_GRANTS = 128
COVER_TTL = 5 * 60
MAX_COVER_BYTES = 32 * 1024 * 1024
MAX_COVERS = 512
BROWSE_TTL = 30
MAX_BROWSE_RESULTS = 16
MAX_BROWSE_ROWS = 10000
THUMBNAIL_LIFETIME = 30 * 60
MAX_THUMBNAIL_PATHS = 2048


def normalize_url(value: str) -> str:
    """Accept only the observed official root, without credentials or proxy prefixes."""
    parsed = urlsplit(value.strip())
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path.rstrip("/") not in {"", "/music"}
    ):
        raise ValueError("Use the official music root URL")
    port = parsed.port
    host = parsed.hostname.lower()
    if ":" in host:
        host = f"[{host}]"
    if port and (parsed.scheme, port) not in {("http", 80), ("https", 443)}:
        host += f":{port}"
    return f"{parsed.scheme}://{host}/music/"


def require_track(row: dict[str, Any]) -> None:
    """Only an explicit integer accessStatus=0 authorizes native track metadata."""
    status = row.get("accessStatus")
    if type(status) is not int:
        raise ProtocolError("Track metadata lacks a valid access status")
    if status == 2:
        raise PermissionDeniedError("Track is outside this account's library")
    if status == 3:
        raise NotFoundError("Track file is unavailable")
    if status != 0:
        raise ProtocolError("Unknown track access status")


def cover_ids(row: dict[str, Any]) -> set[str]:
    """Keep exact covers of an owner and its album/artist associations."""
    values = {row["coverId"]} if isinstance(row.get("coverId"), str) and row["coverId"] else set()
    if isinstance(row.get("album"), dict):
        values.update(cover_ids(row["album"]))
    for artist in row.get("artists") or []:
        if isinstance(artist, dict):
            values.update(cover_ids(artist))
    return values


class FeiNiuRuntime:
    """One entry owns its credentials, cache and bounded reauthentication."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, client: FeiNiuClient) -> None:
        self.hass = hass
        self.entry = entry
        self.client = client
        self.scope = secrets.token_hex(12)
        self.generation = 0
        self.closed = False
        self._failed_generation: int | None = None
        self._login_lock = asyncio.Lock()
        self._details: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}
        self._covers: dict[str, tuple[float, bytes]] = {}
        self._cover_tasks: dict[str, asyncio.Task[bytes]] = {}
        self._cover_waiters: dict[asyncio.Task[bytes], int] = {}
        self._image_slots = asyncio.Semaphore(2)
        self._browse_results: dict[tuple[str, ...], tuple[float, str, list[dict[str, Any]]]] = {}
        self._browse_lock = asyncio.Lock()
        self._thumbnail_paths: dict[tuple[str | None, str], tuple[float, str]] = {}
        self._artwork_grants: dict[str, tuple[float, str, str, str]] = {}
        self._active: set[asyncio.Task] = set()
        self.audio_rounds: dict[str, AudioRound] = {}
        self._lyrics: dict[str, tuple[float, dict[str, Any]]] = {}

    def grant_audio(self, route: AudioRound) -> str:
        """Keep only the current playback round per selected output."""
        self.check_open()
        self.cancel_audio(route.owner)
        token = secrets.token_hex(12)
        self.audio_rounds[token] = route
        return token

    def cancel_audio(self, owner: str) -> None:
        """Stopping one output must not cancel another output of the same account."""
        for token, route in list(self.audio_rounds.items()):
            if route.owner == owner:
                route.close()
                del self.audio_rounds[token]

    async def login(self) -> None:
        """Validate the same music identity configured in this entry."""
        user = await self.client.login(
            self.entry.data[CONF_USERNAME],
            self.entry.data[CONF_PASSWORD],
            self.entry.data[CONF_DEVICE_ID],
        )
        if user.get("guid") != self.entry.data[CONF_ACCOUNT_ID]:
            raise AuthenticationError("Music account identity changed; add a new source")
        self.generation += 1
        self._details.clear()
        self._lyrics.clear()
        self._covers.clear()
        self._browse_results.clear()
        self._thumbnail_paths.clear()

    async def reauthenticate(self, generation: int) -> None:
        """Coordinate a single retry; invalid credentials start HA's reauth flow."""
        async with self._login_lock:
            self.check_open()
            if generation != self.generation:
                return
            if self._failed_generation == generation:
                raise AuthenticationError("Reauthentication is required")
            try:
                await self.login()
            except AuthenticationError:
                self._failed_generation = generation
                self.entry.async_start_reauth(self.hass)
                raise

    async def call[T](self, action: Callable[[], Awaitable[T]]) -> T:
        """Retry authentication once, never reinterpret playback or permission refusals."""
        self.check_open()
        generation = self.generation
        for attempt in range(2):
            try:
                result = await action()
                self.check_open()
                return result
            except AuthenticationError:
                if attempt:
                    raise
                await self.reauthenticate(generation)
        raise AuthenticationError("Music authentication failed")

    async def detail(self, kind: str, guid: str, *, fresh: bool = False) -> dict[str, Any]:
        """Check access before admitting a detail response to the short entry-local cache."""
        self.check_open()
        key = (kind, guid)
        cached = self._details.get(key)
        if not fresh and cached and monotonic() - cached[0] < 30:
            return deepcopy(cached[1])
        self._details.pop(key, None)
        try:
            data = await self.call(lambda: self.client.detail(kind, guid))
            row = data.get("track") if kind == "track" else data
            if not isinstance(row, dict) or row.get("guid") != guid:
                raise ProtocolError("Native detail has the wrong identity")
            if kind == "track":
                require_track(row)
                # Metadata carries audioSpec beside track, unlike some list responses.
                row = {**row, "audioSpec": data.get("audioSpec") or row.get("audioSpec") or {}}
        except NotFoundError, PermissionDeniedError, ProtocolError:
            # A newly observed refusal supersedes an earlier successful browse.
            for cache_key, (_, row_kind, rows) in list(self._browse_results.items()):
                if row_kind == kind and any(item["guid"] == guid for item in rows):
                    self._browse_results.pop(cache_key)
            raise
        if len(self._details) >= 128:
            self._details.pop(next(iter(self._details)))
        self._details[key] = (monotonic(), deepcopy(row))
        return row

    async def pages(
        self, fetch: Callable[[int], Awaitable[dict[str, Any]]], *, playlist: bool = False
    ) -> list[dict[str, Any]]:
        """Read all native pages before returning any result, counting unfiltered rows."""
        result: list[dict[str, Any]] = []
        seen: set[str] = set()
        total: int | None = None
        received = 0
        for page in range(1, 10001):
            data = await self.call(partial(fetch, page))
            rows, count = data.get("list"), data.get("total")
            if not isinstance(rows, list) or type(count) is not int or count < 0:
                raise ProtocolError("Invalid native pagination")
            if len(rows) > PAGE_SIZE or (total is not None and count != total):
                raise ProtocolError("Native list changed during pagination")
            total = count
            for row in rows:
                if (
                    not isinstance(row, dict)
                    or not isinstance(row.get("guid"), str)
                    or not row["guid"]
                ):
                    raise ProtocolError("Missing native item ID")
                if not playlist and row["guid"] in seen:
                    raise ProtocolError("Repeated native item ID")
                seen.add(row["guid"])
                if not playlist or (
                    type(row.get("accessStatus")) is int and row["accessStatus"] == 0
                ):
                    result.append(row)
            received += len(rows)
            if received == total:
                return result
            if not rows or received > total:
                raise ProtocolError("Native pagination stopped before the reported total")
        raise ProtocolError("Native pagination safety limit exceeded")

    async def collection(self, kind: str, *, fresh: bool = False) -> list[dict[str, Any]]:
        """Enumerate the account-filtered native library; never use it as a permission probe."""

        async def read() -> list[dict[str, Any]]:
            if kind == "playlist":
                return await self.call(self.client.playlists)
            return await self.pages(lambda page: self.client.page(kind, page))

        return await self._browse(("collection", kind), kind, read, fresh=fresh)

    async def related(
        self, kind: str, guid: str, *, albums: bool = False, fresh: bool = False
    ) -> list[dict[str, Any]]:
        """Music 1.0.1 filters album/artist children server-side; only playlist rows carry status."""
        self.check_open()

        async def read() -> list[dict[str, Any]]:
            return await self.pages(
                lambda page: self.client.related(kind, guid, page, albums=albums),
                playlist=kind == "playlist",
            )

        row_kind = "album" if albums else "track"
        return await self._browse(("related", kind, guid, row_kind), row_kind, read, fresh=fresh)

    async def _browse(
        self,
        key: tuple[str, ...],
        kind: str,
        read: Callable[[], Awaitable[list[dict[str, Any]]]],
        *,
        fresh: bool = False,
    ) -> list[dict[str, Any]]:
        """Reuse only complete native results; hits never extend their original lifetime."""
        self.check_open()
        cached = self._browse_results.get(key)
        if not fresh and cached and monotonic() - cached[0] < BROWSE_TTL:
            return deepcopy(cached[2])
        async with self._browse_lock:
            self.check_open()
            now = monotonic()
            for expired, (created, _, _) in list(self._browse_results.items()):
                if now - created >= BROWSE_TTL:
                    self._browse_results.pop(expired)
            if not fresh and (cached := self._browse_results.get(key)):
                return deepcopy(cached[2])
            self._browse_results.pop(key, None)
            rows = await read()
            if len(rows) <= MAX_BROWSE_ROWS:
                while self._browse_results and (
                    len(self._browse_results) >= MAX_BROWSE_RESULTS
                    or sum(len(value[2]) for value in self._browse_results.values()) + len(rows)
                    > MAX_BROWSE_ROWS
                ):
                    self._browse_results.pop(next(iter(self._browse_results)))
                # Start the TTL before fetching, not after a potentially slow pagination.
                self._browse_results[key] = (now, kind, deepcopy(rows))
            return rows

    async def search(self, kind: str, query: str) -> list[dict[str, Any]]:
        """Read complete account-filtered search results in native order."""
        return await self._browse(
            ("search", kind, query),
            kind,
            lambda: self.pages(lambda page: self.client.search(kind, query, page, PAGE_SIZE)),
        )

    def _cover_owner(self, kind: str, guid: str) -> dict[str, Any] | None:
        """Reuse fresh, server-filtered browse rows for exact artwork ownership only."""
        now = monotonic()
        newest = now - BROWSE_TTL
        owner = None
        if (cached := self._details.get((kind, guid))) and cached[0] > newest:
            newest, owner = cached
        for created, row_kind, rows in self._browse_results.values():
            if row_kind != kind or created <= newest:
                continue
            for row in rows:
                if row["guid"] == guid:
                    newest, owner = created, row
                    break
        if owner is not None and kind == "track" and "accessStatus" in owner:
            require_track(owner)
        # Music 1.0.1 collection/search/album/artist rows are account-filtered;
        # some omit accessStatus. Playlist rows were explicitly filtered by pages().
        # None of these rows substitutes for fresh playback metadata.
        return owner

    async def display_track(self, guid: str) -> dict[str, Any]:
        """Reuse fresh scoped browse rows for display, never as playback authorization."""
        self.check_open()
        row = self._cover_owner("track", guid)
        return deepcopy(row) if row is not None else await self.detail("track", guid)

    async def lyrics(self, guid: str) -> dict[str, Any]:
        """Lyrics are optional display data, guarded by the existing detail lifetime."""
        async with self.activity():
            await self.detail("track", guid)
            now = monotonic()
            if (cached := self._lyrics.get(guid)) and now - cached[0] < 300:
                return deepcopy(cached[1])
            result = parse_lyrics(await self.call(lambda: self.client.lyrics(guid)))
            if len(self._lyrics) >= 32:
                self._lyrics.pop(next(iter(self._lyrics)))
            self._lyrics[guid] = (now, deepcopy(result))
            return result

    async def cover(self, kind: str, guid: str, cover: str) -> bytes:
        """A currently accessible owner cannot authorize an unrelated cover identifier."""
        # Limit image traffic entering the client's shared request queue, so navigating
        # away from a large grid does not put navigation/audio behind every thumbnail.
        async with self._image_slots:
            self.check_open()
            row = self._cover_owner(kind, guid)
            if row is None or cover not in cover_ids(row):
                row = await self.detail(kind, guid)
            if cover not in cover_ids(row):
                raise PermissionDeniedError("Image does not belong to this media item")
            return await self._cover_data(cover)

    async def _cover_data(self, cover: str) -> bytes:
        """Share downloads while at least one authorized consumer still needs them."""
        # Authorization stays ahead of both cached bytes and shared downloads.
        if (cached := self._covers.get(cover)) and monotonic() - cached[0] < COVER_TTL:
            return cached[1]
        if (task := self._cover_tasks.get(cover)) is None:
            task = self.hass.async_create_task(
                self._fetch_cover(cover), "FeiNiu artwork fetch", eager_start=False
            )
            self._cover_tasks[cover] = task
        self._cover_waiters[task] = self._cover_waiters.get(task, 0) + 1
        try:
            return await asyncio.shield(task)
        finally:
            self._cover_waiters[task] -= 1
            if not self._cover_waiters[task]:
                self._cover_waiters.pop(task)
                if self._cover_tasks.get(cover) is task:
                    self._cover_tasks.pop(cover)
                if not task.done():
                    task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    async def _fetch_cover(self, cover: str) -> bytes:
        """Keep a bounded source-byte cache; entry unload owns these short-lived tasks."""
        data = await self.call(lambda: self.client.cover(cover))
        now = monotonic()
        for key, (created, _) in list(self._covers.items()):
            if now - created >= COVER_TTL:
                self._covers.pop(key)
        if len(data) <= MAX_COVER_BYTES:
            while self._covers and (
                len(self._covers) >= MAX_COVERS
                or sum(len(value[1]) for value in self._covers.values()) + len(data)
                > MAX_COVER_BYTES
            ):
                self._covers.pop(next(iter(self._covers)))
            self._covers[cover] = (now, data)
        return data

    def thumbnail_path(self, path: str) -> str:
        """Reuse an exact signed path, rotating before the HA signature expires."""
        self.check_open()
        now = monotonic()
        # HA signs with the current browser session's issuer. Never reuse its
        # signed link in another HA session, even for the same music account.
        issuer = None
        if (connection := websocket_api.current_connection.get()) and connection.refresh_token_id:
            issuer = connection.refresh_token_id
        elif (request := current_request.get()) is not None:
            issuer = request.get(KEY_HASS_REFRESH_TOKEN_ID)
        cache_key = (issuer, path)
        for key, (expires, _) in list(self._thumbnail_paths.items()):
            if expires <= now:
                self._thumbnail_paths.pop(key)
        if cached := self._thumbnail_paths.get(cache_key):
            return cached[1]
        if len(self._thumbnail_paths) >= MAX_THUMBNAIL_PATHS:
            self._thumbnail_paths.pop(next(iter(self._thumbnail_paths)))
        signed = async_sign_path(
            self.hass, path, timedelta(seconds=THUMBNAIL_LIFETIME), refresh_token_id=issuer
        )
        self._thumbnail_paths[cache_key] = (now + THUMBNAIL_LIFETIME - 60, signed)
        return signed

    def grant_artwork(self, kind: str, guid: str, cover: str) -> str:
        """Issue a bounded, short-lived image grant for length-limited DLNA players."""
        self.check_open()
        now = monotonic()
        for token, (expires, *_) in list(self._artwork_grants.items()):
            if expires <= now:
                self._artwork_grants.pop(token)
        if len(self._artwork_grants) >= MAX_ARTWORK_GRANTS:
            self._artwork_grants.pop(next(iter(self._artwork_grants)))
        token = secrets.token_urlsafe(24)
        self._artwork_grants[token] = (now + ARTWORK_LIFETIME, kind, guid, cover)
        return token

    def artwork_owner(self, token: str) -> tuple[str, str, str]:
        """Resolve only the exact granted owner/cover; normal access checks still apply."""
        self.check_open()
        grant = self._artwork_grants.get(token)
        if grant is None or grant[0] <= monotonic():
            self._artwork_grants.pop(token, None)
            raise NotFoundError("Artwork link expired or unavailable")
        return grant[1], grant[2], grant[3]

    @asynccontextmanager
    async def activity(self) -> AsyncIterator[None]:
        """Let entry unload cancel active HTTP deliveries and release their responses."""
        self.check_open()
        task = asyncio.current_task()
        if task:
            self._active.add(task)
        try:
            yield
        finally:
            if task:
                self._active.discard(task)

    async def close(self) -> None:
        """Invalidate cached media and close all streams belonging to this entry."""
        self.closed = True
        for route in self.audio_rounds.values():
            route.close()
        self.audio_rounds.clear()
        self._details.clear()
        self._lyrics.clear()
        self._covers.clear()
        self._browse_results.clear()
        self._thumbnail_paths.clear()
        self._artwork_grants.clear()
        tasks = list((self._active | set(self._cover_tasks.values())) - {asyncio.current_task()})
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._cover_tasks.clear()
        await self.client.__aexit__(None, None, None)

    def check_open(self) -> None:
        """Reject stale references following unload or reconfiguration."""
        if self.closed:
            raise NotFoundError("Music source is unloaded")


type FeiNiuConfigEntry = ConfigEntry[FeiNiuRuntime]
