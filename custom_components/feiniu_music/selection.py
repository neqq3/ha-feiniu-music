"""Media browser list context and queue selection, without playback state."""

from homeassistant.components.media_player import BrowseMedia, SearchMedia, SearchMediaQuery
from homeassistant.components.media_source import MediaSourceItem
from homeassistant.exceptions import ServiceValidationError

from .const import DOMAIN
from .media import valid_id
from .media_source import FeiNiuMediaSource
from .queue import QueueItem
from .runtime import FeiNiuRuntime


class Selection:
    """Keep account and list position across HA's native browse/play protocol."""

    def __init__(self, runtime: FeiNiuRuntime, entity_id: str) -> None:
        self.runtime = runtime
        self.entity_id = entity_id

    def identifier(self, media_id: str) -> str:
        prefix = f"media-source://{DOMAIN}/{self.runtime.entry.entry_id}"
        if media_id == prefix:
            return self.runtime.entry.entry_id
        if not media_id.startswith(prefix + "/"):
            raise ServiceValidationError("Select media from this FeiNiu account")
        identifier = media_id[len(f"media-source://{DOMAIN}/") :]
        for part in identifier.split("/"):
            valid_id(part)
        return identifier

    async def browse(
        self, media_content_type: str | None = None, media_content_id: str | None = None
    ) -> BrowseMedia:
        """Attach list context to each track, so selecting a song can continue its list."""
        identifier = (
            self.identifier(media_content_id) if media_content_id else self.runtime.entry.entry_id
        )
        result = await FeiNiuMediaSource(self.runtime.hass).async_browse_media(
            MediaSourceItem(self.runtime.hass, DOMAIN, identifier, self.entity_id)
        )
        parts = identifier.split("/")[1:]
        track_list = (
            parts == ["track"]
            or (len(parts) == 2 and parts[0] in {"album", "playlist"})
            or (len(parts) == 3 and parts[0] == "artist" and parts[2] == "tracks")
        )
        if track_list:
            result.can_play = any(child.can_play for child in result.children or [])
        # The source already attaches the global position + GUID, including page 2.
        # Page links and page directories themselves are never playable.
        for child in result.children or []:
            if child.media_content_type in {"album", "playlist"}:
                child.can_play = True
        return result

    async def search(self, query: SearchMediaQuery) -> SearchMedia:
        return await FeiNiuMediaSource(self.runtime.hass).async_search_media(
            MediaSourceItem(self.runtime.hass, DOMAIN, self.runtime.entry.entry_id, self.entity_id),
            query,
        )

    async def items(
        self, media_id: str, *, expand_context: bool = True
    ) -> tuple[list[QueueItem], int]:
        parts = self.identifier(media_id).split("/")[1:]
        position = 0
        selected = None
        if len(parts) >= 4 and parts[-3] == "queue":
            if not parts[-2].isdigit():
                raise ServiceValidationError("Invalid queue position")
            position, selected = int(parts[-2]), parts[-1]
            parts = parts[:-3]
        if len(parts) == 2 and parts[0] == "track":
            rows = [{"guid": parts[1]}]
        elif parts == ["track"]:
            rows = await self.runtime.collection("track", fresh=True)
        elif len(parts) == 2 and parts[0] in {"album", "playlist", "artist"}:
            rows = await self.runtime.related(parts[0], parts[1], fresh=True)
        elif len(parts) == 3 and parts[0] == "artist" and parts[2] == "tracks":
            rows = await self.runtime.related("artist", parts[1], fresh=True)
        else:
            raise ServiceValidationError("Select a track, album, playlist or artist track list")
        guids = [valid_id(row["guid"]) for row in rows]
        if not guids:
            raise ServiceValidationError("This selection has no accessible tracks")
        if position >= len(guids) or (selected is not None and guids[position] != selected):
            raise ServiceValidationError("The music list changed; browse it again")
        if selected is not None and not expand_context:
            # Add/next on a song means one occurrence; its list context only applies
            # when replacing/playing the list from that song.
            guids, position = [selected], 0
        source = f"media-source://{DOMAIN}/{self.runtime.entry.entry_id}/{chr(47).join(parts)}"
        return [QueueItem.create(guid, source) for guid in guids], position
