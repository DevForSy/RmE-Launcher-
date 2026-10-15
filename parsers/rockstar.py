import logging
from pathlib import Path

try:
    import winreg
except ImportError:
    winreg = None

from parsers.base import GameEntry, GameParser

log = logging.getLogger(__name__)

_REG_ROOT = r"SOFTWARE\WOW6432Node\Rockstar Games"
_SKIP_KEYS = ("launcher", "social club")
_BLOCKED_EXE = ("uninstall", "setup", "launcher", "socialclub",
                "installscript", "redist", "crash", "dxsetup")


def _art_for(name: str) -> list[str]:
    low = name.casefold()
    if "red dead redemption 2" in low or "red dead redemption ii" in low:
        return ["https://www.rockstargames.com/reddeadredemption2/"]
    if "red dead" in low:
        return ["https://www.rockstargames.com/reddeadredemption/"]
    if "grand theft auto v" in low:
        return ["https://www.rockstargames.com/V/"]
    if "grand theft auto" in low:
        return ["https://www.rockstargames.com/"]
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


class RockstarParser(GameParser):
    source = "rockstar"

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
                if any(s in name.casefold() for s in _SKIP_KEYS):
                    continue
                try:
                    with winreg.OpenKey(root, name) as key:
                        folder, _ = winreg.QueryValueEx(key, "InstallFolder")
                    install = Path(str(folder))
                except OSError:
                    continue
                if not install.is_dir():
                    continue
                exe = _find_game_exe(install)
                if exe is None:
                    self.errors.append(f"Rockstar '{name}': no executable under {install}")
                    continue
                art = _art_for(name)
                out.append(GameEntry(
                    source=self.source,
                    platform_id=name.casefold(),
                    title=name,
                    install_path=install,
                    executable_path=exe,
                    cover_urls=list(art),
                    hero_urls=list(art),
                    state_flags=4,
                    extra={"game_exe_name": exe.name},
                ))
        log.info("Rockstar parser: %d title(s)", len(out))
        return out