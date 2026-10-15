from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import (QObject, QPoint, QPropertyAnimation, QEasingCurve,
                            QSize, Qt, QThread, QTimer, QUrl, QVariantAnimation,
                            Signal, Slot)
from PySide6.QtGui import (QAction, QColor, QCursor, QDesktopServices, QIcon,
                           QKeySequence, QLinearGradient, QPainter, QPainterPath,
                           QPen, QPixmap, QShortcut)
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QFileDialog,
                               QGraphicsOpacityEffect, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem,
                               QMainWindow, QMenu, QMessageBox, QPushButton,
                               QFrame, QVBoxLayout, QWidget)

from core.client_guard import ClientGuard
from core.database import Database
from core.discord_rpc import DiscordRPC
from core.playtime_import import import_steam_playtime
from core.riot_clicker import RiotAutoClicker
from core.process_tracker import ProcessTracker
from core.settings import Settings
from core.tray import TrayIcon
from core.updater import UpdateChecker, APP_VERSION
from parsers.base import GameEntry, create_parsers
from ui import icons, styles
from ui.background_manager import CustomBackgroundManager
from ui.components.game_card import GameCard
from ui.logo import logo_pixmap
from ui.settings_dialog import SettingsDialog
from utils import win32_helpers as win32

log = logging.getLogger(__name__)

_ALLOWED_URI_SCHEMES = {"steam", "com.epicgames.launcher", "uplay"}
_CLIENT_BACKED_SOURCES = {"ea", "battlenet", "rockstar"}

_ROLE_LAST = int(Qt.ItemDataRole.UserRole)
_ROLE_PLAYED = int(Qt.ItemDataRole.UserRole) + 1
_ROLE_TITLE = int(Qt.ItemDataRole.UserRole) + 2
_ROLE_FAV = int(Qt.ItemDataRole.UserRole) + 3


def _fmt_playtime(seconds: int) -> str:
    hours, rem = divmod(int(seconds), 3600)
    minutes = rem // 60
    return f"{hours}h {minutes:02d}m" if hours else f"{minutes}m"


def _fmt_date(iso: str | None) -> str:
    if not iso:
        return "never"
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone() \
            .strftime("%d %b %Y · %H:%M")
    except ValueError:
        return iso


class _SortableItem(QListWidgetItem):
    sort_mode = "recent"

    def __lt__(self, other) -> bool:
        fa = int(self.data(_ROLE_FAV) or 0)
        fb = int(other.data(_ROLE_FAV) or 0)
        if fa != fb:
            return fa > fb
        mode = _SortableItem.sort_mode
        if mode == "played":
            try:
                a = int(self.data(_ROLE_PLAYED) or 0)
            except (TypeError, ValueError):
                a = 0
            try:
                b = int(other.data(_ROLE_PLAYED) or 0)
            except (TypeError, ValueError):
                b = 0
            return a > b
        if mode == "recent":
            a = str(self.data(_ROLE_LAST) or "")
            b = str(other.data(_ROLE_LAST) or "")
            if a == b:
                return False
            if not a:
                return False
            if not b:
                return True
            return a > b
        a = str(self.data(_ROLE_TITLE) or "")
        b = str(other.data(_ROLE_TITLE) or "")
        return a < b


class _Spinner(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(40, 40)
        self._angle = 0.0
        self._anim = QVariantAnimation(self)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(360.0)
        self._anim.setDuration(1000)
        self._anim.setLoopCount(-1)
        self._anim.valueChanged.connect(self._on_frame)
        self._anim.start()

    def _on_frame(self, value) -> None:
        self._angle = float(value)
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor("#F5F5F7"), 2.4)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        rect = self.rect().adjusted(6, 6, -6, -6)
        painter.drawArc(rect, int(-self._angle * 16), 90 * 16)


