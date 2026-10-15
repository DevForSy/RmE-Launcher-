from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QStandardPaths
from PySide6.QtWidgets import (QCheckBox, QDialog, QDoubleSpinBox, QFrame,
                               QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
                               QWidget)

from core.settings import Settings


def _cache_dir() -> Path:
    base = Path(QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.AppDataLocation))
    return base / "covers"


class _Row(QFrame):
    def __init__(self, title: str, subtitle: str = "") -> None:
        super().__init__()
        self.setObjectName("SettingsRow")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(4)
        t = QLabel(title)
        t.setObjectName("SettingsTitle")
        t.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(t)
        if subtitle:
            s = QLabel(subtitle)
            s.setObjectName("SettingsSub")
            s.setWordWrap(True)
            layout.addWidget(s)


class SettingsDialog(QDialog):
    _QSS = """
        #SettingsCard { background: rgba(200,170,255,0.04);
            border: 1px solid rgba(200,170,255,0.09); border-radius: 16px; }
        #SettingsTitle { color: #EDE9F8; font-size: 10.5pt; font-weight: 600; }
        #SettingsSub { color: #9A8FB0; font-size: 8.5pt; }
        #SettingsNote { color: #6B6480; font-size: 8pt; }
        QCheckBox { color: #CFC5E8; font-size: 10pt; }
        QDoubleSpinBox { background: rgba(200,170,255,0.05);
            border: 1px solid rgba(200,170,255,0.10); border-radius: 10px;
            padding: 6px 10px; color: #EDE9F8; font-size: 9.5pt;
            selection-background-color: #6B3FD6; }
        QPushButton { border-radius: 10px; padding: 8px 18px;
            font-size: 9.5pt; font-weight: 600; border: none; }
    """

    def __init__(self, settings: Settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._settings = settings
        self.setWindowTitle("Settings")
        self.setModal(True)
        self.setFixedWidth(540)
        self.setStyleSheet(self._QSS)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 16)
        root.setSpacing(12)

        title = QLabel("SETTINGS")
        title.setStyleSheet("color:#EDE9F8; font-size:13pt; font-weight:700;"
                            " letter-spacing:4px;")
        root.addWidget(title)
        root.addSpacing(4)

        card1 = _Row("Riot auto-PLAY",
                     "After launching a Riot title, RmE presses PLAY inside the "
                     "Riot Client automatically (the mouse never moves). Turn off "
                     "if you prefer pressing PLAY yourself.")
        self._riot_check = QCheckBox("Enabled")
        self._riot_check.setChecked(settings.riot_clicker_enabled)
        wrap1 = QVBoxLayout(card1)
        wrap1.addWidget(self._riot_check)
        root.addWidget(card1)

        card2 = _Row("Splash duration",
                     "How long the loading screen stays, in seconds (0-15).")
        spin_row = QHBoxLayout()
        self._splash_spin = QDoubleSpinBox()
        self._splash_spin.setRange(0.0, 15.0)
        self._splash_spin.setSingleStep(0.5)
        self._splash_spin.setValue(settings.splash_min_seconds)
        self._splash_spin.setSuffix(" s")
        spin_row.addWidget(self._splash_spin)
        spin_row.addStretch(1)
        wrap2 = QVBoxLayout(card2)
        wrap2.addLayout(spin_row)
        root.addWidget(card2)

        card3 = _Row("Close button behaviour",
                     "ON: the X button hides RmE to the system tray and it keeps "
                     "running (quit from the tray menu). OFF: the X button exits.")
        self._tray_check = QCheckBox("Minimize to tray on close")
        self._tray_check.setChecked(settings.close_to_tray)
        wrap3 = QVBoxLayout(card3)
        wrap3.addWidget(self._tray_check)
        root.addWidget(card3)

        card4 = _Row("Theme", "Current theme: Violet Dusk. More themes in a "
                              "future update.")
        root.addWidget(card4)

        card5 = _Row("Cover art cache",
                     "Cached cover images downloaded for your library.")
        cache_row = QHBoxLayout()
        self._cache_label = QLabel(self._cache_size_text())
        self._cache_label.setObjectName("SettingsNote")
        clear_btn = QPushButton("Clear cache")
        clear_btn.setStyleSheet("background:#2E2745; color:#CFC5E8;")
        clear_btn.clicked.connect(self._clear_cache)
        cache_row.addWidget(self._cache_label)
        cache_row.addStretch(1)
        cache_row.addWidget(clear_btn)
        wrap5 = QVBoxLayout(card5)
        wrap5.addLayout(cache_row)
        root.addWidget(card5)

        root.addStretch(1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.setStyleSheet("background:#2E2745; color:#CFC5E8;")
        cancel.clicked.connect(self.reject)
        save = QPushButton("Save")
        save.setStyleSheet("background:#8B5CF6; color:#FFFFFF;")
        save.clicked.connect(self._save)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        root.addLayout(buttons)

    def _cache_size_text(self) -> str:
        total = 0
        cache = _cache_dir()
        if cache.is_dir():
            for f in cache.iterdir():
                try:
                    total += f.stat().st_size
                except OSError:
                    continue
        return f"{total / (1024 * 1024):.1f} MB used"

    def _clear_cache(self) -> None:
        cache = _cache_dir()
        if cache.is_dir():
            for f in cache.iterdir():
                try:
                    f.unlink()
                except OSError:
                    pass
        self._cache_label.setText(self._cache_size_text())

    def _save(self) -> None:
        self._settings.set("riot_clicker_enabled", self._riot_check.isChecked())
        self._settings.set("splash_min_seconds", float(self._splash_spin.value()))
        self._settings.set("close_to_tray", self._tray_check.isChecked())
        self.accept()

    @staticmethod
    def open_dialog(settings: Settings, parent: QWidget | None = None) -> bool:
        dialog = SettingsDialog(settings, parent)
        return dialog.exec() == QDialog.DialogCode.Accepted