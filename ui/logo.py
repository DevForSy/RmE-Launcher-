from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QFont, QIcon, QLinearGradient,
                           QPainter, QPainterPath, QPen, QPixmap)
_ASSET_CANDIDATES = (
    Path(__file__).resolve().parent.parent / "assets" / "logo.png",
    Path(__file__).resolve().parent.parent / "logo.png",
)

_CACHE: dict[int, QPixmap] = {}


def _square_fit(source: QPixmap, size: int) -> QPixmap:
    out = QPixmap(size, size)
    out.fill(Qt.GlobalColor.transparent)
    if source.isNull():
        return out
    painter = QPainter(out)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    scaled = source.scaled(size, size,
                           Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                           Qt.TransformationMode.SmoothTransformation)
    dx = (scaled.width() - size) // 2
    dy = (scaled.height() - size) // 2
    painter.drawPixmap(-dx, -dy, scaled)
    painter.end()
    return out


def _circle_fit(source: QPixmap, size: int) -> QPixmap:
    out = QPixmap(size, size)
    out.fill(Qt.GlobalColor.transparent)
    if source.isNull():
        return out
    painter = QPainter(out)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    clip = QPainterPath()
    clip.addEllipse(0.0, 0.0, float(size), float(size))
    painter.setClipPath(clip)
    scaled = source.scaled(size, size,
                           Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                           Qt.TransformationMode.SmoothTransformation)
    dx = (scaled.width() - size) // 2
    dy = (scaled.height() - size) // 2
    painter.drawPixmap(-dx, -dy, scaled)
    painter.setPen(QPen(QColor(255, 255, 255, 30), 1.0))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawEllipse(QRectF(0.5, 0.5, size - 1, size - 1))
    painter.end()
    return out


def _vector_logo(size: int) -> QPixmap:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    grad = QLinearGradient(0.0, 0.0, 0.0, float(size))
    grad.setColorAt(0.0, QColor("#F5F5F7"))
    grad.setColorAt(1.0, QColor("#C7C7CC"))
    painter.setBrush(QBrush(grad))
    painter.setPen(QPen(QColor(0, 0, 0, 28), size * 0.02))
    painter.drawEllipse(QRectF(size * 0.04, size * 0.04,
                               size * 0.92, size * 0.92))

    font = QFont()
    font.setFamilies(["SF Pro Display", "Segoe UI", "Helvetica Neue", "Arial"])
    font.setPixelSize(int(size * 0.46))
    font.setBold(True)
    painter.setFont(font)
    painter.setPen(QColor("#0A0A0C"))
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "R")

    painter.end()
    return pixmap


def logo_pixmap(size: int = 22) -> QPixmap:
    size = max(8, int(size))
    if size in _CACHE:
        return _CACHE[size]

    for candidate in _ASSET_CANDIDATES:
        if candidate.is_file():
            art = QPixmap(str(candidate))
            if not art.isNull():
                scaled = _circle_fit(art, size)
                _CACHE[size] = scaled
                return scaled

    pixmap = _vector_logo(size)
    _CACHE[size] = pixmap
    return pixmap


def logo_splash_pixmap(size: int = 96) -> QPixmap:
    out = QPixmap(size, int(size * 1.34))
    out.fill(Qt.GlobalColor.transparent)
    painter = QPainter(out)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

    logo = logo_pixmap(size)
    lx = (size - logo.width()) // 2
    painter.drawPixmap(lx, 0, logo)

    font_title = QFont("Segoe UI Semibold", max(9, int(size * 0.11)))
    font_title.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, size * 0.030)
    painter.setFont(font_title)
    painter.setPen(QColor("#F5F5F7"))
    title_rect = QRectF(0, float(size) + 8, float(size), size * 0.20)
    painter.drawText(title_rect,
                     Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                     "RME")

    font_sub = QFont("Segoe UI", max(7, int(size * 0.08)))
    font_sub.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, size * 0.050)
    painter.setFont(font_sub)
    painter.setPen(QColor("#A1A1A6"))
    sub_rect = QRectF(0, float(size) + 8 + size * 0.22, float(size), size * 0.18)
    painter.drawText(sub_rect,
                     Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                     "LAUNCHER")

    painter.end()
    return out


def app_icon() -> QIcon:
    return QIcon(logo_pixmap(64))