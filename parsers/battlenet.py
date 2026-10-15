import logging
from pathlib import Path

try:
    import winreg
except ImportError:
    winreg = None

from parsers.base import GameEntry, GameParser

log = logging.getLogger(__name__)

_REG_ROOT = r"SOFTWARE\WOW6432Node\Blizzard Entertainment"
_SKIP_KEYS = ("battle.net", "agent")
_BLOCKED_EXE = ("battle.net", "battle_net", "agent.exe", "uninstall", "setup",
                "crash", "report", "blizzerror", "blizzard error")


def _art_for(name: str) -> list[str]:
    low = name.casefold()
    if "world of warcraft" in low:
        return ["https://worldofwarcraft.blizzard.com/"]
    if "overwatch" in low:
        return ["https://overwatch.blizzard.com/"]
    if "diablo iv" in low:
        return ["https://diablo4.blizzard.com/"]
    if "diablo iii" in low:
        return ["https://diablo3.blizzard.com/"]
    if "hearthstone" in low:
        return ["https://hearthstone.blizzard.com/"]
    if "starcraft" in low:
        return ["https://starcraft2.blizzard.com/"]
    if "call of duty" in low:
        return ["https://www.callofduty.com/"]
    if "destiny 2" in low:
        return ["https://www.destinythegame.com/"]
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


class BnetParser(GameParser):
    source = "battlenet"

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
                        folder, _ = winreg.QueryValueEx(key, "InstallPath")
                    install = Path(str(folder))
                except OSError:
                    continue
                if not install.is_dir():
                    continue
                exe = _find_game_exe(install)
                if exe is None:
                    self.errors.append(f"Battle.net '{name}': no executable under {install}")
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
        log.info("Battle.net parser: %d title(s)", len(out))
        return out