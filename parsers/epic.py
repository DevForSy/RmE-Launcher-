import json
import logging
import os
from pathlib import Path
from urllib.parse import quote

from parsers.base import GameEntry, GameParser

log = logging.getLogger(__name__)

_MAX_ITEM_BYTES = 10 * 1024 * 1024


class EpicParser(GameParser):
    source = "epic"

    @staticmethod
    def _manifest_dir() -> Path | None:
        base = os.environ.get("ALLUSERSPROFILE") or os.environ.get("PROGRAMDATA")
        if not base:
            return None
        return Path(base) / "Epic" / "EpicGamesLauncher" / "Data" / "Manifests"

    def is_available(self) -> bool:
        mdir = self._manifest_dir()
        return mdir is not None and mdir.is_dir()

    def _warn(self, message: str) -> None:
        log.warning(message)
        self.errors.append(message)

    @staticmethod
    def _launch_uri(namespace: str, catalog_item_id: str, app_name: str) -> str:
        ns = quote(namespace, safe="")
        cid = quote(catalog_item_id, safe="")
        app = quote(app_name, safe="")
        return (f"com.epicgames.launcher://apps/{ns}%3A{cid}%3A{app}"
                f"?action=launch&silent=true")

    def _entry_from_manifest(self, data: dict, manifest_path: Path) -> GameEntry | None:
        if not data.get("bIsApplication", True):
            return None

        if data.get("bIsIncompleteInstall", False) or data.get("bIsInstalling", False):
            log.debug("Skipping Epic app %s - install incomplete",
                      data.get("AppName", "?"))
            return None

        categories = [
            c.get("path", "") for c in data.get("AppCategories", []) if isinstance(c, dict)
        ]
        if not any(c == "public games" or c.startswith("public games/") for c in categories):
            return None

        app_name = str(data.get("AppName", "")).strip()
        namespace = str(data.get("CatalogNamespace", "")).strip()
        catalog_item_id = str(data.get("CatalogItemId", "")).strip()
        if not (app_name and namespace and catalog_item_id):
            raise KeyError("manifest missing AppName/CatalogNamespace/CatalogItemId")

        main_app = str(data.get("MainGameAppName", app_name)).strip()
        if main_app and main_app != app_name:
            return None

        install_location = str(data.get("InstallLocation", "")).strip()
        if not install_location:
            self._warn(f"Skipping {manifest_path.name}: empty InstallLocation")
            return None
        install_path = Path(install_location)

        launch_exe = str(data.get("LaunchExecutable", "")).strip()
        executable: Path | None = None
        if launch_exe:
            candidate = install_path / launch_exe
            executable = candidate if candidate.is_file() else None

        size = data.get("InstallSize") or data.get("SizeOnDisk")
        try:
            size_on_disk = int(size) if size is not None else None
        except (TypeError, ValueError):
            size_on_disk = None

        return GameEntry(
            source=self.source,
            platform_id=app_name,
            title=str(data.get("DisplayName", app_name)).strip() or app_name,
            install_path=install_path,
            executable_path=executable,
            launch_uri=self._launch_uri(namespace, catalog_item_id, app_name),
            size_on_disk=size_on_disk,
            state_flags=4,
            extra={"catalog_namespace": namespace, "catalog_item_id": catalog_item_id},
        )

    def scan(self) -> list[GameEntry]:
        self.errors.clear()
        out: list[GameEntry] = []
        mdir = self._manifest_dir()
        if mdir is None:
            return out

        for item_path in sorted(mdir.glob("*.item")):
            try:
                with item_path.open("r", encoding="utf-8", errors="replace") as fh:
                    data = json.loads(fh.read(_MAX_ITEM_BYTES))
            except (OSError, json.JSONDecodeError) as exc:
                self._warn(f"Skipping unreadable Epic manifest {item_path.name}: {exc}")
                continue
            if not isinstance(data, dict):
                self._warn(f"Skipping Epic manifest {item_path.name}: unexpected root type")
                continue
            try:
                entry = self._entry_from_manifest(data, item_path)
            except (KeyError, TypeError, ValueError) as exc:
                self._warn(f"Malformed Epic manifest {item_path.name}: {exc}")
                continue
            if entry is not None:
                out.append(entry)
        return out