from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QStandardPaths
from PySide6.QtGui import QImage, QImageReader

log = logging.getLogger(__name__)

_BG_FILENAME = "background.png"

MAX_BYTES = 25 * 1024 * 1024
MAX_DIM = 8192
MIN_W, MIN_H = 480, 270

_ALLOWED_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp"}
_ALLOWED_FORMATS = {"png", "jpeg", "bmp", "gif", "webp"}


def _sniff_format(head: bytes) -> str | None:
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if head.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if head.startswith(b"BM"):
        return "bmp"
    if head.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    if head.startswith(b"RIFF") and len(head) >= 12 and head[8:12] == b"WEBP":
        return "webp"
    return None


def background_path() -> Path:
    base = Path(QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.AppDataLocation))
    base.mkdir(parents=True, exist_ok=True)
    return base / _BG_FILENAME


class CustomBackgroundManager:
    @staticmethod
    def exists() -> bool:
        return background_path().is_file()

    @staticmethod
    def clear() -> bool:
        path = background_path()
        if path.is_file():
            try:
                path.unlink()
                return True
            except OSError as exc:
                log.warning("Background removal failed: %s", exc)
                return False
        return True

    @staticmethod
    def validate_and_store(source: str) -> tuple[bool, str]:
        path = Path(source)

        if path.suffix.casefold() not in _ALLOWED_SUFFIXES:
            return (False, "Not an image file (allowed: png, jpg, jpeg, "
                           "bmp, gif, webp).")

        try:
            size = path.stat().st_size
        except OSError as exc:
            return (False, f"Cannot read the file: {exc}")
        if size <= 0:
            return (False, "The file is empty.")
        if size > MAX_BYTES:
            return (False, f"File is too large ({size / (1024*1024):.1f} MB). "
                           f"Maximum is {MAX_BYTES / (1024*1024):.0f} MB.")

        try:
            with path.open("rb") as fh:
                head = fh.read(16)
        except OSError as exc:
            return (False, f"Cannot read the file: {exc}")
        sniffed = _sniff_format(head)
        if sniffed is None or sniffed not in _ALLOWED_FORMATS:
            return (False, "This is not a real image file "
                           "(content signature check failed).")

        reader = QImageReader(str(path))
        reader.setDecideFormatFromContent(True)
        reader.setAutoTransform(True)
        raw_format = reader.format()
        fmt = str(raw_format.data(), "ascii", "replace").casefold() \
            if raw_format is not None and not raw_format.isNull() else ""
        if fmt and fmt not in _ALLOWED_FORMATS:
            return (False, "Unsupported image content.")
        probe = reader.size()
        if not probe.isValid():
            return (False, "The file could not be interpreted as an image.")
        pw, ph = probe.width(), probe.height()
        if pw <= 0 or ph <= 0:
            return (False, "The image has invalid dimensions.")
        if pw > MAX_DIM or ph > MAX_DIM:
            return (False, f"Image is too large ({pw}x{ph}). "
                           f"Maximum is {MAX_DIM}x{MAX_DIM} pixels.")
        if pw < MIN_W or ph < MIN_H:
            return (False, f"Image is too small ({pw}x{ph}). "
                           f"Minimum is {MIN_W}x{MIN_H} pixels.")
        image = reader.read()
        if image.isNull():
            return (False, "The image failed to decode "
                           "(corrupt or disguised file).")

        target = background_path()
        if not image.save(str(target), "PNG"):
            return (False, "Could not save the background image.")
        verify = QImage(str(target))
        if verify.isNull():
            try:
                target.unlink()
            except OSError:
                pass
            return (False, "Stored image failed verification - rejected.")
        log.info("Custom background stored: %s (%dx%d)", path.name, pw, ph)
        return (True, f"Background set ({pw}x{ph}).")