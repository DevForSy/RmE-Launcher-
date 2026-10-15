from __future__ import annotations

import logging
from pathlib import Path

from parsers.steam import SteamParser, VdfParseError, parse_vdf

log = logging.getLogger(__name__)

_MAX_LOCALCONFIG_BYTES = 16 * 1024 * 1024
_STEAMID64_BASE = 76561197960265728


def _read_capped(path: Path, limit: int) -> str:
    with path.open("r", encoding="utf-8-sig", errors="replace") as fh:
        return fh.read(limit)


def _most_recent_account(root: Path) -> str | None:
    login = root / "config" / "loginusers.vdf"
    try:
        if login.is_file():
            data = parse_vdf(_read_capped(login, 4 * 1024 * 1024))
            users = data.get("users", {})
            best_id, best_ts = None, -1
            for steamid64, node in users.items():
                if not isinstance(node, dict):
                    continue
                if str(node.get("MostRecent", "0")) == "1":
                    try:
                        return str(int(steamid64) - _STEAMID64_BASE)
                    except ValueError:
                        continue
                try:
                    ts = int(str(node.get("Timestamp", "0")))
                except ValueError:
                    ts = 0
                if ts > best_ts:
                    best_ts, best_id = ts, steamid64
            if best_id is not None:
                try:
                    return str(int(best_id) - _STEAMID64_BASE)
                except ValueError:
                    pass
    except (OSError, VdfParseError):
        pass
    userdata = root / "userdata"
    best_cfg, best_mtime = None, -1.0
    try:
        for folder in userdata.iterdir():
            cfg = folder / "config" / "localconfig.vdf"
            if cfg.is_file():
                try:
                    mtime = cfg.stat().st_mtime
                except OSError:
                    continue
                if mtime > best_mtime:
                    best_mtime, best_cfg = mtime, cfg
    except OSError:
        pass
    return None if best_cfg is None else best_cfg.parent.parent.name


def _collect_counters(cfg: Path) -> dict[str, tuple[int, int]]:
    try:
        data = parse_vdf(_read_capped(cfg, _MAX_LOCALCONFIG_BYTES))
    except (OSError, VdfParseError) as exc:
        log.warning("localconfig.vdf unreadable: %s", exc)
        return {}
    apps = (data.get("UserLocalConfigStore", {})
                .get("Software", {})
                .get("Valve", {})
                .get("Steam", {})
                .get("apps", {}))
    if not isinstance(apps, dict):
        return {}
    out: dict[str, tuple[int, int]] = {}
    for appid, node in apps.items():
        if not isinstance(node, dict) or not str(appid).isdigit():
            continue
        minutes = 0
        raw_pt = node.get("Playtime")
        if raw_pt is not None:
            try:
                minutes = max(0, int(str(raw_pt)))
            except ValueError:
                minutes = 0
        last_epoch = 0
        raw_lp = node.get("LastPlayed")
        if raw_lp is not None:
            try:
                last_epoch = max(0, int(str(raw_lp)))
            except ValueError:
                last_epoch = 0
        if minutes > 0 or last_epoch > 0:
            out[str(appid)] = (minutes, last_epoch)
    return out


def import_steam_playtime(db) -> int:
    try:
        root = SteamParser()._steam_root()
    except Exception:
        root = None
    if root is None:
        return 0
    account = _most_recent_account(root)
    if account is None:
        log.info("Steam playtime import: no userdata account found")
        return 0
    cfg = root / "userdata" / account / "config" / "localconfig.vdf"
    if not cfg.is_file():
        return 0
    stats = _collect_counters(cfg)
    if not stats:
        log.info("Steam playtime import: no counters present in localconfig")
        return 0
    updated = db.import_steam_stats(stats)
    log.info("Steam playtime import: %d game(s) updated", updated)
    return updated