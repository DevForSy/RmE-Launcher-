from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from ui.logo import app_icon

log = logging.getLogger(__name__)


class TrayIcon(QObject):
    show_main = Signal()
    launch_favorite = Signal(int)
    quit_requested = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._tray = QSystemTrayIcon(self)
        self._tray.setIcon(app_icon())
        self._tray.setToolTip("RmE Launcher")
        self._tray.activated.connect(self._on_activated)

        self._menu = QMenu()
        self._show_action = QAction("Show RmE", self._menu)
        self._show_action.triggered.connect(self.show_main.emit)
        self._menu.addAction(self._show_action)
        self._menu.addSeparator()
        self._fav_header = QAction("Favorites", self._menu)
        self._fav_header.setEnabled(False)
        self._menu.addAction(self._fav_header)
        self._menu.addSeparator()
        self._quit_action = QAction("Quit", self._menu)
        self._quit_action.triggered.connect(self.quit_requested.emit)
        self._menu.addAction(self._quit_action)
        self._tray.setContextMenu(self._menu)
        self._extra_actions: list[QAction] = []

    def _on_activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.DoubleClick,
                      QSystemTrayIcon.ActivationReason.Trigger):
            self.show_main.emit()

    def show(self) -> None:
        self._tray.show()

    def hide(self) -> None:
        self._tray.hide()

    def show_message(self, title: str, body: str) -> None:
        self._tray.showMessage(title, body,
                               QSystemTrayIcon.MessageIcon.Information, 2500)

    def set_favorites(self, favorites: list[tuple[int, str]]) -> None:
        for action in self._extra_actions:
            self._menu.removeAction(action)
            action.setParent(None)
        self._extra_actions.clear()
        self._menu.removeAction(self._fav_header)
        self._menu.insertAction(self._quit_action, self._fav_header)
        if not favorites:
            empty = QAction("(right-click a game to pin it)", self._menu)
            empty.setEnabled(False)
            self._menu.insertAction(self._quit_action, empty)
            self._extra_actions.append(empty)
            return
        for game_id, title in favorites[:12]:
            action = QAction(title, self._menu)
            action.triggered.connect(
                lambda _checked=False, gid=game_id: self.launch_favorite.emit(gid))
            self._menu.insertAction(self._quit_action, action)
            self._extra_actions.append(action)
        if len(favorites) > 12:
            more = QAction(f"\u2026 and {len(favorites) - 12} more", self._menu)
            more.setEnabled(False)
            self._menu.insertAction(self._quit_action, more)
            self._extra_actions.append(more)