import logging
import os
import re
from pathlib import Path

try:
    import winreg
except ImportError:
    winreg = None

from parsers.base import GameEntry, GameParser, guess_main_executable

log = logging.getLogger(__name__)

FULLY_INSTALLED = 0x4
_DOWNLOAD_ACTIVE = 0x1FF00

_NON_GAME_APPIDS = {"228983", "228990", "1070560", "1391110", "1826330"}
_NON_GAME_NAME = re.compile(
    r"redistribut|steamworks|steam ?runtime|proton|directx|physx|"
    r"openvr|steamvr|dedicated server|linux runtime",
    re.IGNORECASE,
)

MAX_VDF_DEPTH = 64
_MAX_VDF_BYTES = 8 * 1024 * 1024


def _read_capped(path: Path, limit: int = _MAX_VDF_BYTES) -> str:
    with path.open("r", encoding="utf-8-sig", errors="replace") as fh:
        return fh.read(limit)


class VdfParseError(ValueError):
    pass


def parse_vdf(text: str) -> dict[str, object]:
    pos = 0
    n = len(text)

    def skip_ws() -> None:
        nonlocal pos
        while pos < n:
            ch = text[pos]
            if ch in " \t\r\n":
                pos += 1
            elif text.startswith("//", pos):
                end = text.find("\n", pos)
                pos = n if end < 0 else end + 1
            else:
                break

    def read_string() -> str:
        nonlocal pos
        skip_ws()
        if pos >= n:
            raise VdfParseError("unexpected end of file")
        if text[pos] == '"':
            pos += 1
            out: list[str] = []
            while pos < n:
                ch = text[pos]
                if ch == '"':
                    pos += 1
                    return "".join(out)
                if ch == "\\" and pos + 1 < n:
                    nxt = text[pos + 1]
                    out.append({"n": "\n", "t": "\t", "r": "\r"}.get(nxt, nxt))
                    pos += 2
                else:
                    out.append(ch)
                    pos += 1
            raise VdfParseError("unterminated string")
        start = pos
        while pos < n and text[pos] not in " \t\r\n{}":
            pos += 1
        if pos == start:
            raise VdfParseError(f"expected token at offset {pos}")
        return text[start:pos]

    def read_map(top: bool = False, depth: int = 0) -> dict[str, object]:
        nonlocal pos
        if depth > MAX_VDF_DEPTH:
            raise VdfParseError("nesting too deep")
        obj: dict[str, object] = {}
        while True:
            skip_ws()
            if pos >= n:
                if top:
                    return obj
                raise VdfParseError("unexpected EOF inside block")
            if text[pos] == "}":
                pos += 1
                return obj
            key = read_string()
            skip_ws()
            if pos < n and text[pos] == "{":
                pos += 1
                obj[key] = read_map(depth=depth + 1)
            else:
                obj[key] = read_string()

    return read_map(top=True)


def _to_int(value: object, default: int = 0) -> int:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return default


def _prefer(new: GameEntry, old: GameEntry) -> GameEntry:
    new_ok = bool((new.state_flags or 0) & FULLY_INSTALLED)
    old_ok = bool((old.state_flags or 0) & FULLY_INSTALLED)
    if new_ok != old_ok:
        return new if new_ok else old
    return new if new.extra.get("last_updated", 0) >= old.extra.get("last_updated", 0) else old


class SteamParser(GameParser):
    source = "steam"
    REG_PATH = r"Software\Valve\Steam"

    def __init__(self) -> None:
        super().__init__()
        self._root: Path | None = None

    def _steam_root(self) -> Path | None:
        if self._root is not None:
            return self._root
        override = os.environ.get("RME_STEAM_PATH")
        if override:
            self._root = Path(override)
            return self._root
        if winreg is None:
            return None
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.REG_PATH) as key:
                path, _ = winreg.QueryValueEx(key, "SteamPath")
            self._root = Path(path)
        except OSError:
            self._root = None
        return self._root

    def is_available(self) -> bool:
        return self._steam_root() is not None

    def _discover_libraries(self, root: Path) -> list[Path]:
        libraries = [root]
        vdf_path = root / "steamapps" / "libraryfolders.vdf"
        try:
            data = parse_vdf(_read_capped(vdf_path))
        except (OSError, VdfParseError) as exc:
            log.warning("Could not parse libraryfolders.vdf (%s)", exc)
            self.errors.append(str(exc))
            return libraries

        folders = data.get("libraryfolders", {})
        if not isinstance(folders, dict):
            return libraries
        for node in folders.values():
            if isinstance(node, dict) and node.get("path"):
                candidate = Path(str(node["path"]))
            elif isinstance(node, str):
                candidate = Path(node)
            else:
                continue
            if candidate.exists() and candidate not in libraries:
                libraries.append(candidate)
        return libraries

    def _parse_manifest(self, manifest: Path) -> GameEntry | None:
        data = parse_vdf(_read_capped(manifest))
        state = data.get("AppState")
        if not isinstance(state, dict):
            raise VdfParseError("missing 'AppState' block")

        appid = str(state.get("appid", "")).strip()
        name = str(state.get("name", "")).strip()
        installdir = str(state.get("installdir", "")).strip()
        if not appid or not name:
            raise VdfParseError("manifest missing appid/name")
        if not installdir:
            raise VdfParseError("manifest missing installdir")

        if not appid.isdigit():
            raise VdfParseError(f"non-numeric appid rejected: {appid!r}")
        if ".." in Path(installdir).parts or Path(installdir).is_absolute():
            raise VdfParseError(f"installdir escapes library: {installdir!r}")

        state_flags = _to_int(state.get("StateFlags"))

        if appid in _NON_GAME_APPIDS or _NON_GAME_NAME.search(name):
            log.debug("Skipping Steam tool/redist %s (%s)", appid, name)
            return None
        if not state_flags & FULLY_INSTALLED or state_flags & _DOWNLOAD_ACTIVE:
            log.debug("Skipping app %s - not fully installed (flags=%s)",
                      appid, state_flags)
            return None

        install_path = manifest.parent.parent / "common" / installdir
        game_exe = guess_main_executable(install_path)

        return GameEntry(
            source=self.source,
            platform_id=appid,
            title=name,
            install_path=install_path,
            executable_path=None,
            launch_uri=f"steam://run/{appid}",
            cover_urls=[
                f"https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/library_600x900.jpg",
                f"https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/header.jpg",
            ],
            hero_urls=[
                f"https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/library_hero.jpg",
                f"https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/header.jpg",
            ],
            size_on_disk=_to_int(state.get("SizeOnDisk")),
            state_flags=state_flags,
            extra={
                "buildid": str(state.get("buildid", "")),
                "last_updated": _to_int(state.get("LastUpdated")),
                "game_exe_name": game_exe.name if game_exe else None,
            },
        )

    def scan(self) -> list[GameEntry]:
        self.errors.clear()
        root = self._steam_root()
        if root is None:
            return []

        games: dict[str, GameEntry] = {}
        for library in self._discover_libraries(root):
            apps_dir = library / "steamapps"
            if not apps_dir.is_dir():
                continue
            for manifest in sorted(apps_dir.glob("appmanifest_*.acf")):
                try:
                    entry = self._parse_manifest(manifest)
                except (VdfParseError, KeyError, TypeError, ValueError, OSError) as exc:
                    log.warning("Skipping Steam manifest %s: %s", manifest.name, exc)
                    self.errors.append(str(exc))
                    continue
                if entry is None:
                    continue
                existing = games.get(entry.platform_id)
                if existing is None or _prefer(entry, existing) is entry:
                    games[entry.platform_id] = entry
        return list(games.values())