class _SplashScreen(QFrame):
    splash_done = Signal()

    def __init__(self) -> None:
        super().__init__(None,
                         Qt.WindowType.SplashScreen | Qt.WindowType.FramelessWindowHint |
                         Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedSize(440, 300)

        self._fx = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._fx)
        self._fx.setOpacity(0.0)
        self._fade_in = QPropertyAnimation(self._fx, b"opacity", self)
        self._fade_in.setDuration(240)
        self._fade_in.setStartValue(0.0)
        self._fade_in.setEndValue(1.0)
        self._fade_out = QPropertyAnimation(self._fx, b"opacity", self)
        self._fade_out.setDuration(300)
        self._fade_out.setStartValue(1.0)
        self._fade_out.setEndValue(0.0)
        self._fade_out.setEasingCurve(QEasingCurve.Type.InCubic)
        self._fade_out.finished.connect(self._done)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(16)

        logo = QLabel()
        logo.setPixmap(logo_pixmap(76))
        logo.setFixedSize(76, 76)
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)

        brand = QLabel("RME LAUNCHER")
        brand.setObjectName("LoadingBrand")
        brand.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._spinner = _Spinner()

        self._status = QLabel("Scanning platforms\u2026")
        self._status.setObjectName("LoadingStatus")
        self._status.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout.addWidget(logo, 0, Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(brand)
        layout.addSpacing(12)
        layout.addWidget(self._spinner, 0, Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._status)

        screen = QApplication.primaryScreen().availableGeometry()
        self.move(screen.center() - self.rect().center())

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._fade_in.start()

    def set_status(self, text: str) -> None:
        self._status.setText(text)

    def finish(self) -> None:
        self._fade_out.start()

    def _done(self) -> None:
        self.close()
        self.splash_done.emit()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(0.0, 0.0, float(self.width()), float(self.height()),
                            22.0, 22.0)
        painter.fillPath(path, QColor("#0C0C0E"))
        painter.setPen(QPen(QColor(255, 255, 255, 24), 1.0))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)


class _FooterBar(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("FooterBar")
        self.setFixedHeight(44)
        self.setStyleSheet("""
#FooterBar { background: transparent;
             border-top: 1px solid rgba(255,255,255,0.05); }
#FooterVersion { color: #3A3A3C; font-size: 7.5pt; letter-spacing: 1px; }
#FooterCredit { color: #262628; font-size: 7pt; letter-spacing: 1.2px; }
""")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 4, 16, 4)

        layout.addStretch(1)
        version = QLabel(f"v{APP_VERSION}")
        version.setObjectName("FooterVersion")
        layout.addWidget(version)
        layout.addSpacing(10)
        credit = QLabel("By DevForSy X")
        credit.setObjectName("FooterCredit")
        layout.addWidget(credit)


class _ScanWorker(QObject):
    game_found = Signal(object)
    scan_finished = Signal(int, list)

    def __init__(self) -> None:
        super().__init__()
        self._stop = False

    def request_stop(self) -> None:
        self._stop = True

    @Slot()
    def run(self) -> None:
        collected: list[GameEntry] = []
        errors: list[str] = []
        for parser in create_parsers():
            if self._stop:
                return
            try:
                entries = parser.scan()
            except Exception as exc:
                log.exception("Parser %s crashed", parser.source)
                errors.append(f"{parser.source}: {exc}")
                continue
            errors.extend(f"{parser.source}: {e}" for e in parser.errors)
            collected.extend(entries)

        seen_paths: set[str] = set()
        total = 0
        for entry in collected:
            if self._stop:
                return
            key = str(entry.install_path).casefold() if entry.install_path else ""
            if key:
                if key in seen_paths:
                    continue
                seen_paths.add(key)
            self.game_found.emit(entry)
            total += 1
        self.scan_finished.emit(total, errors)


