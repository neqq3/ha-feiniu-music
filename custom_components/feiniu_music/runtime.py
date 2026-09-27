"""Account-scoped native requests and lifecycle, independent of MA's models."""

from __future__ import annotations

import asyncio
import secrets
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from copy import deepcopy
from functools import partial
from time import monotonic
from typing import Any
from urllib.parse import urlsplit

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .client import (
    AuthenticationError,
    FeiNiuClient,
    NotFoundError,
    PermissionDeniedError,
    ProtocolError,
)
from .const import CONF_ACCOUNT_ID, CONF_DEVICE_ID, PAGE_SIZE

ARTWORK_LIFETIME = 2 * 60 * 60
MAX_ARTWORK_GRANTS = 128


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
        self._artwork_grants: dict[str, tuple[float, str, str, str]] = {}
        self._active: set[asyncio.Task] = set()

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
        data = await self.call(lambda: self.client.detail(kind, guid))
        row = data.get("track") if kind == "track" else data
        if not isinstance(row, dict) or row.get("guid") != guid:
            raise ProtocolError("Native detail has the wrong identity")
        if kind == "track":
            require_track(row)
            # Metadata carries audioSpec beside track, unlike some list responses.
            row = {**row, "audioSpec": data.get("audioSpec") or row.get("audioSpec") or {}}
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

    async def collection(self, kind: str) -> list[dict[str, Any]]:
        """Enumerate the account-filtered native library; never use it as a permission probe."""
        if kind == "playlist":
            return await self.call(self.client.playlists)
        return await self.pages(lambda page: self.client.page(kind, page))

    async def related(self, kind: str, guid: str, *, albums: bool = False) -> list[dict[str, Any]]:
        """Music 1.0.1 filters album/artist children server-side; only playlist rows carry status."""
        return await self.pages(
            lambda page: self.client.related(kind, guid, page, albums=albums),
            playlist=kind == "playlist",
        )

    async def search(self, kind: str, query: str) -> list[dict[str, Any]]:
        """Read complete account-filtered search results in native order."""
        return await self.pages(lambda page: self.client.search(kind, query, page, PAGE_SIZE))

    async def cover(self, kind: str, guid: str, cover: str) -> bytes:
        """A currently accessible owner cannot authorize an unrelated cover identifier."""
        row = await self.detail(kind, guid)
        if cover not in cover_ids(row):
            raise PermissionDeniedError("Image does not belong to this media item")
        return await self.call(lambda: self.client.cover(cover))

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
        self._details.clear()
        self._artwork_grants.clear()
        tasks = [task for task in self._active if task is not asyncio.current_task()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        await self.client.__aexit__(None, None, None)

    def check_open(self) -> None:
        """Reject stale references following unload or reconfiguration."""
        if self.closed:
            raise NotFoundError("Music source is unloaded")


type FeiNiuConfigEntry = ConfigEntry[FeiNiuRuntime]
