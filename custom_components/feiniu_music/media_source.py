"""Browse and search native FeiNiu accounts through HA's media source platform."""

from datetime import timedelta
from typing import Any

from homeassistant.components.http.auth import async_sign_path
from homeassistant.components.media_player import BrowseError, SearchMedia, SearchMediaQuery
from homeassistant.components.media_player.browse_media import async_process_play_media_url
from homeassistant.components.media_source import (
    BrowseMediaSource,
    MediaSource,
    MediaSourceItem,
    Unresolvable,
)
from homeassistant.core import HomeAssistant

from .client import FeiNiuError, NotFoundError, ProtocolError
from .const import DOMAIN, KINDS, NAME
from .media import (
    MEDIA_CLASSES,
    FeiNiuPlayMedia,
    folder,
    media_item,
    mime_type,
    play_media,
    valid_id,
)
from .runtime import FeiNiuRuntime


async def async_get_media_source(hass: HomeAssistant) -> MediaSource:
    """Expose all configured music entries under one HA source."""
    return FeiNiuMediaSource(hass)


class FeiNiuMediaSource(MediaSource):
    """Native, read-only collections and relationships, including artist tracks."""

    name = NAME

    def __init__(self, hass: HomeAssistant) -> None:
        super().__init__(DOMAIN)
        self.hass = hass

    def _runtime(self, identifier: str) -> tuple[FeiNiuRuntime, list[str]]:
        parts = identifier.split("/")
        for part in parts:
            valid_id(part)
        runtime = self.hass.data[DOMAIN]["entries"].get(parts[0])
        if runtime is None or runtime.closed:
            raise NotFoundError("Music source is unavailable")
        return runtime, parts[1:]

    async def async_browse_media(self, item: MediaSourceItem) -> BrowseMediaSource:
        """Expose complete lists; account-filtered artist and album rows need no status flag."""
        try:
            return await self._browse(item.identifier)
        except FeiNiuError as err:
            raise BrowseError(str(err)) from err

    async def _browse(self, identifier: str) -> BrowseMediaSource:
        if not identifier:
            children = [
                folder(key, runtime.entry.title, [])
                for key, runtime in self.hass.data[DOMAIN]["entries"].items()
                if not runtime.closed
            ]
            return folder(None, NAME, children)
        runtime, parts = self._runtime(identifier)
        base = runtime.entry.entry_id
        if not parts:
            return folder(
                base,
                runtime.entry.title,
                [folder(f"{base}/{kind}", kind.title() + "s", []) for kind in KINDS],
                search=True,
            )
        kind = parts[0]
        if kind not in KINDS:
            raise NotFoundError("Unknown media category")
        if len(parts) == 1:
            rows = await runtime.collection(kind)
            if kind == "track":
                return self._track_folder(runtime, identifier, rows)
            return folder(
                identifier,
                kind.title() + "s",
                [media_item(runtime, kind, row) for row in rows],
                search=True,
            )
        if len(parts) not in {2, 3}:
            raise NotFoundError("Unknown media path")
        guid = parts[1]
        if kind == "track":
            if len(parts) != 2:
                raise NotFoundError("Unknown track path")
            return media_item(runtime, kind, await runtime.detail(kind, guid))
        if kind == "artist":
            if len(parts) == 2:
                artist = await runtime.detail(kind, guid)
                return folder(
                    identifier,
                    artist.get("name") or "Artist",
                    [
                        folder(f"{identifier}/tracks", "Tracks", []),
                        folder(f"{identifier}/albums", "Albums", []),
                    ],
                )
            if parts[2] not in {"tracks", "albums"}:
                raise NotFoundError("Unknown artist relationship")
            albums = parts[2] == "albums"
            # Music 1.0.1 (0.8.41) filters inaccessible artist children server-side.
            rows = await runtime.related(kind, guid, albums=albums)
            if not albums:
                return self._track_folder(runtime, identifier, rows)
            return folder(
                identifier,
                parts[2].title(),
                [media_item(runtime, "album" if albums else "track", row) for row in rows],
            )
        if len(parts) != 2:
            raise NotFoundError("Unknown media relationship")
        rows = await runtime.related(kind, guid)
        return self._track_folder(runtime, identifier, rows)

    def _track_folder(
        self, runtime: FeiNiuRuntime, identifier: str, rows: list[dict[str, Any]]
    ) -> BrowseMediaSource:
        """Keep list context for queue players; direct players still resolve one track."""
        children = [media_item(runtime, "track", row) for row in rows]
        for index, child in enumerate(children):
            guid = child.media_content_id.rsplit("/", 1)[-1]
            child.media_content_id = f"media-source://{DOMAIN}/{identifier}/queue/{index}/{guid}"
        return folder(identifier, "Tracks", children, search=True)

    async def async_search_media(
        self, item: MediaSourceItem, query: SearchMediaQuery
    ) -> SearchMedia:
        """Search inside one account, across native media types or the selected category."""
        try:
            runtime, parts = self._runtime(item.identifier)
            text = query.search_query.strip()
            if not text or len(text) > 256:
                raise ProtocolError("Search text must contain 1 to 256 characters")
            kinds = [parts[0]] if parts and parts[0] in KINDS else KINDS
            result: list[BrowseMediaSource] = []
            for kind in kinds:
                if (
                    query.media_filter_classes
                    and MEDIA_CLASSES[kind] not in query.media_filter_classes
                ):
                    continue
                result.extend(
                    media_item(runtime, kind, row) for row in await runtime.search(kind, text)
                )
            return SearchMedia(result=result)
        except FeiNiuError as err:
            raise BrowseError(str(err)) from err

    async def async_resolve_media(self, item: MediaSourceItem) -> FeiNiuPlayMedia:
        """Return only a short-lived HA URL, never a native NAS URL or music token."""
        try:
            runtime, parts = self._runtime(item.identifier)
            if len(parts) >= 4 and parts[-3] == "queue" and parts[-2].isdigit():
                context = parts[:-3]
                if (
                    context == ["track"]
                    or (len(context) == 2 and context[0] in {"album", "playlist"})
                    or (len(context) == 3 and context[0] == "artist" and context[2] == "tracks")
                ):
                    parts = ["track", parts[-1]]
            if len(parts) != 2 or parts[0] != "track":
                raise NotFoundError("Select a single track to play")
            row = await runtime.detail("track", parts[1], fresh=True)
            content_type = mime_type(row)
            path = f"/api/{DOMAIN}/{runtime.entry.entry_id}/{runtime.scope}/audio/{parts[1]}"
            signed = async_sign_path(self.hass, path, timedelta(hours=2))
            return play_media(
                runtime, row, async_process_play_media_url(self.hass, signed), content_type
            )
        except FeiNiuError as err:
            raise Unresolvable(str(err)) from err
