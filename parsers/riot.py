import logging
import string
from pathlib import Path

try:
    import winreg
except ImportError:
    winreg = None

from parsers.base import GameEntry, GameParser

log = logging.getLogger(__name__)

_REG_VIEWS = (
    r"SOFTWARE\WOW6432Node\Riot Games, Inc.",
    r"SOFTWARE\WOW6432Node\Riot Games",
    r"SOFTWARE\Riot Games, Inc.",
    r"SOFTWARE\Riot Games",
)
_KNOWN_CLIENT_DIRS = {"riot client", "vanguard"}

_TITLES = {
    "valorant": "VALORANT",
    "league_of_legends": "League of Legends",
    "teamfight_tactics": "Teamfight Tactics",
    "legends_of_runeterra": "Legends of Runeterra",
}

_ART_PAGES = {
    "valorant": ["https://playvalorant.com/"],
    "league_of_legends": [
        "https://www.leagueoflegends.com/",
        "https://ddragon.leagueoflegends.com/cdn/img/champion/splash/Jinx_0.jpg",
    ],
    "teamfight_tactics": ["https://teamfighttactics.leagueoflegends.com/"],
    "legends_of_runeterra": ["https://playruneterra.com/"],
}


def _normalize_slug(name: str) -> str:
    slug = name.casefold().replace(" ", "_")
    if slug.endswith("_-_tdm") or slug == "league_of_legends_tdm":
        slug = "teamfight_tactics"
    return slug


def _clean_path(raw: str) -> Path | None:
    value = raw.strip().strip('"').strip()
    if not value:
        return None
    return Path(value)


class RiotParser(GameParser):
    source = "riot"

    def is_available(self) -> bool:
        if winreg is not None:
            for view in _REG_VIEWS:
                try:
                    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, view):
                        return True
                except OSError:
                    continue
        return bool(self._riot_roots())

    @staticmethod
    def _riot_roots() -> list[Path]:
        roots: list[Path] = []
        for letter in string.ascii_uppercase:
            candidate = Path(f"{letter}:\\Riot Games")
            if candidate.is_dir():
                roots.append(candidate)
        return roots

    def _enum_products(self) -> list[tuple[str, Path]]:
        products: list[tuple[str, Path]] = []
        if winreg is None:
            return products
        for view in _REG_VIEWS:
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, view) as root:
                    index = 0
                    while True:
                        try:
                            name = winreg.EnumKey(root, index)
                        except OSError:
                            break
                        index += 1
                        try:
                            with winreg.OpenKey(root, name) as key:
                                raw, _ = winreg.QueryValueEx(key, "InstallLocation")
                        except OSError:
                            continue
                        install = _clean_path(str(raw))
                        if install is not None and install.is_dir():
                            products.append((name, install))
            except OSError:
                continue
        return products

    def _fallback_products(self) -> list[tuple[str, Path]]:
        out: list[tuple[str, Path]] = []
        for root in self._riot_roots():
            try:
                folders = sorted(root.iterdir())
            except OSError:
                continue
            for folder in folders:
                if not folder.is_dir():
                    continue
                if folder.name.casefold() in _KNOWN_CLIENT_DIRS:
                    continue
                if self._find_game_exe(folder) is not None:
                    out.append((folder.name, folder))
        return out

    @staticmethod
    def _find_game_exe(install: Path) -> Path | None:
        best: tuple[int, Path] | None = None
        for shipping in install.rglob("*Shipping.exe"):
            try:
                size = shipping.stat().st_size
            except OSError:
                continue
            if best is None or size > best[0]:
                best = (size, shipping)
        if best:
            return best[1]
        best = None
        for exe in install.rglob("*.exe"):
            low = str(exe).casefold()
            if "riot client" in low or "uninstall" in exe.name.casefold():
                continue
            try:
                size = exe.stat().st_size
            except OSError:
                continue
            if best is None or size > best[0]:
                best = (size, exe)
        return best[1] if best else None

    @staticmethod
    def _find_client(install: Path) -> Path | None:
        bases = [install.parent, install.parent.parent]
        bases.extend(p for p in Path("C:\\").glob("Riot Games"))
        for base in bases:
            candidate = base / "Riot Client" / "RiotClientServices.exe"
            if candidate.is_file():
                return candidate
        return None

    @staticmethod
    def _process_name(game_exe: Path) -> str:
        stem = game_exe.stem
        for suffix in ("-Win64-Shipping", "-Win32-Shipping", "-Shipping"):
            if stem.endswith(suffix):
                stem = stem[: -len(suffix)]
                break
        return f"{stem}.exe"

    @staticmethod
    def _display_title(name: str) -> str:
        slug = _normalize_slug(name)
        if slug in _TITLES:
            return _TITLES[slug]
        return name if not name.islower() else name.title()

    def scan(self) -> list[GameEntry]:
        self.errors.clear()
        merged: dict[str, tuple[str, Path]] = {}
        for name, install in [*self._enum_products(), *self._fallback_products()]:
            key = str(install).casefold().rstrip("\\/")
            merged.setdefault(key, (name, install))

        out: list[GameEntry] = []
        for name, install in merged.values():
            game_exe = self._find_game_exe(install)
            if game_exe is None:
                self.errors.append(f"Riot '{name}': no game executable under {install}")
                continue
            client = self._find_client(install)
            if client is None:
                self.errors.append(f"Riot '{name}': RiotClientServices.exe not found")
                continue
            slug = _normalize_slug(name)
            art = _ART_PAGES.get(slug, [])
            out.append(GameEntry(
                source=self.source,
                platform_id=slug,
                title=self._display_title(name),
                install_path=install,
                executable_path=client,
                launch_uri=None,
                launch_args=[f"--launch-product={slug}", "--launch-patchline=live"],
                cover_urls=list(art),
                hero_urls=list(art),
                state_flags=4,
                extra={"game_exe_name": self._process_name(game_exe)},
            ))
        log.info("Riot parser: %d product(s) detected", len(out))
        return out