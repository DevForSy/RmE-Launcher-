from __future__ import annotations

import sys

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import (QColor, QFont, QLinearGradient, QPainter, QPen,
                           QPixmap, QRadialGradient)
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QLabel, QPushButton,
                               QWidget)

from ui.logo import logo_pixmap

ACCENT = "#F5F5F7"
TEXT_PRIMARY = "#F5F5F7"
TEXT_SECONDARY = "#A1A1A6"
TEXT_MUTED = "#6E6E73"

SOURCE_LABELS = {
    "steam": "Steam", "epic": "Epic Games", "ea": "EA App",
    "ubisoft": "Ubisoft Connect", "gog": "GOG Galaxy", "generic": "Other",
    "riot": "Riot Games", "rockstar": "Rockstar Games",
    "battlenet": "Battle.net", "minecraft": "Minecraft",
    "bethesda": "Bethesda", "manual": "Manual Add",
    "roblox": "Roblox",
}


class GlassBackdrop(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._custom: QPixmap | None = None
        self._load_custom()

    def _load_custom(self) -> None:
        from ui.background_manager import background_path
        path = background_path()
        pixmap = QPixmap(str(path)) if path.is_file() else QPixmap()
        self._custom = None if pixmap.isNull() else pixmap
        self.update()

    def reload_custom(self) -> None:
        self._load_custom()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        w, h = float(self.width()), float(self.height())

        base = QLinearGradient(0.0, 0.0, 0.0, h)
        base.setColorAt(0.0, QColor(0x11, 0x11, 0x13))
        base.setColorAt(0.5, QColor(0x0B, 0x0B, 0x0D))
        base.setColorAt(1.0, QColor(0x06, 0x06, 0x08))
        painter.fillRect(self.rect(), base)

        if self._custom is not None:
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            scaled = self._custom.scaled(
                self.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation)
            dx = max(0, (scaled.width() - self.width()) // 2)
            dy = max(0, (scaled.height() - self.height()) // 2)
            painter.drawPixmap(-dx, -dy, scaled)
            painter.fillRect(self.rect(), QColor(0, 0, 0, 172))

        glow = QRadialGradient(w * 0.50, h * -0.10, w * 0.75)
        glow.setColorAt(0.0, QColor(255, 255, 255, 14))
        glow.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.fillRect(self.rect(), glow)
        painter.end()


class _TrafficButton(QPushButton):
    def __init__(self, color: str, symbol: str, on_click, parent: QWidget) -> None:
        super().__init__(parent)
        self._color = color
        self._symbol = symbol
        self.setFixedSize(12, 12)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clicked.connect(on_click)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(self._color))
        painter.drawEllipse(QRectF(0.5, 0.5, 11, 11))
        if self.underMouse():
            painter.setPen(QPen(QColor(0, 0, 0, 150), 1.4))
            font = QFont()
            font.setPixelSize(8)
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                             self._symbol)


class GlassTitleBar(QWidget):
    def __init__(self, on_min, on_max, on_close, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("TitleBar")
        self.setFixedHeight(48)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 0, 16, 0)
        layout.setSpacing(0)

        left = QWidget()
        left.setFixedWidth(72)
        layout.addWidget(left)

        center = QWidget()
        cl = QHBoxLayout(center)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(8)
        cl.addStretch(1)
        mark = QLabel()
        mark.setPixmap(logo_pixmap(26))
        mark.setFixedSize(26, 26)
        cl.addWidget(mark)
        name = QLabel("RME LAUNCHER")
        name.setObjectName("BrandMark")
        cl.addWidget(name)
        cl.addStretch(1)
        layout.addWidget(center, 1)

        lights = QWidget()
        lights.setFixedWidth(72)
        ll = QHBoxLayout(lights)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(8)
        ll.addStretch(1)
        ll.addWidget(_TrafficButton("#FF5F57", "\u2715", on_close, lights))
        ll.addWidget(_TrafficButton("#FEBC2E", "\u2013", on_min, lights))
        ll.addWidget(_TrafficButton("#28C840", "\u25A1", on_max, lights))
        layout.addWidget(lights)


APP_QSS = """
* { outline: none; font-family: "Segoe UI", "Helvetica Neue", Arial; }
QMainWindow { background: #050506; }

#TitleBar { background: transparent;
            border-bottom: 1px solid rgba(255,255,255,0.05); }
#BrandMark { color: #F5F5F7; font-size: 10pt; font-weight: 600;
             letter-spacing: 3px; }

#SectionLabel { color: #6E6E73; font-size: 8.5pt; font-weight: 600;
                letter-spacing: 2.5px; }
#HeaderChip   { color: #F5F5F7; background: rgba(255,255,255,0.05);
                border: 1px solid rgba(255,255,255,0.07); border-radius: 14px;
                padding: 5px 14px; font-size: 9pt; font-weight: 500; }

QComboBox { background: rgba(255,255,255,0.05);
            border: 1px solid rgba(255,255,255,0.06); border-radius: 12px;
            padding: 7px 12px; color: #F5F5F7; font-size: 9pt;
            min-width: 150px; }
QComboBox:hover { border-color: rgba(255,255,255,0.18); }
QComboBox::drop-down { border: none; width: 22px; }
QComboBox::down-arrow { image: none; border-left: 4px solid transparent;
                        border-right: 4px solid transparent;
                        border-top: 5px solid #A1A1A6; margin-right: 8px; }
QComboBox QAbstractItemView { background: #141416;
    border: 1px solid rgba(255,255,255,0.10); border-radius: 12px;
    selection-background-color: rgba(255,255,255,0.12);
    selection-color: #F5F5F7; color: #D1D1D6; outline: none; padding: 4px; }
QComboBox QAbstractItemView::item { min-height: 26px; border-radius: 8px;
                                    padding: 2px 8px; }

#NavButton { text-align: center; color: #A1A1A6; background: transparent;
             border: 1px solid rgba(255,255,255,0.10); border-radius: 14px;
             padding: 7px 22px; font-size: 9.5pt; font-weight: 500; }
#NavButton:hover   { background: rgba(255,255,255,0.08); color: #F5F5F7; }
#NavButton:checked { background: #F5F5F7; border: 1px solid #F5F5F7;
                     color: #0A0A0C; font-weight: 600; }

#SearchBox { background: rgba(255,255,255,0.05);
             border: 1px solid rgba(255,255,255,0.06); border-radius: 14px;
             padding: 8px 14px; color: #F5F5F7; font-size: 9.5pt;
             selection-background-color: #48484A; }
#SearchBox:focus { border: 1px solid rgba(255,255,255,0.35);
                   background: rgba(255,255,255,0.08); }
#CountLabel { color: #6E6E73; font-size: 9pt; }

#WinButton { background: rgba(255,255,255,0.05); color: #D1D1D6; border: none;
             border-radius: 10px; }
#WinButton:hover  { background: rgba(255,255,255,0.13); color: #F5F5F7; }

QListWidget { background: transparent; border: none; }
QListWidget::item { border: none; }
QListWidget::item:selected { background: transparent; }
QScrollBar:vertical { background: transparent; width: 8px; margin: 4px 2px 4px 0; }
QScrollBar::handle:vertical { background: rgba(255,255,255,0.12);
                              border-radius: 4px; min-height: 40px; }
QScrollBar::handle:vertical:hover { background: rgba(255,255,255,0.24); }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }

#GameCard { background: #141416;
            border: 1px solid rgba(255,255,255,0.06); border-radius: 10px; }
#GameCard:hover { border: 1px solid rgba(255,255,255,0.22); }
#CardTitle { color: #F5F5F7; font-size: 11pt; font-weight: 600;
             font-family: "Segoe UI Semibold", "Segoe UI"; }
#CardMeta  { color: #A1A1A6; font-size: 8.5pt; }
#PlaytimeChip { color: #F5F5F7; background: rgba(0,0,0,220);
                border: 1px solid rgba(255,255,255,0.14); border-radius: 9px;
                padding: 2px 9px; font-size: 8pt; font-weight: 600; }

#CardPlayBtn { background: #F5F5F7; color: #0A0A0C; border: none;
               border-radius: 8px; padding: 4px 14px;
               font-size: 8.5pt; font-weight: 700; letter-spacing: 1px; }
#CardPlayBtn:hover  { background: #FFFFFF; }
#CardPlayBtn:pressed{ background: #D1D1D6; }
#CardStopBtn { background: rgba(255,107,94,0.14); color: #FF6B5E; border: none;
               border-radius: 8px; padding: 4px 12px;
               font-size: 8.5pt; font-weight: 700; letter-spacing: 1px; }
#CardStopBtn:hover  { background: rgba(255,107,94,0.26); }
#CardStopBtn:pressed{ background: rgba(255,107,94,0.34); }
#CardRemoveBtn { background: rgba(255,255,255,0.05); color: #A1A1A6;
                 border: none; border-radius: 8px; }
#CardRemoveBtn:hover  { background: rgba(255,106,94,0.14); color: #FF6B5E; }

#LoadingBrand { color: #F5F5F7; font-size: 14pt; font-weight: 600;
                letter-spacing: 8px; }
#LoadingStatus { color: #6E6E73; font-size: 9pt; }
#LoadingCredit { color: #232326; font-size: 7.5pt; letter-spacing: 2px; }

QToolTip { background: #141416; color: #F5F5F7;
           border: 1px solid rgba(255,255,255,0.12); padding: 6px 10px;
           border-radius: 10px; }
"""


def apply_app_style(app: QApplication) -> None:
    app.setStyle("Fusion")
    if sys.platform == "win32":
        font = QFont()
        font.setFamilies(["Segoe UI Variable Display", "Segoe UI",
                          "Helvetica Neue", "Arial"])
        font.setPointSize(9)
        font.setWeight(QFont.Weight.DemiBold)
        app.setFont(font)
    app.setStyleSheet(APP_QSS)