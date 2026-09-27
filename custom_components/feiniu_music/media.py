"""Public media identifiers and safe metadata for Home Assistant."""

import re
from dataclasses import dataclass
from typing import Any

from didl_lite import didl_lite
from homeassistant.components.media_player import MediaClass, MediaType
from homeassistant.components.media_player.browse_media import async_process_play_media_url
from homeassistant.components.media_source import BrowseMediaSource, PlayMedia

from .client import ProtocolError, StreamRejectedError
from .const import DOMAIN
from .runtime import FeiNiuRuntime

MIME_TYPES = {
    "flac": "audio/flac",
    "mp3": "audio/mpeg",
    "ogg": "audio/ogg",
    "opus": "audio/ogg",
    "wav": "audio/wav",
    "m4a": "audio/mp4",
    "mp4": "audio/mp4",
    "aac": "audio/aac",
}
MEDIA_CLASSES = {
    "track": MediaClass.TRACK,
    "album": MediaClass.ALBUM,
    "artist": MediaClass.ARTIST,
    "playlist": MediaClass.PLAYLIST,
}


@dataclass(slots=True)
class FeiNiuPlayMedia(PlayMedia):
    """Use the same DIDL extension consumed by HA's built-in DLNA player/source."""

    didl_metadata: didl_lite.DidlObject


def play_media(runtime: FeiNiuRuntime, row: dict[str, Any], url: str, mime: str) -> FeiNiuPlayMedia:
    """Supply actual song metadata to DLNA without a second player or HA core patch."""
    guid = valid_id(row["guid"])
    artists = " / ".join(
        artist["name"]
        for artist in row.get("artists") or []
        if isinstance(artist, dict) and isinstance(artist.get("name"), str)
    )
    album = row.get("album") or {}
    cover = thumbnail(runtime, "track", row, for_player=True)
    metadata = didl_lite.MusicTrack(
        id=f"{runtime.entry.entry_id}/track/{guid}",
        parent_id=f"{runtime.entry.entry_id}/track",
        restricted="1",
        title=row.get("title") or "Untitled track",
        artist=artists or None,
        creator=artists or None,
        album=album.get("name") if isinstance(album, dict) else None,
        album_art_uri=async_process_play_media_url(runtime.hass, cover) if cover else None,
        resources=[didl_lite.Resource(url, f"http-get:*:{mime}:*")],
    )
    return FeiNiuPlayMedia(url, mime, didl_metadata=metadata)


def valid_id(value: str) -> str:
    """Identifiers are opaque native IDs, never filesystem paths or remote URLs."""
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}", value):
        raise ProtocolError("Invalid media identifier")
    return value


def mime_type(row: dict[str, Any]) -> str:
    """Describe original audio; no PCM or universal codec support is implied."""
    if row.get("isCue"):
        raise StreamRejectedError("CUE split-track playback is not supported")
    spec = row.get("audioSpec") or {}
    for key in ("container", "format", "codec"):
        value = str(spec.get(key, "")).lower()
        if value in MIME_TYPES:
            return MIME_TYPES[value]
    raise StreamRejectedError("Audio format is not supported by this integration")


def thumbnail(
    runtime: FeiNiuRuntime, kind: str, row: dict[str, Any], *, for_player: bool = False
) -> str | None:
    """Sign an exact owner/cover path without exposing the native session or URL."""
    cover = row.get("coverId")
    if not cover and isinstance(row.get("album"), dict):
        cover = row["album"].get("coverId")
    if not isinstance(cover, str) or not cover:
        return None
    guid, cover = valid_id(row["guid"]), valid_id(cover)
    if for_player:
        # MA3 truncates albumArtURI at 256 characters, cutting off HA's long signature.
        token = runtime.grant_artwork(kind, guid, cover)
        return f"/api/{DOMAIN}/{runtime.entry.entry_id}/artwork?token={token}"
    path = f"/api/{DOMAIN}/{runtime.entry.entry_id}/{runtime.scope}/image/{kind}/{guid}/{cover}"
    return runtime.thumbnail_path(path)


def media_item(runtime: FeiNiuRuntime, kind: str, row: dict[str, Any]) -> BrowseMediaSource:
    """Expose an allowlist of display fields; never raw audioSpec or auth data."""
    guid = valid_id(row.get("guid", ""))
    title = row.get("title" if kind == "track" else "name")
    title = title if isinstance(title, str) and title else f"Untitled {kind}"
    playable = kind == "track"
    content_type: str = kind
    if playable:
        try:
            content_type = mime_type(row)
        except StreamRejectedError:
            # Lists may omit audioSpec. Resolve validates the metadata before playback.
            playable = not bool(row.get("isCue"))
            content_type = MediaType.MUSIC
    return BrowseMediaSource(
        domain=DOMAIN,
        identifier=f"{runtime.entry.entry_id}/{kind}/{guid}",
        media_class=MEDIA_CLASSES[kind],
        media_content_type=content_type,
        title=title,
        can_play=playable,
        can_expand=kind != "track",
        thumbnail=thumbnail(runtime, kind, row),
    )


def folder(
    identifier: str | None, title: str, children: list[BrowseMediaSource], *, search: bool = False
) -> BrowseMediaSource:
    """Create a browsable folder; albums/playlists are not advertised as queue players."""
    return BrowseMediaSource(
        domain=DOMAIN,
        identifier=identifier,
        media_class=MediaClass.DIRECTORY,
        media_content_type=MediaType.MUSIC,
        title=title,
        can_play=False,
        can_expand=True,
        can_search=search,
        children=children,
    )
