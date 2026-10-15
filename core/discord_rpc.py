from __future__ import annotations

import contextlib
import json
import logging
import os
import struct
import sys
import threading
import time
import uuid

from PySide6.QtCore import QObject, QThread

log = logging.getLogger(__name__)

IS_WINDOWS = sys.platform == "win32"
DISCORD_CLIENT_ID: int = 1560291914253598852

IDLE_ACTIVITY = {"details": "Browsing the library", "state": "Using RmE Launcher"}
USE_ASSETS = True
ASSET_KEY = "polar"

OP_HANDSHAKE, OP_FRAME, OP_CLOSE, OP_PING, OP_PONG = 0, 1, 2, 3, 4


class _IpcWorker(QThread):
    def __init__(self, client_id: int) -> None:
        super().__init__()
        self._client_id = client_id
        self._pending: dict | None = None
        self._clearing = False
        self._stopping = False
        self._use_assets = USE_ASSETS
        self._lock = threading.Lock()

    def set_activity(self, payload: dict) -> None:
        with self._lock:
            self._pending = payload

    def clear_to_idle(self) -> None:
        with self._lock:
            self._clearing = True

    def stop(self) -> None:
        self._stopping = True

    def run(self) -> None:
        log.info("[RPC] worker started")
        while not self._stopping:
            fd = self._connect()
            if fd is None:
                log.info("[RPC] Discord pipe not found (desktop app running?) - retry 15s")
                self._sleep(15000)
                continue
            try:
                self._pump(fd)
            except OSError as exc:
                log.info("[RPC] connection dropped: %s", exc)
            finally:
                with contextlib.suppress(OSError):
                    os.close(fd)
            if not self._stopping:
                self._sleep(3000)

    def _sleep(self, ms: int) -> None:
        for _ in range(0, ms, 250):
            if self._stopping:
                return
            self.msleep(min(250, ms))

    def _connect(self) -> int | None:
        for i in range(10):
            try:
                fd = os.open(rf"\\.\pipe\discord-ipc-{i}",
                             os.O_RDWR | getattr(os, "O_BINARY", 0))
            except OSError:
                continue
            try:
                self._write(fd, OP_HANDSHAKE, {"v": 1, "client_id": str(self._client_id)})
                op, payload = self._read_frame(fd)
                evt, data = self._decode(payload)
                if op == OP_CLOSE:
                    log.error("[RPC] Discord REJECTED the handshake (client_id=%s): %s",
                              self._client_id, data)
                    with contextlib.suppress(OSError):
                        os.close(fd)
                    return None
                log.info("[RPC] handshake ACCEPTED - application id is valid")
                return fd
            except OSError as exc:
                log.warning("[RPC] handshake failed on ipc-%s: %s", i, exc)
                with contextlib.suppress(OSError):
                    os.close(fd)
        return None

    def _decode(self, payload: bytes) -> tuple[str | None, dict]:
        try:
            data = json.loads(payload.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None, {}
        if isinstance(data, dict):
            return data.get("evt"), data.get("data") or {}
        return None, {}

    def _read_frame(self, fd: int) -> tuple[int, bytes]:
        header = b""
        while len(header) < 8:
            chunk = os.read(fd, 8 - len(header))
            if not chunk:
                raise OSError("Discord closed the pipe")
            header += chunk
        op, length = struct.unpack("<II", header)
        payload = b""
        while len(payload) < length:
            chunk = os.read(fd, min(4096, length - len(payload)))
            if not chunk:
                raise OSError("Discord closed the pipe mid-frame")
            payload += chunk
        return op, payload

    def _write(self, fd: int, op: int, payload: dict) -> None:
        data = json.dumps(payload).encode("utf-8")
        os.write(fd, struct.pack("<II", op, len(data)) + data)

    def _request(self, fd: int, payload: dict) -> tuple[str | None, dict]:
        self._write(fd, OP_FRAME, payload)
        while True:
            op, raw = self._read_frame(fd)
            if op == OP_CLOSE:
                raise OSError(f"Discord sent CLOSE: {raw[:200]!r}")
            evt, data = self._decode(raw)
            if evt == "ERROR":
                return "ERROR", data
            if evt is None:
                return None, data
            log.info("[RPC] event: %s", evt)

    def _activity(self, payload: dict) -> dict:
        activity = {
            "details": payload.get("details", ""),
            "state": payload.get("state", ""),
            "timestamps": {"start": int(time.time())},
            "instance": False,
        }
        if self._use_assets:
            activity["assets"] = {"large_image": ASSET_KEY,
                                  "large_text": "RmE Launcher"}
        return {"cmd": "SET_ACTIVITY",
                "args": {"pid": os.getpid(), "activity": activity},
                "nonce": str(uuid.uuid4())}

    def _send_activity(self, fd: int, payload: dict) -> None:
        evt, data = self._request(fd, self._activity(payload))
        if evt == "ERROR":
            message = str(data.get("message", "")).casefold()
            code = data.get("code")
            log.error("[RPC] SET_ACTIVITY REJECTED (code=%s): %s", code, message)
            if self._use_assets and ("asset" in message or "image" in message):
                log.warning("[RPC] asset '%s' rejected - retrying WITHOUT assets. "
                            "Permanent fix: upload an image in the Developer Portal "
                            "under Rich Presence Assets with the name '%s'.",
                            ASSET_KEY, ASSET_KEY)
                self._use_assets = False
                evt2, _data2 = self._request(fd, self._activity(payload))
                if evt2 is None:
                    log.info("[RPC] activity ACCEPTED without assets - it should show now")
            return
        log.info("[RPC] activity ACCEPTED by Discord: %r / %r",
                 payload.get("details", ""), payload.get("state", ""))

    def _pump(self, fd: int) -> None:
        self._send_activity(fd, dict(IDLE_ACTIVITY))
        last_beat = time.monotonic()
        while not self._stopping:
            with self._lock:
                pending, clearing = self._pending, self._clearing
                self._pending, self._clearing = None, False
            if pending is not None:
                self._send_activity(fd, pending)
            elif clearing:
                self._send_activity(fd, dict(IDLE_ACTIVITY))
            elif time.monotonic() - last_beat >= 15.0:
                self._write(fd, OP_PING, {"nonce": str(uuid.uuid4())})
                with contextlib.suppress(OSError):
                    self._read_frame(fd)
                last_beat = time.monotonic()
            self._sleep(500)


class DiscordRPC(QObject):
    def __init__(self, client_id: int = DISCORD_CLIENT_ID,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._worker = _IpcWorker(client_id) if client_id and IS_WINDOWS else None
        if self._worker:
            self._worker.start(QThread.Priority.LowPriority)

    def set_activity(self, details: str, state: str) -> None:
        if self._worker:
            self._worker.set_activity({"details": details, "state": state})

    def clear_to_idle(self) -> None:
        if self._worker:
            self._worker.clear_to_idle()

    def shutdown(self) -> None:
        if self._worker:
            self._worker.stop()
            self._worker.wait(3000)