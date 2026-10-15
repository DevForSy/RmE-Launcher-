import logging
from pathlib import Path

try:
    import winreg
except ImportError:
    winreg = None

from parsers.base import GameEntry, GameParser

log = logging.getLogger(__name__)

_REG_ROOT = r"SOFTWARE\WOW6432Node\Bethesda Softworks"
_VALUE_NAMES = ("Install Path", "InstallPath", "Installed Path")
_BLOCKED_EXE = ("uninstall", "setup", "launcher", "redist", "crash", "dxsetup",
                "bethesda.net", "bnet", "installscript")


def _art_for(name: str) -> list[str]:
    low = name.casefold()
    if "starfield" in low:
        return ["https://bethesda.net/game/starfield"]
    if "skyrim" in low:
        return ["https://elderscrolls.bethesda.net/skyrim10/"]
    if "fallout" in low:
        return ["https://fallout.bethesda.net/"]
    if "doom" in low:
        return ["https://slayersclub.bethesda.net/"]
    if "dishonored" in low:
        return ["https://dishonored.bethesda.net/"]
    return []


def _find_game_exe(install: Path) -> Path | None:
    best: tuple[int, Path] | None = None
    for exe in install.rglob("*.exe"):
        low = exe.name.casefold()
        if any(b in low for b in _BLOCKED_EXE):
            continue
        try:
            size = exe.stat().st_size
        except OSError:
            continue
        if best is None or size > best[0]:
            best = (size, exe)
    return best[1] if best else None


class BethesdaParser(GameParser):
    source = "bethesda"

    def is_available(self) -> bool:
        if winreg is None:
            return False
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _REG_ROOT):
                return True
        except OSError:
            return False

    def scan(self) -> list[GameEntry]:
        self.errors.clear()
        out: list[GameEntry] = []
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _REG_ROOT) as root:
            index = 0
            while True:
                try:
                    name = winreg.EnumKey(root, index)
                except OSError:
                    break
                index += 1
                install = None
                try:
                    with winreg.OpenKey(root, name) as key:
                        for value_name in _VALUE_NAMES:
                            try:
                                folder, _ = winreg.QueryValueEx(key, value_name)
                                if folder:
                                    install = Path(str(folder))
                                    break
                            except OSError:
                                continue
                except OSError:
                    continue
                if install is None or not install.is_dir():
                    continue
                exe = _find_game_exe(install)
                if exe is None:
                    self.errors.append(f"Bethesda '{name}': no executable under {install}")
                    continue
                art = _art_for(name)
                out.append(GameEntry(
                    source=self.source,
                    platform_id=name.casefold().replace(" ", "_"),
                    title=name,
                    install_path=install,
                    executable_path=exe,
                    cover_urls=list(art),
                    hero_urls=list(art),
                    state_flags=4,
                    extra={"game_exe_name": exe.name},
                ))
        log.info("Bethesda parser: %d title(s)", len(out))
        return out