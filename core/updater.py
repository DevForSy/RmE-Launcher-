from __future__ import annotations

import json
import logging

from PySide6.QtCore import QUrl
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

log = logging.getLogger(__name__)

APP_VERSION = "1.0.0"
UPDATE_URL = ("https://raw.githubusercontent.com/"
              "اسم_حسابك/اسم_المستودع/main/latest.json")

_TIMEOUT_MS = 10_000


def _parse_version(value: str) -> tuple[int, ...]:
    try:
        return tuple(int(p) for p in str(value).strip().lstrip("vV").split("."))
    except (ValueError, AttributeError):
        return ()


class UpdateChecker:
    def __init__(self) -> None:
        self._nam = QNetworkAccessManager()

    def check(self, on_result) -> None:
        """on_result(has_update: bool, latest_url: str, notes: str)."""
        request = QNetworkRequest(QUrl(UPDATE_URL))
        request.setTransferTimeout(_TIMEOUT_MS)
        reply = self._nam.get(request)

        def _done() -> None:
            reply.deleteLater()
            if reply.error() != reply.error().NoError:
                log.info("Update check skipped (offline): %s", reply.error())
                on_result(False, "", "")
                return
            try:
                data = json.loads(bytes(reply.readAll()).decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                log.warning("Update manifest unreadable: %s", exc)
                on_result(False, "", "")
                return
            remote = _parse_version(data.get("version", ""))
            local = _parse_version(APP_VERSION)
            latest_url = str(data.get("url", ""))
            notes = str(data.get("notes", ""))
            if remote > local and latest_url:
                on_result(True, latest_url, notes)
            else:
                on_result(False, "", "")

        reply.finished.connect(_done)