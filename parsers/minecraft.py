import logging
import re
import os
from pathlib import Path

try:
    import winreg
except ImportError:
    winreg = None

from parsers.base import GameEntry, GameParser

log = logging.getLogger(__name__)

_UNINSTALL_HIVES = (
    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
    (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
) if winreg is not None else ()

_LAUNCHER_EXE_NAMES = ("Minecraft Launcher.exe", "MinecraftLauncher.exe")

_PURE_VERSION = re.compile(r"^\d+(\.\d+)*$")


def _official_launcher_exe() -> Path | None:
    if winreg is not None:
        for hive, path in _UNINSTALL_HIVES:
            try:
                with winreg.OpenKey(hive, path) as root:
                    index = 0
                    while True:
                        try:
                            sub_name = winreg.EnumKey(root, index)
                        except OSError:
                            break
                        index += 1
                        try:
                            with winreg.OpenKey(root, sub_name) as sub:
                                display, _ = winreg.QueryValueEx(sub, "DisplayName")
                                if "minecraft launcher" not in str(display).casefold():
                                    continue
                                icon, _ = winreg.QueryValueEx(sub, "DisplayIcon")
                        except OSError:
                            continue
                        exe = str(icon).split(",")[0].strip().strip('"')
                        if exe.casefold().endswith(".exe") and Path(exe).is_file():
                            return Path(exe)
            except OSError:
                continue

    pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    local = os.environ.get("LOCALAPPDATA", "")
    candidates: list[Path] = []
    for base in (Path(pf86), Path(pf), Path(local) / "Programs"):
        for name in _LAUNCHER_EXE_NAMES:
            candidates.append(base / "Minecraft Launcher" / name)
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _mc_dir() -> Path | None:
    override = os.environ.get("RME_MC_DIR")
    if override and Path(override).is_dir():
        return Path(override)
    appdata = os.environ.get("APPDATA", "")
    default = Path(appdata) / ".minecraft" if appdata else None
    if default is not None and default.is_dir():
        return default
    return None


def _installed_versions(mc: Path | None) -> list[str]:
    if mc is None:
        return []
    versions_root = mc / "versions"
    if not versions_root.is_dir():
        return []
    out: list[str] = []
    try:
        for vdir in sorted(versions_root.iterdir()):
            if not vdir.is_dir():
                continue
            name = vdir.name
            if (vdir / f"{name}.jar").is_file() and (vdir / f"{name}.json").is_file():
                out.append(name)
    except OSError:
        pass
    return out


def _best_version(versions: list[str]) -> str | None:
    if not versions:
        return None
    if len(versions) == 1:
        return versions[0]
    releases: list[tuple[int, ...]] = []
    for name in versions:
        if _PURE_VERSION.match(name):
            try:
                releases.append(tuple(int(p) for p in name.split(".")))
            except ValueError:
                continue
    if releases:
        best = max(releases)
        return ".".join(str(p) for p in best)
    return None


class MinecraftParser(GameParser):
    source = "minecraft"

    def __init__(self) -> None:
        super().__init__()
        self._exe: Path | None = None

    def is_available(self) -> bool:
        if self._exe is None:
            self._exe = _official_launcher_exe()
        return self._exe is not None

    def scan(self) -> list[GameEntry]:
        self.errors.clear()
        if not self.is_available() or self._exe is None:
            return []
        mc = _mc_dir()
        versions = _installed_versions(mc)
        best = _best_version(versions)
        launch_args: list[str] = []
        if best:
            launch_args = ["--launch", best]
        out = [GameEntry(
            source=self.source,
            platform_id="official-launcher",
            title="Minecraft",
            install_path=self._exe.parent,
            executable_path=self._exe,
            launch_uri=None,
            launch_args=launch_args,
            cover_urls=[],
            hero_urls=[],
            state_flags=4,
            extra={
                "game_exe_name": self._exe.name,
                "mc_dir": str(mc) if mc else "",
                "mc_versions": versions,
                "watch_mode": "pid",
            },
        )]
        log.info("Minecraft parser: launcher at %s, %d version(s), auto-launch=%s",
                 self._exe, len(versions), best or "off (menu)")
        return out