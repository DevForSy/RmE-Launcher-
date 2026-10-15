import logging
from pathlib import Path

try:
    import winreg
except ImportError:
    winreg = None

from parsers.base import GameEntry, GameParser, guess_main_executable

log = logging.getLogger(__name__)


class _RegistryParser(GameParser):
    def _warn(self, message: str) -> None:
        log.warning(message)
        self.errors.append(message)

    def _enum_subkeys(self, hive: int, path: str) -> list[tuple[str, dict[str, str]]]:
        out: list[tuple[str, dict[str, str]]] = []
        if winreg is None:
            return out
        try:
            with winreg.OpenKey(hive, path, 0, winreg.KEY_READ) as key:
                index = 0
                while True:
                    try:
                        subkey_name = winreg.EnumKey(key, index)
                    except OSError:
                        break
                    index += 1
                    try:
                        with winreg.OpenKey(key, subkey_name) as subkey:
                            values: dict[str, str] = {}
                            v = 0
                            while True:
                                try:
                                    name, val, _ = winreg.EnumValue(subkey, v)
                                except OSError:
                                    break
                                v += 1
                                values[name] = str(val)
                            out.append((subkey_name, values))
                    except OSError:
                        continue
        except OSError:
            return []
        return out


class EAParser(_RegistryParser):
    source = "ea"

    def is_available(self) -> bool:
        if winreg is None:
            return False
        return any(self._enum_subkeys(winreg.HKEY_LOCAL_MACHINE, p)
                   for p in (r"SOFTWARE\WOW6432Node\EA Games",
                             r"SOFTWARE\WOW6432Node\Origin Games"))

    def scan(self) -> list[GameEntry]:
        self.errors.clear()
        out: list[GameEntry] = []
        roots = (
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\EA Games", "Install Dir"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Origin Games", "Install Path"),
        )
        for hive, path, value_name in roots:
            for slug, values in self._enum_subkeys(hive, path):
                install = values.get(value_name)
                if not install:
                    continue
                exe = guess_main_executable(Path(install))
                if exe is None or not exe.exists():
                    self._warn(f"EA title '{slug}' skipped - no verified executable")
                    continue
                out.append(GameEntry(
                    source=self.source,
                    platform_id=slug,
                    title=slug.replace("_", " ").strip(),
                    install_path=Path(install),
                    executable_path=exe,
                    launch_uri=None,
                    extra={"registry": path},
                ))
        return out


class UbisoftParser(_RegistryParser):
    source = "ubisoft"

    def is_available(self) -> bool:
        if winreg is None:
            return False
        return bool(self._enum_subkeys(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\WOW6432Node\Ubisoft\Launcher\Installs"))

    def scan(self) -> list[GameEntry]:
        self.errors.clear()
        out: list[GameEntry] = []
        root = r"SOFTWARE\WOW6432Node\Ubisoft\Launcher\Installs"
        for game_id, values in self._enum_subkeys(winreg.HKEY_LOCAL_MACHINE, root):
            install = values.get("InstallDir")
            if not install:
                continue
            install_path = Path(install)
            exe = guess_main_executable(install_path)
            if exe is None or not exe.exists():
                self._warn(f"Ubisoft title {game_id} skipped - no verified executable")
                continue
            launch_uri = f"uplay://launch/{game_id}/0" if game_id.isdigit() else None
            out.append(GameEntry(
                source=self.source,
                platform_id=game_id,
                title=install_path.name.replace("_", " ").strip(),
                install_path=install_path,
                executable_path=exe,
                launch_uri=launch_uri,
                extra={"registry": root},
            ))
        return out


class GogParser(_RegistryParser):
    source = "gog"

    def is_available(self) -> bool:
        if winreg is None:
            return False
        return bool(self._enum_subkeys(
            winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\GOG.com\Games"))

    def scan(self) -> list[GameEntry]:
        self.errors.clear()
        out: list[GameEntry] = []
        root = r"SOFTWARE\WOW6432Node\GOG.com\Games"
        for slug, values in self._enum_subkeys(winreg.HKEY_LOCAL_MACHINE, root):
            install = values.get("path")
            if not install:
                continue
            install_path = Path(install)
            exe_rel = values.get("exe") or values.get("exeFile")
            if exe_rel:
                candidate = Path(exe_rel)
                exe = candidate if candidate.is_absolute() else install_path / candidate
            else:
                exe = guess_main_executable(install_path)
            if exe is None or not exe.exists():
                self._warn(f"GOG title '{slug}' skipped - no verified executable")
                continue
            out.append(GameEntry(
                source=self.source,
                platform_id=str(values.get("gameID") or values.get("gogGalaxyId") or slug),
                title=str(values.get("gameName") or values.get("displayName")
                          or install_path.name),
                install_path=install_path,
                executable_path=exe,
                launch_uri=None,
                extra={"registry": root},
            ))
        return out