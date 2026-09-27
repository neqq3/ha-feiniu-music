"""Read-only lyric results for HA actions; no player lyric-rendering claim."""

import re
from typing import Any

from .client import ProtocolError

_TIME = re.compile(r"\[(\d{1,3}):(\d{1,2})(?:[.:](\d{1,3}))?\]")
_OFFSET = re.compile(r"^\[offset:\s*([+-]?\d+)\s*\]$", re.IGNORECASE)
_PREFIX = re.compile(r"^((?:\[\d{1,3}:\d{1,2}(?:[.:]\d{1,3})?\]\s*)+)(.*)$")


def parse_lyrics(data: dict[str, Any]) -> dict[str, Any]:
    """Return plain text and timed lines for the native selected lyric and offset."""
    rows = data.get("list")
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise ProtocolError("Invalid lyric list")
    available = [
        row for row in rows if isinstance(row.get("content"), str) and row["content"].strip()
    ]
    if not available:
        return {"text": "", "synced_lines": []}
    selected = next(
        (row for row in available if row.get("guid") == data.get("preferred")), available[0]
    )
    content = selected["content"].lstrip("\ufeff").strip()
    if len(content) > 256000:
        raise ProtocolError("Lyric exceeds size limit")
    lines = content.splitlines()
    offset = selected.get("offset")
    if offset is not None and type(offset) is not int:
        raise ProtocolError("Invalid lyric offset")
    embedded = [int(m[1]) for line in lines if (m := _OFFSET.fullmatch(line.strip()))]
    alignment = offset if offset is not None else (embedded[-1] if embedded else 0)
    inline_offset = 0
    synced: list[dict[str, Any]] = []
    for line in lines:
        if match := _OFFSET.fullmatch(line.strip()):
            inline_offset = int(match[1])
            continue
        if block := _PREFIX.match(line.strip()):
            for timestamp in _TIME.finditer(block[1]):
                millis = (
                    int(timestamp[1]) * 60000
                    + int(timestamp[2]) * 1000
                    + int((timestamp[3] or "0").ljust(3, "0"))
                    + inline_offset
                    - alignment
                )
                if millis >= 0:
                    synced.append({"time_ms": millis, "text": block[2]})
    if synced:
        synced.sort(key=lambda line: line["time_ms"])
        return {"text": "\n".join(line["text"] for line in synced), "synced_lines": synced}
    return {"text": content, "synced_lines": []}