class RmeLauncherWindow(QMainWindow):
    TITLE_H = 48

    def __init__(self, db: Database, settings: Settings) -> None:
        super().__init__()
        self._db = db
        self._settings = settings
        self._library: dict[int, dict] = {}
        self._cards: list[list] = []
        self._known: set[tuple[str, str]] = set()
        self._active_sessions: set[int] = set()
        self._query = ""
        self._hwnd = 0
        self._native_chrome_done = False
        self._scan_started = 0.0
        self._scan_done = False
        self._shutting_down = False
        self._playtime_imported = False
        self._force_quit = False
        self._tray_notice_shown = False

        self.setObjectName("Root")
        self.setWindowTitle("RmE Launcher")
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.setMinimumSize(1080, 700)
        self.resize(1300, 820)

        self._tracker = ProcessTracker(db, self)
        self._tracker.game_started.connect(self._on_session_start)
        self._tracker.game_stopped.connect(self._on_session_stop)
        self._rpc = DiscordRPC()
        self._riot_clicker = RiotAutoClicker(self)
        self._client_guard = ClientGuard(self)
        self._updater = UpdateChecker()

        self._tray = TrayIcon(self)
        self._tray.show_main.connect(self._show_from_tray)
        self._tray.launch_favorite.connect(self._launch)
        self._tray.quit_requested.connect(self._quit_from_tray)
        self._tray.show()

        self._build_ui()

    def _launch_splash(self) -> None:
        self._splash = _SplashScreen()
        self._splash.splash_done.connect(self._activate_after_splash)
        self._splash.show()
        self._start_scan()
        self._updater.check(self._on_update_result)

    def _activate_after_splash(self) -> None:
        self.raise_()
        self.activateWindow()

    @staticmethod
    def _toolbar_button(icon: QIcon, tooltip: str) -> QPushButton:
        button = QPushButton()
        button.setObjectName("WinButton")
        button.setFixedSize(38, 38)
        button.setIcon(icon)
        button.setIconSize(QSize(18, 18))
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setToolTip(tooltip)
        return button

    def _build_ui(self) -> None:
        body = styles.GlassBackdrop()
        self._backdrop = body
        self.setCentralWidget(body)
        root = QVBoxLayout(body)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        titlebar = styles.GlassTitleBar(self.showMinimized, self._toggle_max, self.close)
        root.addWidget(titlebar)

        main = QWidget()
        ml = QVBoxLayout(main)
        ml.setContentsMargins(20, 14, 20, 12)
        ml.setSpacing(10)

        top = QHBoxLayout()
        top.setSpacing(10)
        self._total_chip = QLabel("0 games", objectName="HeaderChip")
        self._search = QLineEdit(objectName="SearchBox")
        self._search.setPlaceholderText("Search games\u2026   (Ctrl+F)")
        self._search.setClearButtonEnabled(True)
        self._search.setFixedWidth(280)
        self._search.textChanged.connect(self._on_search_changed)
        top.addWidget(self._total_chip)
        top.addStretch(1)
        top.addWidget(self._search)
        ml.addLayout(top)

        content = QHBoxLayout()
        content.setSpacing(14)

        self._grid = QListWidget()
        self._grid.setViewMode(QListWidget.ViewMode.IconMode)
        self._grid.setFlow(QListWidget.Flow.LeftToRight)
        self._grid.setResizeMode(QListWidget.ResizeMode.Adjust)
        self._grid.setMovement(QListWidget.Movement.Static)
        self._grid.setWrapping(True)
        self._grid.setSortingEnabled(False)
        self._grid.setSpacing(22)
        self._grid.setUniformItemSizes(True)
        self._grid.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self._grid.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._grid.setItemAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self._grid.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self._grid.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._grid.verticalScrollBar().setSingleStep(40)
        content.addWidget(self._grid, 1)

        side = QWidget()
        side.setFixedWidth(56)
        side_l = QVBoxLayout(side)
        side_l.setContentsMargins(0, 4, 0, 0)
        side_l.setSpacing(10)
        side_l.addStretch(1)

        rescan = self._toolbar_button(icons.refresh_icon(18), "Rescan platforms")
        rescan.clicked.connect(self._rescan)

        add_btn = self._toolbar_button(icons.plus_icon(18), "Add a game manually")
        add_btn.clicked.connect(self._add_manual_game)

        bg_btn = self._toolbar_button(icons.image_icon(18), "Custom background")
        bg_btn.clicked.connect(self._show_background_menu)

        gear = self._toolbar_button(icons.gear_icon(18), "Settings")
        gear.clicked.connect(self._open_settings)

        side_l.addWidget(rescan, 0, Qt.AlignmentFlag.AlignHCenter)
        side_l.addWidget(add_btn, 0, Qt.AlignmentFlag.AlignHCenter)
        side_l.addWidget(bg_btn, 0, Qt.AlignmentFlag.AlignHCenter)
        side_l.addWidget(gear, 0, Qt.AlignmentFlag.AlignHCenter)
        side_l.addStretch(1)
        content.addWidget(side)

        ml.addLayout(content, 1)
        root.addWidget(main, 1)

        self._footer = _FooterBar()
        root.addWidget(self._footer)

        QShortcut(QKeySequence("Ctrl+F"), self).activated.connect(self._search.setFocus)

    def _start_scan(self) -> None:
        self._db.purge_source("pc")
        self._db.purge_stale_minecraft()
        self._scan_started = time.monotonic()
        self._scan_thread = QThread(self)
        self._worker = _ScanWorker()
        self._worker.moveToThread(self._scan_thread)
        self._scan_thread.started.connect(self._worker.run)
        self._worker.game_found.connect(self._add_game)
        self._worker.scan_finished.connect(self._on_scan_finished)
        self._worker.scan_finished.connect(self._scan_thread.quit)
        self._scan_thread.start()

    def _card_for(self, game_id: int) -> GameCard | None:
        for entry in self._cards:
            if entry[4] == game_id:
                return entry[1]
        return None

    def _card_tooltip(self, data: dict) -> str:
        source = str(data.get("source", ""))
        label = styles.SOURCE_LABELS.get(source, source.title())
        fav = "Favorite\n" if data.get("is_favorite") else ""
        return (f"{data.get('title', '')}\n{fav}"
                f"via {label}\n"
                f"Playtime: {_fmt_playtime(int(data.get('total_playtime') or 0))}\n"
                f"Last played: {_fmt_date(data.get('last_played'))}")

    def _append_log(self, message: str) -> None:
        log.info(message)

    def _on_search_changed(self, text: str) -> None:
        if not hasattr(self, "_search_timer"):
            self._search_timer = QTimer(self)
            self._search_timer.setSingleShot(True)
            self._search_timer.setInterval(130)
            self._search_timer.timeout.connect(self._apply_search)
        self._pending_query = text
        self._search_timer.start()

    def _apply_search(self) -> None:
        self._query = (self._pending_query if hasattr(self, "_pending_query") else "").casefold()
        for entry in self._cards:
            entry[0].setHidden(not self._matches(entry[2]))
        self._update_count()

    def _matches(self, title_cf: str) -> bool:
        return not self._query or self._query in title_cf

    @Slot(object)
    def _add_game(self, entry: GameEntry) -> None:
        key = (entry.source, entry.platform_id)
        if key in self._known:
            return
        self._known.add(key)
        game_id = self._db.upsert_game(entry)
        row = self._db.get_game(game_id) or {}
        playtime = int(row.get("total_playtime") or 0)
        last = row.get("last_played") or ""
        fav = bool(row.get("is_favorite"))

        self._library[game_id] = {
            "id": game_id, "source": entry.source, "title": entry.title,
            "platform_id": entry.platform_id,
            "install_path": str(entry.install_path) if entry.install_path else "",
            "executable_path": str(entry.executable_path) if entry.executable_path else "",
            "launch_uri": entry.launch_uri or "",
            "launch_args": list(entry.launch_args),
            "watch_mode": entry.extra.get("watch_mode", ""),
            "mc_dir": entry.extra.get("mc_dir", ""),
            "mc_versions": list(entry.extra.get("mc_versions", [])),
            "hero_urls": entry.hero_urls,
            "playtime": playtime,
            "last": last,
            "fav": fav,
            "watch_name": (entry.extra.get("game_exe_name")
                           or (entry.executable_path.name if entry.executable_path else None)),
        }

        if hasattr(self, "_splash") and self._splash.isVisible():
            self._splash.set_status(f"Found {len(self._library)} games\u2026")

        verified = bool(entry.launch_uri) or (
            entry.executable_path is not None and entry.executable_path.exists())

        item = _SortableItem()
        item.setSizeHint(QSize(GameCard.CARD_W, GameCard.CARD_H))
        item.setData(_ROLE_TITLE, entry.title.casefold())
        item.setData(_ROLE_PLAYED, playtime)
        item.setData(_ROLE_LAST, last)
        item.setData(_ROLE_FAV, 1 if fav else 0)

        card = GameCard(game_id, entry.title, entry.source,
                        verified=verified, playtime_seconds=playtime)
        card.setToolTip(self._card_tooltip(row))
        card.play_clicked.connect(self._launch)
        card.stop_clicked.connect(self._force_stop)
        card.remove_clicked.connect(self._remove_game)
        card.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        card.customContextMenuRequested.connect(
            lambda _pos, gid=game_id: self._show_card_menu(gid))
        card.load_cover(entry.cover_urls,
                        exe_path=str(entry.executable_path) if entry.executable_path else None,
                        title=entry.title)
        card.set_running(game_id in self._active_sessions)
        self._grid.addItem(item)
        self._grid.setItemWidget(item, card)
        self._cards.append([item, card, entry.title.casefold(), entry.source, game_id])
        card.play_entrance(min(60 * (len(self._cards) - 1), 480))
        item.setHidden(not self._matches(entry.title.casefold()))
        self._update_count()

    @Slot(int, list)
    def _on_scan_finished(self, total: int, errors: list[str]) -> None:
        try:
            if errors:
                for message in errors:
                    log.warning("scan: %s", message)
            self._scan_done = True
            if not self._playtime_imported:
                self._playtime_imported = True
                try:
                    import_steam_playtime(self._db)
                except Exception:
                    log.exception("Steam playtime import failed")
            for mrow in self._db.games_by_source("manual"):
                mentry = GameEntry(
                    source="manual", platform_id=mrow["platform_id"],
                    title=mrow["title"],
                    install_path=Path(mrow["install_path"]) if mrow["install_path"] else None,
                    executable_path=(Path(mrow["executable_path"])
                                     if mrow["executable_path"] else None),
                    state_flags=4)
                self._add_game(mentry)
            self._refresh_cards_from_db()
            self._refresh_tray_favorites()
            self._update_count()
            self._apply_sort()
        except Exception:
            log.exception("Scan-finished handling failed - revealing app anyway")
        self._scan_done = True
        elapsed = time.monotonic() - self._scan_started
        splash_min = self._settings.splash_min_seconds
        delay_ms = max(0, int((splash_min - elapsed) * 1000))
        QTimer.singleShot(delay_ms, self._reveal_app)

    def _refresh_cards_from_db(self) -> None:
        for entry in self._cards:
            gid = entry[4]
            row = self._db.get_game(gid)
            if not row:
                continue
            lib = self._library.get(gid)
            playtime = int(row.get("total_playtime") or 0)
            last = row.get("last_played") or ""
            fav = bool(row.get("is_favorite"))
            if lib is not None:
                lib["playtime"] = playtime
                lib["last"] = last
                lib["fav"] = fav
            item = entry[0]
            item.setData(_ROLE_PLAYED, playtime)
            item.setData(_ROLE_LAST, last)
            item.setData(_ROLE_FAV, 1 if fav else 0)
            entry[1].set_playtime(playtime)

    def _update_count(self) -> None:
        if not hasattr(self, "_total_chip"):
            return
        total = len(self._cards)
        shown = sum(1 for entry in self._cards if not entry[0].isHidden())
        hours = sum(int(lib.get("playtime") or 0) for lib in self._library.values())
        self._total_chip.setText(f"{shown}/{total} games  \u00b7  {_fmt_playtime(hours)}")

    def _apply_sort(self) -> None:
        if not hasattr(self, "_grid"):
            return
        for entry in self._cards:
            lib = self._library.get(entry[4], {})
            item = entry[0]
            item.setData(_ROLE_PLAYED, int(lib.get("playtime") or 0))
            item.setData(_ROLE_LAST, lib.get("last") or "")
            item.setData(_ROLE_TITLE, entry[2])
            item.setData(_ROLE_FAV, 1 if lib.get("fav") else 0)
        _SortableItem.sort_mode = "recent"
        self._grid.sortItems()

    def _reveal_app(self) -> None:
        if self._shutting_down:
            return
        if hasattr(self, "_splash") and self._splash.isVisible():
            self.show()
            self._splash.finish()
        else:
            self.show()
            self.raise_()
            self.activateWindow()

    def _on_update_result(self, has_update: bool, url: str, notes: str) -> None:
        if not has_update or self._shutting_down:
            return
        box = QMessageBox(self)
        box.setStyleSheet(
            "QMessageBox { background:#141416; }"
            "QLabel { color:#F5F5F7; font-size:10pt; }"
            "QPushButton { border:none; border-radius:8px;"
            " padding:6px 20px; min-width:80px; font-weight:600; }")
        box.setIcon(QMessageBox.Icon.Information)
        box.setWindowTitle("Update available")
        box.setText("A new version of RmE Launcher is available.\n"
                    "Open the download page?")
        open_btn = box.addButton("Open", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Later", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is open_btn and url:
            QDesktopServices.openUrl(QUrl(url))

    def _open_settings(self) -> None:
        SettingsDialog.open_dialog(self._settings, self)

    def _rescan(self) -> None:
        if getattr(self, "_scan_thread", None) and self._scan_thread.isRunning():
            return
        self._start_scan()

    def _add_manual_game(self) -> None:
        exe, _selected = QFileDialog.getOpenFileName(
            self, "Choose the game executable", "",
            "Executables (*.exe);;All files (*)")
        if not exe:
            return
        p = Path(exe)
        if ("manual", str(p).casefold()) in self._known:
            return
        if p.suffix.casefold() != ".exe":
            return
        try:
            if not p.is_file() or p.stat().st_size <= 0:
                return
        except OSError:
            return
        title = p.stem.replace("_", " ").strip() or "My Game"
        try:
            game_id = self._db.add_manual_game(title, str(p))
        except Exception:
            log.exception("Manual add failed")
            return
        entry = GameEntry(
            source="manual", platform_id=str(p).casefold(), title=title,
            install_path=p.parent, executable_path=p, state_flags=4)
        self._add_game(entry)
        self._apply_sort()

    def _show_from_tray(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()

    def _quit_from_tray(self) -> None:
        self._force_quit = True
        self.close()

    def _show_background_menu(self) -> None:
        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu { background:#141416; color:#F5F5F7;"
            " border:1px solid rgba(255,255,255,0.12); border-radius:12px;"
            " padding:6px; }"
            "QMenu::item { padding:6px 22px; border-radius:8px; }"
            "QMenu::item:selected { background:rgba(255,255,255,0.12); }")
        act_set = QAction("Set custom background\u2026", menu)
        act_set.triggered.connect(self._set_custom_background)
        menu.addAction(act_set)
        act_reset = QAction("Reset to default", menu)
        act_reset.setEnabled(CustomBackgroundManager.exists())
        act_reset.triggered.connect(self._reset_background)
        menu.addAction(act_reset)
        menu.exec(QCursor.pos())

    def _set_custom_background(self) -> None:
        source, _selected = QFileDialog.getOpenFileName(
            self, "Choose a background image", "",
            "Images (*.png *.jpg *.jpeg *.bmp *.gif *.webp)")
        if not source:
            return
        ok, message = CustomBackgroundManager.validate_and_store(source)
        box = QMessageBox(self)
        box.setStyleSheet(
            "QMessageBox { background:#141416; }"
            "QLabel { color:#F5F5F7; font-size:10pt; }"
            "QPushButton { background:#F5F5F7; color:#0A0A0C; border:none;"
            " border-radius:8px; padding:6px 20px; min-width:70px; }")
        if ok:
            self._backdrop.reload_custom()
            box.setIcon(QMessageBox.Icon.Information)
            box.setWindowTitle("Background")
            box.setText(message)
        else:
            box.setIcon(QMessageBox.Icon.Warning)
            box.setWindowTitle("Rejected")
            box.setText(f"The file was rejected:\n\n{message}")
        box.exec()

    def _reset_background(self) -> None:
        if CustomBackgroundManager.clear():
            self._backdrop.reload_custom()

    def _toggle_favorite(self, game_id: int) -> None:
        row = self._db.get_game(game_id) or {}
        new_val = not bool(row.get("is_favorite"))
        self._db.set_favorite(game_id, new_val)
        lib = self._library.get(game_id)
        if lib is not None:
            lib["fav"] = new_val
        for entry in self._cards:
            if entry[4] == game_id:
                entry[0].setData(_ROLE_FAV, 1 if new_val else 0)
                updated = dict(row, is_favorite=1 if new_val else 0)
                entry[1].setToolTip(self._card_tooltip(updated))
                break
        self._refresh_tray_favorites()
        self._apply_sort()

    def _refresh_tray_favorites(self) -> None:
        favs = self._db.favorites()
        self._tray.set_favorites([(f["id"], f["title"]) for f in favs])

    def _set_custom_image(self, game_id: int) -> None:
        card = self._card_for(game_id)
        if card is None:
            return
        source, _selected = QFileDialog.getOpenFileName(
            self, "Choose a cover image", "",
            "Images (*.png *.jpg *.jpeg *.webp)")
        if source:
            card.set_custom_image(source)

    def _show_card_menu(self, game_id: int) -> None:
        row = self._db.get_game(game_id) or {}
        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu { background:#141416; color:#F5F5F7;"
            " border:1px solid rgba(255,255,255,0.12); border-radius:12px;"
            " padding:6px; }"
            "QMenu::item { padding:6px 22px; border-radius:8px; }"
            "QMenu::item:selected { background:rgba(255,255,255,0.12); }"
            "QMenu::separator { height:1px; background:rgba(255,255,255,0.08);"
            " margin:4px 8px; }")
        act_launch = QAction("Launch", menu)
        act_launch.setIcon(icons.play_icon(14))
        act_launch.triggered.connect(lambda: self._launch(game_id))
        menu.addAction(act_launch)
        menu.addSeparator()
        fav_label = ("Unpin from favorites" if row.get("is_favorite")
                     else "Pin to favorites")
        act_fav = QAction(fav_label, menu)
        act_fav.triggered.connect(lambda: self._toggle_favorite(game_id))
        menu.addAction(act_fav)
        act_image = QAction("Set custom cover\u2026", menu)
        act_image.triggered.connect(lambda: self._set_custom_image(game_id))
        menu.addAction(act_image)
        install_path = str(row.get("install_path") or "")
        if install_path and Path(install_path).is_dir():
            act_folder = QAction("Open install folder", menu)
            act_folder.triggered.connect(
                lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(install_path)))
            menu.addAction(act_folder)
        menu.addSeparator()
        act_remove = QAction("Remove from library", menu)
        act_remove.setIcon(icons.trash_icon(14, QColor("#A1A1A6")))
        act_remove.triggered.connect(lambda: self._remove_game(game_id))
        menu.addAction(act_remove)
        menu.exec(QCursor.pos())

    def _remove_game(self, game_id: int) -> None:
        row = self._db.get_game(game_id) or {}
        title = str(row.get("title") or "this game")
        if self._tracker.is_running(game_id):
            box = QMessageBox(self)
            box.setStyleSheet(
                "QMessageBox { background:#141416; }"
                "QLabel { color:#F5F5F7; font-size:10pt; }"
                "QPushButton { background:#F5F5F7; color:#0A0A0C; border:none;"
                " border-radius:8px; padding:6px 20px; min-width:70px; }")
            box.setIcon(QMessageBox.Icon.Warning)
            box.setWindowTitle("Cannot remove")
            box.setText(f"'{title}' is currently running.\n"
                        "Stop it first, then remove it.")
            box.exec()
            return
        box = QMessageBox(self)
        box.setStyleSheet(
            "QMessageBox { background:#141416; }"
            "QLabel { color:#F5F5F7; font-size:10pt; }"
            "QPushButton { border:none; border-radius:8px;"
            " padding:6px 20px; min-width:70px; font-weight:600; }")
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("Remove game")
        box.setText(f"Remove '{title}' from your library?\n\n"
                    "Its playtime history will be deleted too.\n"
                    "The game files on disk are NOT touched.")
        yes = box.addButton("Remove", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is not yes:
            return

        self._db.delete_game(game_id)

        for entry in list(self._cards):
            if entry[4] != game_id:
                continue
            item = entry[0]
            self._grid.removeItemWidget(item)
            row_idx = self._grid.row(item)
            if row_idx >= 0:
                self._grid.takeItem(row_idx)
            self._cards.remove(entry)
            break

        self._library.pop(game_id, None)
        if row.get("source") and row.get("platform_id"):
            self._known.discard((str(row["source"]), str(row["platform_id"])))
        self._active_sessions.discard(game_id)
        card = self._card_for(game_id)
        if card is not None:
            card.set_running(False)

        self._refresh_tray_favorites()
        self._update_count()

    def _matches(self, title_cf: str) -> bool:
        return not self._query or self._query in title_cf

    @Slot(int)
    def _launch(self, game_id: int) -> None:
        data = self._library.get(game_id)
        if not data:
            return
        title = data["title"]
        try:
            if data["launch_uri"]:
                scheme = QUrl(data["launch_uri"]).scheme().casefold()
                if scheme not in _ALLOWED_URI_SCHEMES:
                    log.warning("BLOCKED non-whitelisted scheme for %s", title)
                    return
                QDesktopServices.openUrl(QUrl(data["launch_uri"]))
                self._db.touch_last_played(game_id)
                watch_name = data.get("watch_name")
                if watch_name:
                    self._tracker.watch(game_id, title, process_name=watch_name)
                return

            if data["executable_path"]:
                if data.get("source") in _CLIENT_BACKED_SOURCES:
                    self._db.touch_last_played(game_id)
                    self._client_guard.launch_with_client(
                        data["source"],
                        lambda: self._spawn_game_exe(data, game_id),
                        self._append_log)
                    return
                self._spawn_game_exe(data, game_id)
        except Exception as exc:
            log.exception("Launch failed for %s", title)

    def _spawn_game_exe(self, data: dict, game_id: int) -> None:
        title = data["title"]
        watch_name: str | None = None
        watch_pid: int | None = None
        try:
            exe = data["executable_path"]
            if not exe or not Path(exe).is_file():
                return
            args = list(data.get("launch_args", []))
            mc_versions = list(data.get("mc_versions", []))
            if data.get("mc_dir"):
                args += ["--workDir", str(data["mc_dir"])]
            flags = subprocess.DETACHED_PROCESS if os.name == "nt" else 0
            proc = subprocess.Popen([exe, *args],
                                    cwd=os.path.dirname(exe) or None,
                                    creationflags=flags)
            if data.get("launch_args"):
                if data.get("watch_mode") == "pid":
                    watch_pid, watch_name = proc.pid, data.get("watch_name")
                else:
                    watch_name = data.get("watch_name")
            else:
                watch_pid, watch_name = proc.pid, data.get("watch_name")
            if data.get("mc_dir"):
                self._append_log(
                    f"Minecraft Launcher \u2014 {len(mc_versions)} installed "
                    f"version(s): {', '.join(mc_versions[:6])}"
                    f"{' \u2026' if len(mc_versions) > 6 else ''}")
            else:
                self._append_log(f"Launched {title} (pid {proc.pid})")
            self._db.touch_last_played(game_id)
        except Exception as exc:
            log.exception("Launch failed for %s", title)
            return
        if watch_name or watch_pid:
            self._tracker.watch(game_id, title, process_name=watch_name, pid=watch_pid)
        if data.get("source") == "riot" and self._settings.riot_clicker_enabled:
            self._riot_clicker.arm(data.get("watch_name"))

    @Slot(int)
    def _force_stop(self, game_id: int) -> None:
        data = self._library.get(game_id)
        if not data:
            return
        title = data["title"]
        if not self._tracker.is_running(game_id):
            return
        if self._tracker.force_stop(game_id, title):
            self._append_log(f"Force-closed \u2014 {title}")

    @Slot(int, str)
    def _on_session_start(self, game_id: int, title: str) -> None:
        source = self._library.get(game_id, {}).get("source", "")
        self._append_log(f"Session started \u2014 {title}")
        self._rpc.set_activity(
            f"Playing {title}",
            f"via RmE Launcher \u00b7 {styles.SOURCE_LABELS.get(source, '')}".strip())
        self._active_sessions.add(game_id)
        card = self._card_for(game_id)
        if card is not None:
            card.set_running(True)

    @Slot(int, str, int)
    def _on_session_stop(self, game_id: int, title: str, duration_s: int) -> None:
        self._append_log(f"Session ended \u2014 {title} ({_fmt_playtime(duration_s)})")
        self._rpc.clear_to_idle()
        self._active_sessions.discard(game_id)
        card = self._card_for(game_id)
        if card is not None:
            card.set_running(False)
        row = self._db.get_game(game_id)
        if row:
            lib = self._library.get(game_id)
            playtime = int(row.get("total_playtime") or 0)
            last = row.get("last_played") or ""
            if lib is not None:
                lib["playtime"] = playtime
                lib["last"] = last
            for entry in self._cards:
                if entry[4] == game_id:
                    entry[0].setData(_ROLE_PLAYED, playtime)
                    entry[0].setData(_ROLE_LAST, last)
                    entry[1].set_playtime(playtime)
                    entry[1].setToolTip(self._card_tooltip(row))
                    break
            self._update_count()
            self._apply_sort()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._native_chrome_done and sys.platform == "win32":
            self._hwnd = int(self.winId())
            win32.enable_native_chrome(self._hwnd)
            win32.apply_dwm_preferences(self._hwnd)
            self._native_chrome_done = True

    def nativeEvent(self, eventType, message):
        if eventType in ("windows_generic_MSG", b"windows_generic_MSG") and self._hwnd:
            hwnd, msg_id, wparam, lparam = win32.parse_message(int(message))
            if hwnd == self._hwnd:
                if msg_id == win32.WM_NCCALCSIZE and wparam:
                    if win32.is_zoomed(self._hwnd):
                        win32.deflate_client_rect(lparam,
                                                  win32.resize_border_thickness())
                    return True, 0
                if msg_id == win32.WM_NCHITTEST:
                    return True, self._hit_test(lparam)
                if msg_id == win32.WM_NCACTIVATE:
                    win32.def_window_proc(self._hwnd, msg_id, wparam, -1)
                    return True, 1
        return super().nativeEvent(eventType, message)

    def _hit_test(self, lparam: int) -> int:
        x, y = win32.lparam_to_point(lparam)
        dpr = self.devicePixelRatioF() or 1.0
        local = self.mapFromGlobal(QPoint(round(x / dpr), round(y / dpr)))
        w, h = self.width(), self.height()
        if not (0 <= local.x() <= w and 0 <= local.y() <= h):
            return win32.HTCLIENT

        if not win32.is_zoomed(self._hwnd):
            margin = 8
            left, right = local.x() <= margin, local.x() >= w - margin
            top, bottom = local.y() <= margin, local.y() >= h - margin
            if top and left:    return win32.HTTOPLEFT
            if top and right:   return win32.HTTOPRIGHT
            if bottom and left: return win32.HTBOTTOMLEFT
            if bottom and right:return win32.HTBOTTOMRIGHT
            if left:  return win32.HTLEFT
            if right: return win32.HTRIGHT
            if top:   return win32.HTTOP
            if bottom:return win32.HTBOTTOM

        if local.y() <= self.TITLE_H:
            child = self.childAt(local)
            if child is None or not isinstance(child, (QPushButton, QLineEdit)):
                return win32.HTCAPTION
        return win32.HTCLIENT

    def _toggle_max(self) -> None:
        self.showNormal() if self.isMaximized() else self.showMaximized()

    def closeEvent(self, event) -> None:
        if self._settings.close_to_tray and not self._force_quit:
            event.ignore()
            self.hide()
            if not self._tray_notice_shown:
                self._tray_notice_shown = True
                self._tray.show_message(
                    "RmE Launcher",
                    "Still running in the tray. Quit from the tray menu.")
            return
        self._shutting_down = True
        self._tray.hide()
        self._tracker.stop()
        self._rpc.shutdown()
        if hasattr(self, "_splash") and self._splash.isVisible():
            self._splash.close()
        if hasattr(self, "_worker") and hasattr(self, "_scan_thread"):
            self._worker.request_stop()
            if self._scan_thread.isRunning():
                self._scan_thread.quit()
                if not self._scan_thread.wait(3000):
                    log.warning("Scan thread did not stop within 3 s")
        super().closeEvent(event)