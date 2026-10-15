from __future__ import annotations

import logging

from PySide6.QtCore import QObject, QTimer

from utils import win32_helpers as win32

log = logging.getLogger(__name__)

try:
    import psutil
except ImportError:
    psutil = None

_CLIENT_WINDOW_TITLE = "Riot Client"
_PLAY_X_FRAC = 0.10
_PLAY_Y_FRAC = 0.72
_ATTEMPTS = 10
_ATTEMPT_DELAY_MS = 2500
_SETTLE_MS = 700


class RiotAutoClicker(QObject):
    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._attempts_left = 0
        self._game_process = ""
        self._timer = QTimer(self)
        self._timer.setInterval(_ATTEMPT_DELAY_MS)
        self._timer.timeout.connect(self._attempt)

    def arm(self, game_process: str | None = None) -> None:
        if not win32.IS_WINDOWS:
            return
        self._game_process = (game_process or "").casefold()
        self._attempts_left = _ATTEMPTS
        self._timer.start()
        log.info("Riot clicker armed (fallback mode, game signal=%s)",
                 self._game_process or "n/a")

    def _game_already_running(self) -> bool:
        if not self._game_process or psutil is None:
            return False
        for proc in psutil.process_iter(["name"]):
            if (proc.info.get("name") or "").casefold() == self._game_process:
                return True
        return False

    def _attempt(self) -> None:
        self._attempts_left -= 1
        if self._attempts_left <= 0:
            self._timer.stop()
            log.info("Riot clicker expired - manual PLAY remains")
            return

        if self._game_already_running():
            self._timer.stop()
            log.info("Riot CLI launch confirmed (%s running) - clicker disarmed",
                     self._game_process)
            return

        hwnd = win32.find_window_by_title(_CLIENT_WINDOW_TITLE)
        if not hwnd:
            return
        win32.focus_window(hwnd)
        width, height = win32.client_size(hwnd)
        if width < 400 or height < 300:
            return
        x = int(width * _PLAY_X_FRAC)
        y = int(height * _PLAY_Y_FRAC)
        win32.post_click(hwnd, x, y)
        QTimer.singleShot(_SETTLE_MS,
                          lambda: win32.post_click(hwnd, x, y))
        log.info("Riot fallback click posted at (%d, %d) in %dx%d client",
                 x, y, width, height)
        self._timer.stop()