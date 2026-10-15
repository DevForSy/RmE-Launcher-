from __future__ import annotations

import importlib
import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class GameEntry:
    source: str
    platform_id: str
    title: str
    install_path: Path | None = None
    executable_path: Path | None = None
    launch_uri: str | None = None
    launch_args: list[str] = field(default_factory=list)
    cover_urls: list[str] = field(default_factory=list)
    hero_urls: list[str] = field(default_factory=list)
    size_on_disk: int | None = None
    state_flags: int | None = None
    extra: dict = field(default_factory=dict)


class GameParser(ABC):
    source: ClassVar[str] = "generic"

    def __init__(self) -> None:
        self.errors: list[str] = []

    @abstractmethod
    def is_available(self) -> bool: ...

    @abstractmethod
    def scan(self) -> list[GameEntry]: ...


_HELPER_PATTERNS = (
    "uninstall", "unins", "setup", "installer", "redist", "vcredist",
    "dxsetup", "dotnet", "crash", "updater", "update", "patcher", "eosboot",
)


def guess_main_executable(root: Path | None, max_depth: int = 2) -> Path | None:
    if root is None or not root.is_dir():
        return None
    best: tuple[int, Path] | None = None
    root_depth = len(root.parts)
    for dirpath, dirs, files in os.walk(root):
        if len(Path(dirpath).parts) - root_depth >= max_depth:
            dirs[:] = []
        for fname in files:
            low = fname.casefold()
            if not low.endswith(".exe") or any(p in low for p in _HELPER_PATTERNS):
                continue
            full = Path(dirpath) / fname
            try:
                size = full.stat().st_size
            except OSError:
                continue
            if best is None or size > best[0]:
                best = (size, full)
    return best[1] if best else None


_PARSER_REGISTRY = (
    ("parsers.steam", "SteamParser"),
    ("parsers.epic", "EpicParser"),
    ("parsers.generic", "EAParser"),
    ("parsers.generic", "UbisoftParser"),
    ("parsers.generic", "GogParser"),
    ("parsers.riot", "RiotParser"),
    ("parsers.rockstar", "RockstarParser"),
    ("parsers.battlenet", "BnetParser"),
    ("parsers.minecraft", "MinecraftParser"),
    ("parsers.bethesda", "BethesdaParser"),
    ("parsers.roblox", "RobloxParser"),
)

def create_parsers() -> list[GameParser]:
    parsers: list[GameParser] = []
    for module, cls_name in _PARSER_REGISTRY:
        try:
            cls = getattr(importlib.import_module(module), cls_name)
            parser = cls()
        except Exception:
            log.exception("Parser failed to load: %s.%s (platform skipped)",
                          module, cls_name)
            continue
        try:
            if parser.is_available():
                parsers.append(parser)
            else:
                log.info("Platform not detected: %s", parser.source)
        except Exception:
            log.exception("Availability check failed: %s", module)
    return parsers