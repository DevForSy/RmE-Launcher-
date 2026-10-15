from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Callable, Sequence
from urllib.parse import quote

from PySide6.QtCore import (QStandardPaths, QEasingCurve, QPointF, QSize, Qt,
                            QTimer, QUrl, QPropertyAnimation, QVariantAnimation,
                            Signal)
from PySide6.QtGui import (QColor, QFont, QLinearGradient, QPainter,
                           QPainterPath, QPen, QPixmap, QPolygonF)
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (QFrame, QGraphicsOpacityEffect, QHBoxLayout,
                               QLabel, QPushButton, QVBoxLayout, QWidget)

from ui import icons
from ui.styles import SOURCE_LABELS

log = logging.getLogger(__name__)

_NETWORK: QNetworkAccessManager | None = None
_REPLIES: set[QNetworkReply] = set()

_TRANSFER_TIMEOUT_MS = 15_000
_MAX_IMAGE_BYTES = 30 * 1024 * 1024
_MAX_HTML_BYTES = 2 * 1024 * 1024

_OG_IMAGE_RE = re.compile(
    r"<meta[^>]+(?:property|name)=[\"']og:image(?::secure_url)?[\"'][^>]*"
    r"content=[\"']([^\"']+)[\"']", re.IGNORECASE)
_OG_IMAGE_RE_ALT = re.compile(
    r"<meta[^>]+content=[\"']([^\"']+)[\"'][^>]*"
    r"(?:property|name)=[\"']og:image[\"']", re.IGNORECASE)

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_JPEG_MAGIC = b"\xff\xd8\xff"

_STEAM_SEARCH_URL = ("https://store.steampowered.com/api/storesearch/"
                     "?term={term}&l=english&cc=US")

_ROBLOX_COVER = "https://i.postimg.cc/jjMgCYG2/3fd94f4396a61a3b603a085e17bd2262.jpg"


def _network() -> QNetworkAccessManager:
    global _NETWORK
    if _NETWORK is None:
        _NETWORK = QNetworkAccessManager()
    return _NETWORK


def _cache_dir() -> Path:
    base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
    path = Path(base) / "covers"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _first_og_image(html: str) -> str | None:
    match = _OG_IMAGE_RE.search(html) or _OG_IMAGE_RE_ALT.search(html)
    if not match:
        return None
    url = match.group(1).replace("&amp;", "&")
    return url if url.startswith("https://") else None


def load_remote_image(urls: Sequence[str], on_ready: Callable[[str | None], None]) -> None:
    queue = [u for u in urls if u]

    def attempt(index: int, hops: int = 0) -> None:
        if index >= len(queue):
            on_ready(None)
            return
        url = queue[index]
        path = _cache_dir() / f"{hashlib.sha1(url.encode()).hexdigest()[:24]}.img"

        if path.is_file():
            if path.read_bytes()[:1] == b"<":
                og = _first_og_image(path.read_text(encoding="utf-8",
                                                    errors="replace")[:_MAX_HTML_BYTES])
                if og and og != url and hops < 2:
                    queue[index] = og
                    attempt(index, hops + 1)
                    return
                attempt(index + 1)
                return
            on_ready(str(path))
            return

        request = QNetworkRequest(QUrl(url))
        request.setTransferTimeout(_TRANSFER_TIMEOUT_MS)
        request.setAttribute(QNetworkRequest.RedirectPolicyAttribute,
                             QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy)
        reply = _network().get(request)

        def _on_progress(received: int, _total: int) -> None:
            if received > _MAX_IMAGE_BYTES:
                reply.abort()

        reply.downloadProgress.connect(_on_progress)

        def _done() -> None:
            _REPLIES.discard(reply)
            reply.deleteLater()
            if reply.error() != QNetworkReply.NetworkError.NoError:
                attempt(index + 1)
                return
            data = bytes(reply.readAll())
            if not data or len(data) > _MAX_IMAGE_BYTES:
                attempt(index + 1)
                return
            ctype = str(reply.header(QNetworkRequest.KnownHeaders.ContentTypeHeader) or "")
            try:
                path.write_bytes(data)
            except OSError:
                pass
            if "text/html" in ctype or data[:1] == b"<":
                og = _first_og_image(data[:_MAX_HTML_BYTES].decode("utf-8",
                                                                   errors="replace"))
                if og and og != url and hops < 2:
                    queue[index] = og
                    attempt(index, hops + 1)
                else:
                    attempt(index + 1)
                return
            if data[:8] == _PNG_MAGIC or data[:3] == _JPEG_MAGIC or "image/" in ctype:
                on_ready(str(path))
            else:
                attempt(index + 1)

        reply.finished.connect(_done)
        _REPLIES.add(reply)

    attempt(0)


