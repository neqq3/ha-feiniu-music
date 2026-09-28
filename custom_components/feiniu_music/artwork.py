"""Bounded image resources, never an authority for access to a music item."""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import logging
import os
import struct
import threading
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from time import time
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from PIL import Image, ImageOps, UnidentifiedImageError

from .client import ProtocolError, classify_media

_LOGGER = logging.getLogger(__name__)
RESOURCE_TTL = 60 * 60
MAX_DISK_BYTES = 128 * 1024 * 1024
MAX_DISK_FILES = 2048
MAX_MEMORY_BYTES = 16 * 1024 * 1024
MAX_MEMORY_FILES = 512
MAX_RESOURCE_BYTES = 8 * 1024 * 1024
SIZES = {128, 256, 512}
_HEADER = struct.Struct("!8sd32s")
_MAGIC = b"FNIMAGE1"


@dataclass(frozen=True, slots=True)
class CachedImage:
    """Encoded pixels and a precomputed validator, without account credentials."""

    data: bytes
    created: float
    etag: str
    content_type: str

    @classmethod
    def build(cls, data: bytes, created: float | None = None) -> CachedImage:
        kind = classify_media(data)
        if kind not in {"jpeg", "png", "webp"} or len(data) > MAX_RESOURCE_BYTES:
            raise ProtocolError("Artwork is not a bounded supported image")
        return cls(
            data,
            time() if created is None else created,
            hashlib.sha256(data).hexdigest(),
            {"jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}[kind],
        )


def resize_image(source: CachedImage, size: int) -> CachedImage:
    """Run Pillow off the event loop; preserve aspect ratio and actual transparency."""
    if size not in SIZES:
        raise ValueError("Unsupported thumbnail size")
    try:
        with Image.open(io.BytesIO(source.data)) as original:
            if original.width * original.height > 16_000_000:
                raise ProtocolError("Artwork pixel limit exceeded")
            image = ImageOps.exif_transpose(original)
            image.thumbnail((size, size), Image.Resampling.LANCZOS)
            image = image.convert(
                "RGBA" if "A" in image.getbands() or "transparency" in image.info else "RGB"
            )
            result = io.BytesIO()
            image.save(result, format="WEBP", quality=82, method=3)
            return CachedImage.build(result.getvalue(), source.created)
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as err:
        raise ProtocolError("Artwork could not be decoded") from err


class ArtworkCache:
    """One entry/account's LRU memory and atomic persistent cache (128 MiB on disk).

    Files contain a timestamp, checksum and encoded image only. Disk operations
    are serialized in the executor, not on the event loop. Cache I/O failure is
    best-effort; it must not prevent a valid native response being displayed.
    """

    def __init__(self, hass: HomeAssistant, identity: str) -> None:
        self.hass = hass
        self.path = Path(
            hass.config.path(
                ".storage", "feiniu_music_artwork", hashlib.sha256(identity.encode()).hexdigest()
            )
        )
        self._memory: OrderedDict[str, CachedImage] = OrderedDict()
        self._bytes = 0
        self._files: OrderedDict[str, tuple[float, int]] | None = None
        self._disk_bytes = 0
        self._lock = threading.Lock()
        self._warned = False

    @classmethod
    def for_entry(cls, hass: HomeAssistant, entry: ConfigEntry) -> ArtworkCache:
        return cls(
            hass, json.dumps([entry.entry_id, entry.data.get("url"), entry.data.get("account_id")])
        )

    async def delete(self) -> None:
        """Remove only this account's own cache files when its entry is removed."""
        self.clear_memory()
        await self.executor(self._delete)

    def _delete(self) -> None:
        with self._lock:
            try:
                self._initialize()
                assert self._files is not None
                for key in list(self._files):
                    self._drop(key)
                self.path.rmdir()
            except OSError as err:
                self._io_error(err)

    @staticmethod
    def key(cover: str, size: int = 0) -> str:
        return hashlib.sha256(f"v1:{size}:{cover}".encode()).hexdigest()

    async def executor(self, target: Any, *args: Any) -> Any:
        """Let an already-started bounded disk/resize job finish even on unload."""
        job = self.hass.async_add_executor_job(target, *args)
        try:
            return await asyncio.shield(job)
        except asyncio.CancelledError:
            await job
            raise

    async def get(self, key: str) -> CachedImage | None:
        if value := self._memory.get(key):
            if 0 <= time() - value.created < RESOURCE_TTL:
                self._memory.move_to_end(key)
                return value
            self._bytes -= len(self._memory.pop(key).data)
        value = await self.executor(self._read, key)
        if value:
            self._remember(key, value)
        return value

    async def put(self, key: str, value: CachedImage) -> None:
        self._remember(key, value)
        await self.executor(self._write, key, value)

    def clear_memory(self) -> None:
        self._memory.clear()
        self._bytes = 0

    def _remember(self, key: str, value: CachedImage) -> None:
        if old := self._memory.pop(key, None):
            self._bytes -= len(old.data)
        if len(value.data) > MAX_MEMORY_BYTES:
            return
        while self._memory and (
            len(self._memory) >= MAX_MEMORY_FILES
            or self._bytes + len(value.data) > MAX_MEMORY_BYTES
        ):
            self._bytes -= len(self._memory.popitem(last=False)[1].data)
        self._memory[key] = value
        self._bytes += len(value.data)

    def _initialize(self) -> None:
        if self._files is not None:
            return
        if self.path.is_symlink():
            raise OSError("Artwork cache directory must not be a symlink")
        self.path.mkdir(parents=True, exist_ok=True, mode=0o700)
        files = []
        for path in self.path.iterdir():
            if len(path.stem) != 64 or any(c not in "0123456789abcdef" for c in path.stem):
                continue
            if path.suffix == ".tmp":
                path.unlink(missing_ok=True)
            elif path.suffix == ".cache" and not path.is_symlink():
                stat = path.stat()
                if (
                    not 0 <= time() - stat.st_mtime < RESOURCE_TTL
                    or stat.st_size > MAX_RESOURCE_BYTES + _HEADER.size
                ):
                    path.unlink(missing_ok=True)
                else:
                    files.append((path.stem, (stat.st_mtime, stat.st_size)))
        self._files = OrderedDict(sorted(files, key=lambda item: item[1][0]))
        self._disk_bytes = sum(v[1] for v in self._files.values())
        self._trim()

    def _drop(self, key: str) -> None:
        assert self._files is not None
        (self.path / (key + ".cache")).unlink(missing_ok=True)
        if record := self._files.pop(key, None):
            self._disk_bytes -= record[1]

    def _trim(self) -> None:
        assert self._files is not None
        while self._files and (
            self._disk_bytes > MAX_DISK_BYTES or len(self._files) > MAX_DISK_FILES
        ):
            self._drop(next(iter(self._files)))

    def _io_error(self, error: OSError) -> None:
        if not self._warned:
            _LOGGER.warning(
                "Artwork disk cache unavailable (%s); using memory", type(error).__name__
            )
            self._warned = True

    def _read(self, key: str) -> CachedImage | None:
        with self._lock:
            try:
                self._initialize()
                assert self._files is not None
                if key not in self._files:
                    return None
                path = self.path / (key + ".cache")
                with path.open("rb") as handle:
                    raw = handle.read(MAX_RESOURCE_BYTES + _HEADER.size + 1)
                try:
                    magic, created, digest = _HEADER.unpack(raw[: _HEADER.size])
                    value = CachedImage.build(raw[_HEADER.size :], created)
                    valid = (
                        magic == _MAGIC
                        and digest.hex() == value.etag
                        and 0 <= time() - created < RESOURCE_TTL
                    )
                except struct.error, ProtocolError:
                    valid = False
                if not valid:
                    self._drop(key)
                    return None
                self._files.move_to_end(key)
                return value
            except OSError as err:
                self._io_error(err)
                return None

    def _write(self, key: str, value: CachedImage) -> None:
        with self._lock:
            temporary = self.path / (key + ".tmp")
            try:
                self._initialize()
                assert self._files is not None
                if len(value.data) + _HEADER.size > MAX_DISK_BYTES:
                    return
                with temporary.open("wb") as handle:
                    handle.write(_HEADER.pack(_MAGIC, value.created, bytes.fromhex(value.etag)))
                    handle.write(value.data)
                target = self.path / (key + ".cache")
                os.replace(temporary, target)
                os.utime(target, (value.created, value.created))
                if old := self._files.pop(key, None):
                    self._disk_bytes -= old[1]
                length = len(value.data) + _HEADER.size
                self._files[key] = (value.created, length)
                self._disk_bytes += length
                self._trim()
            except OSError as err:
                self._io_error(err)
            finally:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass
