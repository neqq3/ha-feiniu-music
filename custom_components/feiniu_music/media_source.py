"""Browse and search native FeiNiu accounts through HA's media source platform."""

import asyncio
from datetime import timedelta
from typing import Any

from homeassistant.components.http.auth import async_sign_path
from homeassistant.components.media_player import (
    BrowseError,
    BrowseMedia,
    SearchMedia,
    SearchMediaQuery,
)
from homeassistant.components.media_player.browse_media import async_process_play_media_url
from homeassistant.components.media_source import (
    BrowseMediaSource,
    MediaSource,
    MediaSourceItem,
    Unresolvable,
)
from homeassistant.core import HomeAssistant

from .browse import BrowsePage
from .client import FeiNiuError, NotFoundError, ProtocolError
from .const import DOMAIN, KINDS, NAME, PAGE_SIZE
from .media import (
    MEDIA_CLASSES,
    FeiNiuPlayMedia,
    folder,
    media_item,
    mime_type,
    play_media,
    valid_id,
)
from .runtime import BROWSE_TIMEOUT, ENUMERATION_TIMEOUT, FeiNiuRuntime


class PagedFolder(BrowseMediaSource):
    """Native next/previous directories plus optional card display information."""

    def __init__(self, identifier: str, title: str, children: list, page: BrowsePage, size: int):
        super().__init__(
            domain=DOMAIN,
            identifier=identifier,
            title=title,
            children=children,
            media_class="directory",
            media_content_type="music",
            can_play=False,
            can_expand=True,
            can_search=True,
        )
        self.page_info = {
            "offset": page.offset,
            "size": size,
            "total": page.total,
            "context_id": self.media_content_id,
            "refresh_id": f"{self.media_content_id}/page/{page.offset // size + 1}/{size}/refresh",
        }

    def as_dict(self, *, parent: bool = True) -> dict[str, Any]:
        result = super().as_dict(parent=parent)
        if parent:
            result["feiniu_paging"] = dict(self.page_info)
        return result


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
        """Browse one native page, keeping playlist occurrence lists complete."""
        try:
            # Includes admission, native I/O, re-login and assembly. Playlist reads
            # retain their full-list budget; other first screens need one page.
            parts = item.identifier.split("/")
            budget = (
                ENUMERATION_TIMEOUT if len(parts) > 1 and parts[1] == "playlist" else BROWSE_TIMEOUT
            )
            async with asyncio.timeout(budget):
                return await self._browse(item.identifier)
        except TimeoutError as err:
            raise BrowseError("Music browsing timed out; retry") from err
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
        page, size, fresh = 1, PAGE_SIZE, False
        if len(parts) >= 5 and parts[-1] == "refresh" and parts[-4] == "page":
            parts = parts[:-1]
            fresh = True
        paged = len(parts) >= 4 and parts[-3] == "page"
        if paged:
            if not parts[-2].isdigit() or not parts[-1].isdigit():
                raise ProtocolError("Invalid browse page")
            page, size = int(parts[-2]), int(parts[-1])
            parts = parts[:-3]
        identifier = "/".join([base, *parts])
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
            if kind != "playlist":
                data = await runtime.browse_page(kind, page=page, size=size, fresh=fresh)
                return self._page_folder(runtime, identifier, kind, data, size)
            if paged:
                raise NotFoundError("Playlist lists are not paginated")
            rows = await runtime.collection(kind, fresh=fresh)
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
            if len(parts) != 2 or paged:
                raise NotFoundError("Unknown track path")
            return media_item(runtime, kind, await runtime.detail(kind, guid))
        if kind == "artist":
            if len(parts) == 2:
                if paged:
                    raise NotFoundError("Select an artist relationship")
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
            data = await runtime.browse_page(
                kind,
                guid=guid,
                albums=albums,
                page=page,
                size=size,
                fresh=fresh,
            )
            return self._page_folder(
                runtime, identifier, "album" if albums else "track", data, size
            )
        if len(parts) != 2:
            raise NotFoundError("Unknown media relationship")
        if kind == "album":
            data = await runtime.browse_page(kind, guid=guid, page=page, size=size, fresh=fresh)
            return self._page_folder(runtime, identifier, "track", data, size)
        if paged:
            raise NotFoundError("Playlist occurrences are not paginated")
        rows = await runtime.related(kind, guid, fresh=fresh)
        return self._track_folder(runtime, identifier, rows)

    def _page_folder(
        self,
        runtime: FeiNiuRuntime,
        identifier: str,
        kind: str,
        data: BrowsePage,
        size: int,
    ) -> PagedFolder:
        children = [media_item(runtime, kind, row) for row in data.rows]
        if kind == "track":
            for index, child in enumerate(children, data.offset):
                guid = data.rows[index - data.offset]["guid"]
                child.media_content_id = (
                    f"media-source://{DOMAIN}/{identifier}/queue/{index}/{guid}"
                )
        page = data.offset // size + 1
        for number, title in ((page - 1, "Previous page"), (page + 1, "Next page")):
            if number < 1 or (number - 1) * size >= data.total:
                continue
            link = folder(f"{identifier}/page/{number}/{size}", title, [])
            link.media_content_type = "feiniu_page"
            children.append(link)
        result = PagedFolder(identifier, kind.title() + "s", children, data, size)
        return result

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
        """Bound the complete multi-kind search, including waiting and pagination."""
        try:
            async with asyncio.timeout(ENUMERATION_TIMEOUT):
                return await self._search_media(item, query)
        except TimeoutError as err:
            raise BrowseError("Music search timed out; retry") from err

    async def _search_media(self, item: MediaSourceItem, query: SearchMediaQuery) -> SearchMedia:
        """Search inside one account, across native media types or the selected category."""
        try:
            runtime, parts = self._runtime(item.identifier)
            text = query.search_query.strip()
            if not text or len(text) > 256:
                raise ProtocolError("Search text must contain 1 to 256 characters")
            kinds = [parts[0]] if parts and parts[0] in KINDS else KINDS
            result: list[BrowseMedia] = []
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