def rounded_pixmap(src: QPixmap, size: QSize, radius: int) -> QPixmap:
    out = QPixmap(size)
    out.fill(Qt.GlobalColor.transparent)
    if src.isNull():
        return out
    painter = QPainter(out)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    clip = QPainterPath()
    clip.addRoundedRect(0.0, 0.0, float(size.width()), float(size.height()),
                        float(radius), float(radius))
    painter.setClipPath(clip)
    scaled = src.scaled(size, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                        Qt.TransformationMode.SmoothTransformation)
    dx = max(0, (scaled.width() - size.width()) // 2)
    dy = max(0, (scaled.height() - size.height()) // 2)
    painter.drawPixmap(-dx, -dy, scaled)
    sheen = QLinearGradient(0.0, 0.0, 0.0, float(size.height()))
    sheen.setColorAt(0.0, QColor(255, 255, 255, 26))
    sheen.setColorAt(0.30, QColor(255, 255, 255, 0))
    painter.fillRect(0, 0, size.width(), size.height(), sheen)
    painter.end()
    return out


_MC_ROWS = (
    "GGGGGGGG",
    "GgGGgGGG",
    "DdDGDdDD",
    "DDdDDDdD",
    "dDDdDDDD",
    "EDDdDDdD",
    "DdEDdDDD",
    "DDDdDEDD",
)
_MC_PALETTE = {
    "G": "#8CCB5A", "g": "#6AAD3D", "D": "#8B5A2B",
    "d": "#79502A", "E": "#9C6B3A",
}


def minecraft_tile_pixmap(size: QSize, radius: int) -> QPixmap:
    out = QPixmap(size)
    out.fill(Qt.GlobalColor.transparent)
    cell = QPixmap(8, 8)
    painter = QPainter(cell)
    for y, row in enumerate(_MC_ROWS):
        for x, ch in enumerate(row):
            painter.fillRect(x, y, 1, 1, QColor(_MC_PALETTE[ch]))
    painter.end()
    painter = QPainter(out)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    clip = QPainterPath()
    clip.addRoundedRect(0.0, 0.0, float(size.width()), float(size.height()),
                        float(radius), float(radius))
    painter.setClipPath(clip)
    scaled = cell.scaled(size, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                         Qt.TransformationMode.FastTransformation)
    painter.drawPixmap(0, 0, scaled)
    sheen = QLinearGradient(0.0, 0.0, 0.0, float(size.height()))
    sheen.setColorAt(0.0, QColor(255, 255, 255, 26))
    sheen.setColorAt(0.30, QColor(255, 255, 255, 0))
    painter.fillRect(0, 0, size.width(), size.height(), sheen)
    painter.end()
    return out


def roblox_tile_pixmap(size: QSize, radius: int) -> QPixmap:
    out = QPixmap(size)
    out.fill(Qt.GlobalColor.transparent)
    painter = QPainter(out)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    clip = QPainterPath()
    clip.addRoundedRect(0.0, 0.0, float(size.width()), float(size.height()),
                        float(radius), float(radius))
    painter.setClipPath(clip)

    base = QLinearGradient(0.0, 0.0, 0.0, float(size.height()))
    base.setColorAt(0.0, QColor("#232326"))
    base.setColorAt(1.0, QColor("#0D0D10"))
    painter.fillRect(out.rect(), base)

    sq = min(size.width(), size.height()) * 0.44
    sx = (size.width() - sq) / 2.0
    sy = (size.height() - sq) / 2.0 - size.height() * 0.04
    tilt = sq * 0.24

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#F5F5F7"))

    p1 = QPolygonF([
        QPointF(sx + tilt, sy),
        QPointF(sx + sq, sy),
        QPointF(sx + sq - tilt, sy + tilt),
        QPointF(sx, sy + tilt),
    ])
    painter.drawPolygon(p1)

    p2 = QPolygonF([
        QPointF(sx, sy + tilt),
        QPointF(sx + sq - tilt, sy + tilt),
        QPointF(sx + sq - sq * 0.18, sy + sq * 0.30),
        QPointF(sx + sq * 0.18, sy + sq * 0.30),
    ])
    painter.drawPolygon(p2)

    font = QFont("Segoe UI Black", max(10, int(sq * 0.32)))
    font.setBold(True)
    painter.setFont(font)
    painter.setPen(QColor("#E2231A"))
    painter.drawText(out.rect(), Qt.AlignmentFlag.AlignCenter, "R")

    sheen = QLinearGradient(0.0, 0.0, 0.0, float(size.height()))
    sheen.setColorAt(0.0, QColor(255, 255, 255, 30))
    sheen.setColorAt(0.30, QColor(255, 255, 255, 0))
    painter.fillRect(0, 0, size.width(), size.height(), sheen)
    painter.end()
    return out


_GRADIENTS = [("#2A2A2E", "#161618"), ("#232326", "#121214"), ("#1E1E22", "#0E0E10"),
              ("#26262B", "#131316"), ("#202024", "#101012"), ("#1C1C20", "#0D0D0F")]


def placeholder_pixmap(title: str, size: QSize, radius: int) -> QPixmap:
    out = QPixmap(size)
    out.fill(Qt.GlobalColor.transparent)
    painter = QPainter(out)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    clip = QPainterPath()
    clip.addRoundedRect(0.0, 0.0, float(size.width()), float(size.height()),
                        float(radius), float(radius))
    painter.setClipPath(clip)
    seed = int(hashlib.sha1(title.encode()).hexdigest(), 16) % len(_GRADIENTS)
    top, bottom = _GRADIENTS[seed]
    grad = QLinearGradient(0.0, 0.0, 0.0, float(size.height()))
    grad.setColorAt(0.0, QColor(top))
    grad.setColorAt(1.0, QColor(bottom))
    painter.fillRect(out.rect(), grad)
    initials = "".join(w[0] for w in title.split()[:2]).upper() or (title[:1] or "?")
    painter.setPen(QColor(245, 245, 247, 200))
    font = QFont("Segoe UI Semibold", 28)
    painter.setFont(font)
    painter.drawText(out.rect(), Qt.AlignmentFlag.AlignCenter, initials)
    sheen = QLinearGradient(0.0, 0.0, 0.0, float(size.height()))
    sheen.setColorAt(0.0, QColor(255, 255, 255, 30))
    sheen.setColorAt(0.30, QColor(255, 255, 255, 0))
    painter.fillRect(0, 0, size.width(), size.height(), sheen)
    painter.end()
    return out


class GameCard(QFrame):
    clicked = Signal(int)
    play_clicked = Signal(int)
    stop_clicked = Signal(int)
    remove_clicked = Signal(int)

    CARD_W, CARD_H = 240, 358
    COVER_W, COVER_H = 238, 272
    RADIUS = 8

    def __init__(self, game_id: int, title: str, source: str,
                 verified: bool = True, playtime_seconds: int = 0,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._game_id = game_id
        self._title = title
        self._source = source
        self._hover = 0.0
        self._sweep = 0.0
        self._chip: QLabel | None = None
        self._steam_tried = False
        self._exe_path = None
        self._search_title = title

        self.setObjectName("GameCard")
        self.setFixedSize(self.CARD_W, self.CARD_H)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(1, 1, 1, 1)
        layout.setSpacing(0)

        self._cover = QLabel()
        self._cover.setFixedSize(self.COVER_W, self.COVER_H)
        if source == "minecraft":
            self._cover.setPixmap(
                minecraft_tile_pixmap(QSize(self.COVER_W, self.COVER_H), self.RADIUS))
        elif source == "roblox":
            self._cover.setPixmap(
                roblox_tile_pixmap(QSize(self.COVER_W, self.COVER_H), self.RADIUS))
        else:
            self._cover.setPixmap(
                placeholder_pixmap(title, QSize(self.COVER_W, self.COVER_H), self.RADIUS))
        layout.addWidget(self._cover)

        footer = QWidget()
        footer.setFixedHeight(self.CARD_H - self.COVER_H - 2)
        fl = QVBoxLayout(footer)
        fl.setContentsMargins(12, 7, 12, 8)
        fl.setSpacing(6)
        metrics = self.fontMetrics()
        self._title_label = QLabel(metrics.elidedText(
            title, Qt.TextElideMode.ElideRight, self.CARD_W - 24))
        self._title_label.setObjectName("CardTitle")
        self._title_label.setTextFormat(Qt.TextFormat.PlainText)

        label = SOURCE_LABELS.get(source, source.title())
        ready = '<span style="color:#30D158">\u2713</span>'
        missing = '<span style="color:#FF453A">\u2717</span>'
        status = ready if verified else missing
        self._meta_label = QLabel(
            f"<span style='font-size:8.5pt;color:#6E6E73'>{label}</span> {status}")
        self._meta_label.setObjectName("CardMeta")
        fl.addWidget(self._title_label)
        fl.addWidget(self._meta_label)

        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 0, 0, 0)
        btn_row.setSpacing(6)
        self._play_btn = QPushButton("PLAY")
        self._play_btn.setObjectName("CardPlayBtn")
        self._play_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._play_btn.setFixedHeight(28)
        self._play_btn.clicked.connect(lambda: self.play_clicked.emit(self._game_id))
        btn_row.addWidget(self._play_btn)

        self._stop_btn = QPushButton("STOP")
        self._stop_btn.setObjectName("CardStopBtn")
        self._stop_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._stop_btn.setFixedHeight(28)
        self._stop_btn.setToolTip("Force-close this game")
        self._stop_btn.clicked.connect(lambda: self.stop_clicked.emit(self._game_id))
        self._stop_btn.hide()
        btn_row.addWidget(self._stop_btn)

        btn_row.addStretch(1)

        self._remove_btn = QPushButton()
        self._remove_btn.setObjectName("CardRemoveBtn")
        self._remove_btn.setIcon(icons.trash_icon(13))
        self._remove_btn.setIconSize(QSize(13, 13))
        self._remove_btn.setFixedSize(32, 28)
        self._remove_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._remove_btn.setToolTip("Remove from library")
        self._remove_btn.clicked.connect(lambda: self.remove_clicked.emit(self._game_id))
        btn_row.addWidget(self._remove_btn)

        fl.addLayout(btn_row)
        layout.addWidget(footer)

        self._fx = QGraphicsOpacityEffect(self)
        self._fx.setOpacity(0.0)
        self.setGraphicsEffect(self._fx)
        self._entrance = QPropertyAnimation(self._fx, b"opacity", self)
        self._entrance.setDuration(300)
        self._entrance.setStartValue(0.0)
        self._entrance.setEndValue(1.0)
        self._entrance.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._anim = QVariantAnimation(self)
        self._anim.setDuration(160)
        self._anim.valueChanged.connect(self._set_hover)

        self.set_playtime(playtime_seconds)

    def play_entrance(self, delay_ms: int) -> None:
        delay = max(0, int(delay_ms))
        if delay == 0:
            self._entrance.start()
            return
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(self._entrance.start)
        timer.timeout.connect(timer.deleteLater)
        self._entrance_timer = timer
        timer.start(delay)

    def set_running(self, running: bool) -> None:
        try:
            self._stop_btn.setVisible(running)
            self._stop_btn.setEnabled(running)
            self._play_btn.setVisible(not running)
        except (RuntimeError, AttributeError):
            pass

    @staticmethod
    def _chip_text(seconds: int) -> str | None:
        s = int(seconds)
        if s >= 3600:
            return f"{s // 3600}h"
        if s >= 60:
            return f"{s // 60}m"
        return None

    def set_playtime(self, seconds: int) -> None:
        try:
            text = self._chip_text(seconds)
            if text is None:
                if self._chip is not None:
                    self._chip.hide()
                return
            if self._chip is None:
                chip = QLabel(self._cover)
                chip.setObjectName("PlaytimeChip")
                self._chip = chip
            self._chip.setText(text)
            self._chip.adjustSize()
            self._chip.move(self.COVER_W - self._chip.width() - 10,
                            self.COVER_H - self._chip.height() - 10)
            self._chip.raise_()
            self._chip.show()
        except RuntimeError:
            log.debug("Playtime chip update on deleted card ignored")

    def load_cover(self, urls: Sequence[str],
                   exe_path: str | None = None,
                   title: str | None = None) -> None:
        self._exe_path = exe_path
        self._search_title = title or self._title

        custom = Path(QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.AppDataLocation)) / "covers" / "custom" / f"{self._game_id}.img"
        if custom.is_file():
            pixmap = QPixmap(str(custom))
            if not pixmap.isNull():
                self._apply_cover_pixmap(pixmap)
                return

        if self._source == "roblox":
            load_remote_image([_ROBLOX_COVER], self._roblox_done)
            return

        if self._source == "minecraft":
            return

        famous = self._famous_art_for(self._search_title)
        if famous:
            self._famous_chain = famous
            load_remote_image(famous, self._famous_done)
            return

        if urls:
            load_remote_image(urls, self._cover_chain_done)
        else:
            self._cover_chain_done(None)

    def _roblox_done(self, path: str | None) -> None:
        try:
            if path:
                pixmap = QPixmap(path)
                if not pixmap.isNull():
                    self._apply_cover_pixmap(pixmap)
                    return
            self._cover.setPixmap(
                roblox_tile_pixmap(QSize(self.COVER_W, self.COVER_H), self.RADIUS))
        except RuntimeError:
            log.debug("Roblox cover on deleted card ignored")

    def _famous_art_for(self, title: str) -> list[str]:
        slug = title.casefold().replace(" ", "_").replace(":", "").replace("-", "_")
        while "__" in slug:
            slug = slug.replace("__", "_")
        table = {
            "valorant": ["https://playvalorant.com/"],
            "league_of_legends": [
                "https://www.leagueoflegends.com/",
                "https://ddragon.leagueoflegends.com/cdn/img/champion/splash/Jinx_0.jpg",
            ],
            "counter_strike_2": ["https://cdn.cloudflare.steamstatic.com/steam/apps/730/library_600x900.jpg"],
            "counter_strike": ["https://cdn.cloudflare.steamstatic.com/steam/apps/730/library_600x900.jpg"],
            "fortnite": ["https://cdn2.unrealengine.com/fortnite-keyart-1920x1080-8b0f6cf34f7b.jpg"],
            "gta_v": ["https://cdn.cloudflare.steamstatic.com/steam/apps/271590/library_600x900.jpg"],
            "grand_theft_auto_v": ["https://cdn.cloudflare.steamstatic.com/steam/apps/271590/library_600x900.jpg"],
            "red_dead_redemption_2": ["https://cdn.cloudflare.steamstatic.com/steam/apps/1174180/library_600x900.jpg"],
            "apex_legends": ["https://cdn.cloudflare.steamstatic.com/steam/apps/1172470/library_600x900.jpg"],
            "dota_2": ["https://cdn.cloudflare.steamstatic.com/steam/apps/570/library_600x900.jpg"],
            "pubg": ["https://cdn.cloudflare.steamstatic.com/steam/apps/578080/library_600x900.jpg"],
            "rust": ["https://cdn.cloudflare.steamstatic.com/steam/apps/252490/library_600x900.jpg"],
            "elden_ring": ["https://cdn.cloudflare.steamstatic.com/steam/apps/1245620/library_600x900.jpg"],
            "cyberpunk_2077": ["https://cdn.cloudflare.steamstatic.com/steam/apps/1091500/library_600x900.jpg"],
            "resident_evil_2": ["https://cdn.cloudflare.steamstatic.com/steam/apps/883710/library_600x900.jpg"],
            "ultrakill": ["https://cdn.cloudflare.steamstatic.com/steam/apps/1229490/library_600x900.jpg"],
            "god_of_war": ["https://cdn.cloudflare.steamstatic.com/steam/apps/1593500/library_600x900.jpg"],
            "hogwarts_legacy": ["https://cdn.cloudflare.steamstatic.com/steam/apps/990080/library_600x900.jpg"],
            "rocket_league": ["https://cdn.cloudflare.steamstatic.com/steam/apps/252950/library_600x900.jpg"],
            "among_us": ["https://cdn.cloudflare.steamstatic.com/steam/apps/1030300/library_600x900.jpg"],
            "fall_guys": ["https://cdn.cloudflare.steamstatic.com/steam/apps/1097150/library_600x900.jpg"],
            "terraria": ["https://cdn.cloudflare.steamstatic.com/steam/apps/105600/library_600x900.jpg"],
            "stardew_valley": ["https://cdn.cloudflare.steamstatic.com/steam/apps/413150/library_600x900.jpg"],
            "it_takes_two": ["https://cdn.cloudflare.steamstatic.com/steam/apps/1426210/library_600x900.jpg"],
            "hollow_knight": ["https://cdn.cloudflare.steamstatic.com/steam/apps/367520/library_600x900.jpg"],
        }
        if slug in table:
            return table[slug]
        for key, urls in table.items():
            if key in slug or slug in key:
                return urls
        return []

    def _famous_done(self, path: str | None) -> None:
        if path:
            self._apply_cover_file(path)
            return
        self._exe_chain()

    def _exe_chain(self) -> None:
        if self._exe_path:
            pixmap = self._exe_icon_pixmap()
            if pixmap is not None and not pixmap.isNull():
                self._apply_cover_pixmap(pixmap)
                return
        if not self._steam_tried and self._search_title:
            self._steam_tried = True
            self._try_steam_search()
            return

    def _cover_chain_done(self, path: str | None) -> None:
        try:
            if path:
                pixmap = QPixmap(path)
                if not pixmap.isNull():
                    self._apply_cover_pixmap(pixmap)
                    return
            self._exe_chain()
        except RuntimeError:
            log.debug("Cover chain on deleted card ignored")

    def _exe_icon_pixmap(self):
        try:
            from utils.exe_icon import extract_exe_icon
            return extract_exe_icon(self._exe_path, 256)
        except Exception:
            log.debug("exe icon extraction failed", exc_info=True)
            return None

    def _try_steam_search(self) -> None:
        term = quote(self._search_title.strip())
        if not term:
            return
        url = QUrl(_STEAM_SEARCH_URL.format(term=term))
        request = QNetworkRequest(url)
        request.setTransferTimeout(_TRANSFER_TIMEOUT_MS)
        reply = _network().get(request)

        def _on_search() -> None:
            try:
                data = json.loads(bytes(reply.readAll()).decode("utf-8", "replace"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                return
            items = data.get("items") or []
            if not items:
                return
            appid = items[0].get("id")
            if not appid:
                return
            header = (f"https://cdn.cloudflare.steamstatic.com/"
                      f"steam/apps/{appid}/header.jpg")
            load_remote_image([header], self._cover_chain_done)

        reply.finished.connect(_on_search)

    def _apply_cover_file(self, path: str) -> None:
        try:
            pixmap = QPixmap(path)
            if pixmap.isNull():
                return
            self._apply_cover_pixmap(pixmap)
        except RuntimeError:
            log.debug("Cover callback on deleted card ignored")

    def _apply_cover_pixmap(self, pixmap: QPixmap) -> None:
        try:
            self._cover.setPixmap(
                rounded_pixmap(pixmap, QSize(self.COVER_W, self.COVER_H), self.RADIUS))
            if self._chip is not None:
                self._chip.raise_()
        except RuntimeError:
            log.debug("Cover update on deleted card ignored")

    def set_custom_image(self, source_path: str) -> None:
        try:
            custom_dir = Path(QStandardPaths.writableLocation(
                QStandardPaths.StandardLocation.AppDataLocation)) / "covers" / "custom"
            custom_dir.mkdir(parents=True, exist_ok=True)
            target = custom_dir / f"{self._game_id}.img"
            target.write_bytes(Path(source_path).read_bytes())
            pixmap = QPixmap(str(target))
            if not pixmap.isNull():
                self._apply_cover_pixmap(pixmap)
        except (OSError, RuntimeError):
            log.exception("Custom image failed")

    def _set_hover(self, value: float) -> None:
        self._hover = float(value)
        self.update()

    def enterEvent(self, event) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._hover)
        self._anim.setEndValue(1.0)
        self._anim.start()
        sweep = QVariantAnimation(self)
        sweep.setStartValue(0.0)
        sweep.setEndValue(1.0)
        sweep.setDuration(600)
        sweep.valueChanged.connect(self._set_sweep)
        sweep.finished.connect(sweep.deleteLater)
        self._sweep_anim = sweep
        sweep.start()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._hover)
        self._anim.setEndValue(0.0)
        self._anim.start()
        super().leaveEvent(event)

    def _set_sweep(self, value: float) -> None:
        self._sweep = float(value)
        self.update()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._game_id)
        super().mousePressEvent(event)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self._hover > 0.01:
            painter.setPen(QPen(QColor(255, 255, 255, int(90 * self._hover)), 1.0))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1),
                                    self.RADIUS + 2, self.RADIUS + 2)
        if self._sweep > 0.001:
            band_w = self.width() * 0.4
            x = -band_w + (self.width() + 2 * band_w) * self._sweep
            grad = QLinearGradient(x, 0.0, x + band_w, float(self.height()))
            grad.setColorAt(0.0, QColor(255, 255, 255, 0))
            grad.setColorAt(0.5, QColor(255, 255, 255, 80))
            grad.setColorAt(1.0, QColor(255, 255, 255, 0))
            painter.save()
            clip = QPainterPath()
            clip.addRoundedRect(1.0, 1.0, float(self.width() - 2),
                                float(self.height() - 2),
                                self.RADIUS + 2, self.RADIUS + 2)
            painter.setClipPath(clip)
            painter.fillRect(self.rect(), grad)
            painter.restore()