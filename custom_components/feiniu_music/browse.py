"""Small native browse values, without HA sessions or playback authorization."""

from dataclasses import dataclass
from typing import Any

from .client import ProtocolError
from .const import PAGE_SIZE


@dataclass
class BrowsePage:
    """An independently copied page; total counts native rows, not page links."""

    rows: list[dict[str, Any]]
    total: int
    offset: int = 0


def compact_row(row: dict[str, Any]) -> dict[str, Any]:
    """Retain display/playability fields, not paths, tags or recursive library objects."""
    value = {
        key: row[key]
        for key in ("guid", "title", "name", "coverId", "accessStatus", "isCue", "duration")
        if key in row and isinstance(row[key], str | int | float | bool | type(None))
    }
    if isinstance(spec := row.get("audioSpec"), dict):
        value["audioSpec"] = {
            key: spec[key]
            for key in ("format", "container", "codec")
            if isinstance(spec.get(key), str)
        }
    for key in ("album", "artists"):
        nested = row.get(key)
        if (key == "album" and isinstance(nested, dict)) or (
            key == "artists" and isinstance(nested, list)
        ):
            refs = [nested] if key == "album" else nested
            clean = [
                {k: item[k] for k in ("guid", "name", "coverId") if isinstance(item.get(k), str)}
                for item in refs
                if isinstance(item, dict)
            ]
            value[key] = (clean[0] if clean else {}) if key == "album" else clean
    return value


def page_rows(data: dict[str, Any], *, playlist: bool = False) -> tuple[list[dict], int, int]:
    """Validate raw pagination before filtering; status meanings are endpoint-specific."""
    rows, total = data.get("list"), data.get("total")
    if not isinstance(rows, list) or type(total) is not int or total < 0 or len(rows) > PAGE_SIZE:
        raise ProtocolError("Invalid native pagination")
    seen: set[str] = set()
    result = []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("guid"), str) or not row["guid"]:
            raise ProtocolError("Missing native item ID")
        if not playlist and row["guid"] in seen:
            raise ProtocolError("Repeated native item ID")
        seen.add(row["guid"])
        if playlist:
            # Metadata's 3 is not verified for playlist rows. Never hide an
            # unknown/missing/bool status by presenting an apparently empty list.
            status = row.get("accessStatus")
            if type(status) is not int or status not in {0, 2}:
                raise ProtocolError("Invalid playlist track access status")
            if status == 2:
                continue
        result.append(compact_row(row))
    return result, total, len(rows)
