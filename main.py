from __future__ import annotations

import logging
import sys

from PySide6.QtWidgets import QApplication

from core.database import Database
from core.settings import Settings
from ui.logo import app_icon
from ui.styles import apply_app_style
from ui.window import RmeLauncherWindow


def main() -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")

    app = QApplication(sys.argv)
    app.setOrganizationName("RmE HQ")
    app.setApplicationName("RmE Launcher")
    app.setWindowIcon(app_icon())

    db = Database.default()
    settings = Settings()
    apply_app_style(app)

    window = RmeLauncherWindow(db, settings)
    window._launch_splash()

    exit_code = app.exec()
    db.close()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())