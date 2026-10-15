from __future__ import annotations

import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, QTimer

try:
    import psutil
except ImportError:
    psutil = None

log = logging.getLogger(__name__)

_CLIENTS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "ea": (
        ("eadesktop.exe", "origin.exe"),
        (r"C:\Program Files\Electronic Arts\EA Desktop\EA Desktop\EADesktop.exe",
         r"C:\Program Files (x86)\Origin\Origin.exe"),
    ),
    "battlenet": (
        ("battle.net.exe",),
        (r"C:\Program Files (x86)\Battle.net\Battle.net.exe",),
    ),
    "rockstar": (
        ("rockstarservice.exe", "launcherpatcher.exe"),
        (r"C:\Program Files\Rockstar Games\Launcher\LauncherPatcher.exe",),
    ),
}

_POLL_MS = 500
_MAX_WAIT_S = 45
_SETTLE_S = 6


def _running(process_names: tuple[str, ...]) -> bool:
    if psutil is None:
        return False
    wanted = {n.casefold() for n in process_names}
    try:
        for proc in psutil.process_iter(["name"]):
            if (proc.info.get("name") or "").casefold() in wanted:
                return True
    except psutil.Error:
        return False
    return False


class ClientGuard(QObject):
    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._timer = QTimer(self)
        self._timer.setInterval(_POLL_MS)
        self._timer.timeout.connect(self._poll)
        self._source = ""
        self._deadline = 0.0
        self._settle_at = 0.0
        self._start_game: Callable[[], None] | None = None
        self._on_log: Callable[[str], None] | None = None

    def launch_with_client(self, source: str,
                           start_game: Callable[[], None],
                           on_log: Callable[[str], None]) -> None:
        spec = _CLIENTS.get(source)
        if spec is None or psutil is None:
            start_game()
            return
        process_names, exe_candidates = spec
        if _running(process_names):
            on_log(f"{source}: client already running - launching game")
            start_game()
            return
        client_exe = next((Path(p) for p in exe_candidates if Path(p).is_file()), None)
        if client_exe is None:
            on_log(f"{source}: client not installed - launching game directly")
            start_game()
            return
        try:
            flags = subprocess.DETACHED_PROCESS if os.name == "nt" else 0
            subprocess.Popen([str(client_exe)], creationflags=flags)
        except OSError as exc:
            on_log(f"{source}: client failed to start ({exc}) - trying game anyway")
            start_game()
            return
        on_log(f"{source}: starting client ({client_exe.name}) before the game\u2026")
        self._source = source
        self._start_game = start_game
        self._on_log = on_log
        self._deadline = time.monotonic() + _MAX_WAIT_S
        self._settle_at = 0.0
        self._timer.start()

    def _poll(self) -> None:
        if not self._source or self._start_game is None:
            self._timer.stop()
            return
        process_names = _CLIENTS[self._source][0]
        now = time.monotonic()
        if now > self._deadline:
            self._on_log(f"{self._source}: client wait timeout - launching game anyway")
            self._finish()
            return
        if not _running(process_names):
            return
        if self._settle_at == 0.0:
            self._settle_at = now + _SETTLE_S
            self._on_log(f"{self._source}: client is up - settling before game")
            return
        if now >= self._settle_at:
            self._on_log(f"{self._source}: launching game")
            self._finish()

    def _finish(self) -> None:
        self._timer.stop()
        callback = self._start_game
        self._start_game = None
        self._source = ""
        if callback:
            callback()