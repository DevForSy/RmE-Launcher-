from __future__ import annotations

import logging
import os
from pathlib import Path

try:
    import winreg
except ImportError:
    winreg = None

from parsers.base import GameEntry, GameParser

log = logging.getLogger(__name__)

_PLAYER_NAME = "RobloxPlayerBeta.exe"


def _path_is_roblox(exe: Path) -> bool:
    parts = [p.casefold() for p in exe.parts]
    return any("roblox" in part for part in parts)


def _exe_from_versions() -> Path | None:
    local = os.environ.get("LOCALAPPDATA", "")
    if not local:
        return None
    versions_root = Path(local) / "Roblox" / "Versions"
    if not versions_root.is_dir():
        return None
    best = None
    try:
        for vdir in sorted(versions_root.iterdir()):
            if not vdir.is_dir():
                continue
            exe = vdir / _PLAYER_NAME
            if not exe.is_file():
                continue
            try:
                size = exe.stat().st_size
            except OSError:
                continue
            if best is None or size > best[0]:
                best = (size, exe)
    except OSError:
        pass
    return best[1] if best else None


def _exe_from_registry() -> Path | None:
    if winreg is None:
        return None
    hives = (
        (winreg.HKEY_CURRENT_USER,
         r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\roblox-player"),
        (winreg.HKEY_LOCAL_MACHINE,
         r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\roblox-player"),
    )
    for hive, path in hives:
        try:
            with winreg.OpenKey(hive, path) as key:
                icon, _ = winreg.QueryValueEx(key, "DisplayIcon")
            exe = str(icon).split(",")[0].strip().strip('"')
            if not exe.casefold().endswith(".exe"):
                continue
            candidate = Path(exe)
            if not candidate.is_file():
                continue
            if not _path_is_roblox(candidate):
                log.warning("Roblox registry entry points outside a Roblox "
                            "directory - rejected: %s", candidate)
                continue
            return candidate
        except OSError:
            continue
    return None


class RobloxParser(GameParser):
    source = "roblox"

    def __init__(self) -> None:
        super().__init__()
        self._exe = None

    def is_available(self) -> bool:
        if self._exe is None:
            self._exe = _exe_from_versions() or _exe_from_registry()
        return self._exe is not None

    def scan(self) -> list[GameEntry]:
        self.errors.clear()
        if not self.is_available() or self._exe is None:
            return []
        out = [GameEntry(
            source=self.source,
            platform_id="roblox-player",
            title="Roblox",
            install_path=self._exe.parent,
            executable_path=self._exe,
            launch_uri=None,
            cover_urls=[],
            hero_urls=[],
            state_flags=4,
            extra={"game_exe_name": self._exe.name},
        )]
        log.info("Roblox parser: player at %s", self._exe)
        return out