from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1

_DEFAULTS: dict = {
    "version": SCHEMA_VERSION,
    "riot_clicker_enabled": True,
    "splash_min_seconds": 5.0,
    "close_to_tray": True,
    "theme": "violet",
}


class Settings:
    def __init__(self, path: Path | None = None) -> None:
        if path is None:
            from PySide6.QtCore import QStandardPaths
            base = Path(QStandardPaths.writableLocation(
                QStandardPaths.StandardLocation.AppDataLocation))
            base.mkdir(parents=True, exist_ok=True)
            path = base / "settings.json"
        self._path = path
        self._lock = threading.RLock()
        self._data: dict = {}
        self._load()

    def _load(self) -> None:
        try:
            if self._path.is_file():
                self._data = json.loads(
                    self._path.read_text(encoding="utf-8")[:262144])
            else:
                self._data = {}
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("Settings file unreadable (%s) - using defaults", exc)
            self._data = {}
        merged = dict(_DEFAULTS)
        merged.update({k: v for k, v in self._data.items() if k in _DEFAULTS})
        self._data = merged
        self._save()

    def _save(self) -> None:
        try:
            self._path.write_text(
                json.dumps(self._data, indent=2, sort_keys=True), encoding="utf-8")
        except OSError as exc:
            log.error("Settings could not be saved: %s", exc)

    def get(self, key: str, default=None):
        with self._lock:
            return self._data.get(key, _DEFAULTS.get(key, default))

    def set(self, key: str, value) -> None:
        with self._lock:
            self._data[key] = value
            self._save()

    @property
    def riot_clicker_enabled(self) -> bool:
        return bool(self.get("riot_clicker_enabled", True))

    @property
    def splash_min_seconds(self) -> float:
        try:
            return max(0.0, min(15.0, float(self.get("splash_min_seconds", 5.0))))
        except (TypeError, ValueError):
            return 5.0

    @property
    def close_to_tray(self) -> bool:
        return bool(self.get("close_to_tray", True))

    @property
    def theme(self) -> str:
        return str(self.get("theme", "violet"))