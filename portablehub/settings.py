"""Pfad- und Einstellungsverwaltung fuer PortableHub.

Alle Pfade werden relativ zur Programmwurzel aufgeloest, damit der Stick
unter jedem Laufwerksbuchstaben funktioniert. Es wird nichts in die
Registry oder nach %APPDATA% geschrieben.
"""

import json
import os
import sys
from pathlib import Path

APP_NAME = "PortableHub"
DEFAULT_CATALOG_URL = (
    "https://raw.githubusercontent.com/7miwork/PortableHub/main/catalog.json"
)


def app_root() -> Path:
    """Wurzel des tragbaren Systems (Ordner der PortableHub.exe)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    # Im Quelltextmodus: uebergeordneter Ordner des Pakets (Projektroot)
    return Path(__file__).resolve().parent.parent


def data_dir() -> Path:
    """Ordner fuer installed.json, settings.json und Cache."""
    return app_root() / "PortableHub"


def apps_dir() -> Path:
    return app_root() / "Apps"


def tmp_dir() -> Path:
    return data_dir() / "tmp"


def _read_json(path: Path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return default


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def load_installed() -> dict:
    """Liest den lokalen Installationsstand: {app_id: {version, path, ...}}."""
    data = _read_json(data_dir() / "installed.json", {})
    return data if isinstance(data, dict) else {}


def save_installed(installed: dict) -> None:
    _write_json(data_dir() / "installed.json", installed)


def load_settings() -> dict:
    defaults = {
        "catalog_url": DEFAULT_CATALOG_URL,
        "language": "de",
        "start_with_windows": False,
        "check_updates_on_start": False,
        "window_mode": False,  # True = Kachel-Fenster statt Tray
    }
    data = _read_json(data_dir() / "settings.json", {})
    if isinstance(data, dict):
        defaults.update({k: v for k, v in data.items() if k in defaults})
    return defaults


def save_settings(settings: dict) -> None:
    _write_json(data_dir() / "settings.json", settings)


def catalog_cache_path() -> Path:
    return data_dir() / "catalog_cache.json"


def save_catalog_cache(catalog: dict) -> None:
    _write_json(catalog_cache_path(), catalog)


def load_catalog_cache() -> dict:
    data = _read_json(catalog_cache_path(), {})
    return data if isinstance(data, dict) else {}


def bundled_catalog() -> dict:
    """Katalog, der per PyInstaller mitgeliefert wurde (optional)."""
    try:
        if getattr(sys, "frozen", False):
            base = Path(sys._MEIPASS)
        else:
            base = app_root()
        return _read_json(base / "catalog.json", {})
    except Exception:
        return {}
