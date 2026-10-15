from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

from PySide6.QtCore import QObject, QTimer, Signal

try:
    import psutil
except ImportError:
    psutil = None

log = logging.getLogger(__name__)


@dataclass
class _Watch:
    game_id: int
    title: str
    name: str | None
    pid: int | None
    started_utc: datetime | None = None
    started_mono: float | None = None
    deadline_mono: float = 0.0


class ProcessTracker(QObject):
    game_started = Signal(int, str)
    game_stopped = Signal(int, str, int)
    game_force_stopped = Signal(int, str, int)

    POLL_INTERVAL_MS = 2000
    LAUNCH_GRACE_S = 180
    SLEEP_GAP_S = 30

    def __init__(self, db, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._db = db
        self._watches: dict[int, _Watch] = {}
        self._last_poll_mono: float = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(self.POLL_INTERVAL_MS)
        self._timer.timeout.connect(self._poll)

    def on_game_start(self, callback: Callable[[int, str], None]) -> None:
        self.game_started.connect(callback)

    def on_game_stop(self, callback: Callable[[int, str, int], None]) -> None:
        self.game_stopped.connect(callback)

    def start(self) -> None:
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()
        for watch in [w for w in self._watches.values() if w.started_utc is not None]:
            self._finalize(watch)
        self._watches.clear()

    def watch(self, game_id: int, title: str,
              process_name: str | None = None, pid: int | None = None) -> None:
        if psutil is None:
            log.warning("psutil not installed - session tracking disabled")
            return
        existing = self._watches.get(game_id)
        if existing is not None and existing.started_utc is not None:
            log.info("Re-arming watch for '%s' - finalizing the open session", title)
            self._finalize(existing)
        now = time.monotonic()
        self._watches[game_id] = _Watch(
            game_id=game_id, title=title, name=process_name, pid=pid,
            deadline_mono=now + self.LAUNCH_GRACE_S,
        )

    def is_running(self, game_id: int) -> bool:
        watch = self._watches.get(game_id)
        return watch is not None and watch.started_utc is not None

    def force_stop(self, game_id: int, title: str) -> bool:
        if psutil is None:
            return False
        watch = self._watches.get(game_id)
        if watch is None or watch.pid is None:
            return False
        try:
            parent = psutil.Process(watch.pid)
            children = parent.children(recursive=True)
            for child in children:
                child.kill()
            parent.kill()
            psutil.wait_procs([parent, *children], timeout=5)
            return True
        except (psutil.Error, OSError) as exc:
            log.warning("Force-stop failed for '%s': %s", title, exc)
            return False

    def _poll(self) -> None:
        now_mono = time.monotonic()

        if self._last_poll_mono:
            gap = now_mono - self._last_poll_mono - (self.POLL_INTERVAL_MS / 1000)
            if gap > self.SLEEP_GAP_S:
                shift = timedelta(seconds=gap)
                for watch in self._watches.values():
                    if watch.started_utc is not None:
                        watch.started_utc += shift
                log.info("System sleep detected (%.0f s) - open sessions adjusted", gap)
        self._last_poll_mono = now_mono

        if not self._watches:
            return
        for game_id, watch in list(self._watches.items()):
            if self._is_running(watch):
                if watch.started_utc is None:
                    watch.started_utc = datetime.now(timezone.utc)
                    watch.started_mono = time.monotonic()
                    self.game_started.emit(game_id, watch.title)
            else:
                if watch.started_utc is not None:
                    del self._watches[game_id]
                    self._finalize(watch)
                elif now_mono > watch.deadline_mono:
                    del self._watches[game_id]
                    log.debug("Launch never materialized for '%s' (grace expired)",
                              watch.title)

    def _is_running(self, watch: _Watch) -> bool:
        assert psutil is not None
        if watch.pid is not None:
            try:
                proc = psutil.Process(watch.pid)
                if proc.is_running() and (
                        not watch.name
                        or (proc.name() or "").casefold() == watch.name.casefold()):
                    return True
            except psutil.Error:
                pass
            watch.pid = None
        if watch.name:
            try:
                for proc in psutil.process_iter(["pid", "name"]):
                    if (proc.info.get("name") or "").casefold() == watch.name.casefold():
                        watch.pid = proc.info["pid"]
                        return True
            except psutil.Error:
                return False
        return False

    def _finalize(self, watch: _Watch) -> None:
        assert watch.started_utc is not None
        ended_utc = datetime.now(timezone.utc)
        anchor = watch.started_mono if watch.started_mono is not None else time.monotonic()
        duration = max(0, int(time.monotonic() - anchor))
        self._db.record_session(watch.game_id, watch.started_utc, ended_utc, duration)
        self.game_stopped.emit(watch.game_id, watch.title, duration)