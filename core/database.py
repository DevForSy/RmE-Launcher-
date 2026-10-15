from __future__ import annotations

import json
import logging
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import QStandardPaths

from parsers.base import GameEntry

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS games (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source          TEXT    NOT NULL,
    platform_id     TEXT    NOT NULL,
    title           TEXT    NOT NULL,
    install_path    TEXT,
    executable_path TEXT,
    launch_uri      TEXT,
    size_on_disk    INTEGER,
    state_flags     INTEGER,
    is_installed    INTEGER NOT NULL DEFAULT 1,
    cover_url       TEXT,
    hero_url        TEXT,
    total_playtime  INTEGER NOT NULL DEFAULT 0,
    last_played     TEXT,
    is_favorite     INTEGER NOT NULL DEFAULT 0,
    extra_json      TEXT,
    added_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(source, platform_id)
);
CREATE INDEX IF NOT EXISTS idx_games_source ON games(source);
CREATE INDEX IF NOT EXISTS idx_games_title  ON games(title);

CREATE TABLE IF NOT EXISTS play_sessions (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id          INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
    started_at       TEXT NOT NULL,
    ended_at         TEXT,
    duration_seconds INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_sessions_game ON play_sessions(game_id);

CREATE TABLE IF NOT EXISTS tags (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS game_tags (
    game_id INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
    tag_id  INTEGER NOT NULL REFERENCES tags(id)  ON DELETE CASCADE,
    PRIMARY KEY (game_id, tag_id)
);
"""


def _newer_iso(current: str | None, candidate: str) -> str:
    def parse(value: str | None):
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None

    a, b = parse(current), parse(candidate)
    if a is None:
        return candidate
    if b is None:
        return current or candidate
    return candidate if b > a else current


class Database:
    def __init__(self, path: str | Path) -> None:
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA journal_mode = WAL")
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._migrate()

    @classmethod
    def default(cls) -> "Database":
        base = Path(QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.AppDataLocation))
        base.mkdir(parents=True, exist_ok=True)
        return cls(base / "rme.db")

    def _migrate(self) -> None:
        try:
            cols = self._conn.execute("PRAGMA table_info(games)").fetchall()
            names = {r["name"] for r in cols}
            if "is_favorite" not in names:
                self._conn.execute(
                    "ALTER TABLE games ADD COLUMN is_favorite INTEGER NOT NULL DEFAULT 0")
                self._conn.commit()
                log.info("Migrated games table: added is_favorite")
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_games_fav ON games(is_favorite)")
            self._conn.commit()
        except sqlite3.Error:
            log.exception("Migration failed")

    def upsert_game(self, entry: GameEntry) -> int:
        query = """
        INSERT INTO games (source, platform_id, title, install_path, executable_path,
                           launch_uri, size_on_disk, state_flags, is_installed,
                           cover_url, hero_url, extra_json)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(source, platform_id) DO UPDATE SET
            title=excluded.title, install_path=excluded.install_path,
            executable_path=excluded.executable_path, launch_uri=excluded.launch_uri,
            size_on_disk=excluded.size_on_disk, state_flags=excluded.state_flags,
            is_installed=excluded.is_installed, cover_url=excluded.cover_url,
            hero_url=excluded.hero_url, extra_json=excluded.extra_json
        """
        installed = 1 if (entry.state_flags is None or entry.state_flags & 4) else 0
        params = (
            entry.source, entry.platform_id, entry.title,
            str(entry.install_path) if entry.install_path else None,
            str(entry.executable_path) if entry.executable_path else None,
            entry.launch_uri, entry.size_on_disk, entry.state_flags,
            installed,
            entry.cover_urls[0] if entry.cover_urls else None,
            entry.hero_urls[0] if entry.hero_urls else None,
            json.dumps(entry.extra, default=str),
        )
        with self._lock:
            self._conn.execute(query, params)
            self._conn.commit()
            row = self._conn.execute(
                "SELECT id FROM games WHERE source=? AND platform_id=?",
                (entry.source, entry.platform_id),
            ).fetchone()
            return int(row["id"])

    def get_game(self, game_id: int) -> dict | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM games WHERE id=?",
                                     (game_id,)).fetchone()
        return dict(row) if row else None

    def games_by_source(self, source: str) -> list[dict]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM games WHERE source=?",
                                      (source,)).fetchall()
        return [dict(r) for r in rows]

    def set_favorite(self, game_id: int, favorite: bool) -> None:
        with self._lock:
            self._conn.execute("UPDATE games SET is_favorite=? WHERE id=?",
                               (1 if favorite else 0, game_id))
            self._conn.commit()

    def favorites(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, title, source FROM games WHERE is_favorite=1 "
                "ORDER BY title COLLATE NOCASE").fetchall()
        return [dict(r) for r in rows]

    def count_by_source(self) -> dict[str, int]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT source, COUNT(*) AS n FROM games GROUP BY source"
            ).fetchall()
        return {r["source"]: int(r["n"]) for r in rows}

    def purge_source(self, source: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM games WHERE source=?", (source,))
            self._conn.commit()

    def purge_stale_minecraft(self) -> None:
        with self._lock:
            self._conn.execute(
                "DELETE FROM games WHERE source='minecraft' "
                "AND platform_id != 'official-launcher'")
            self._conn.commit()

    def delete_game(self, game_id: int) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM games WHERE id=?", (game_id,))
            self._conn.commit()

    def import_steam_stats(self, stats: dict[str, tuple[int, int]]) -> int:
        if not stats:
            return 0
        updated = 0
        with self._lock:
            try:
                rows = self._conn.execute(
                    "SELECT id, platform_id, total_playtime, last_played "
                    "FROM games WHERE source='steam'").fetchall()
                by_pid = {r["platform_id"]: r for r in rows}
                for appid, (minutes, last_epoch) in stats.items():
                    row = by_pid.get(appid)
                    if row is None:
                        continue
                    current_total = int(row["total_playtime"] or 0)
                    new_total = max(current_total, minutes * 60)
                    current_last = row["last_played"]
                    new_last = current_last
                    if last_epoch > 0:
                        imported_iso = datetime.fromtimestamp(
                            last_epoch, tz=timezone.utc).isoformat()
                        new_last = _newer_iso(current_last, imported_iso)
                    if new_total != current_total or new_last != current_last:
                        self._conn.execute(
                            "UPDATE games SET total_playtime=?, last_played=? WHERE id=?",
                            (new_total, new_last, row["id"]))
                        updated += 1
                self._conn.commit()
            except sqlite3.Error:
                self._conn.rollback()
                updated = 0
        return updated

    def add_manual_game(self, title: str, exe_path: str, source: str = "manual") -> int:
        p = Path(exe_path)
        if p.suffix.casefold() != ".exe" or not p.is_file():
            raise ValueError("executable must be an existing .exe file")
        try:
            if p.stat().st_size <= 0:
                raise ValueError("executable file is empty")
        except OSError as exc:
            raise ValueError(f"cannot stat executable: {exc}") from exc
        entry = GameEntry(
            source=source,
            platform_id=str(p).casefold(),
            title=title,
            install_path=p.parent,
            executable_path=p,
            state_flags=4,
        )
        return self.upsert_game(entry)

    def record_session(self, game_id: int, started: datetime,
                       ended: datetime, duration_s: int) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO play_sessions (game_id, started_at, ended_at, duration_seconds) "
                "VALUES (?,?,?,?)",
                (game_id, started.isoformat(), ended.isoformat(), duration_s),
            )
            self._conn.execute(
                "UPDATE games SET total_playtime = total_playtime + ?, last_played = ? WHERE id=?",
                (duration_s, ended.isoformat(), game_id),
            )
            self._conn.commit()

    def touch_last_played(self, game_id: int, when: datetime | None = None) -> None:
        when = when or datetime.now(timezone.utc)
        with self._lock:
            self._conn.execute("UPDATE games SET last_played=? WHERE id=?",
                               (when.isoformat(), game_id))
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()