"""Katalog-Verwaltung: laden, validieren, cachen.

Der Katalog wird per HTTP(S) von einer konfigurierbaren URL geladen
(Standard: raw.githubusercontent.com). Die GitHub-API wird bewusst
NICHT genutzt (Rate-Limit). Bei Netzwerkfehlern wird der zuletzt
gespeicherte Cache aus PortableHub/catalog_cache.json verwendet.
"""

import json
import re
import urllib.request
import urllib.error
from typing import Optional

from . import settings as cfg

REQUIRED_FIELDS = ("id", "name", "version", "exe", "url", "sha256")
VALID_PLATFORMS = ("windows", "linux", "any")
_FETCH_TIMEOUT = 15


def current_platform() -> str:
    import sys
    return "windows" if sys.platform.startswith("win") else "linux"


def parse_version(version: str):
    """'1.2.3' -> (1,2,3); ungueltige Teile werden zu Strings."""
    parts = []
    for p in str(version).split("."):
        parts.append(int(p) if p.isdigit() else p)
    return tuple(parts)


def version_newer(a: str, b: str) -> bool:
    """True, wenn Version a neuer als b ist (Tupelvergleich)."""
    try:
        return parse_version(a) > parse_version(b)
    except Exception:
        return str(a) != str(b)


def validate_app(app: dict) -> bool:
    """Prueft Pflichtfelder und Plattform eines Katalog-Eintrags."""
    if not isinstance(app, dict):
        return False
    if any(not app.get(f) for f in REQUIRED_FIELDS):
        return False
    platform = app.get("platform", "windows")
    if platform not in VALID_PLATFORMS:
        return False
    if platform != "any" and platform != current_platform():
        return False
    if not app["id"].replace("-", "").replace("_", "").isalnum():
        return False
    return True


def validate_catalog(catalog) -> bool:
    return isinstance(catalog, dict) and isinstance(catalog.get("apps"), list)


def fetch_catalog(url: str, timeout: int = _FETCH_TIMEOUT) -> Optional[dict]:
    """Laedt den Katalog per urllib. Wirft bei Fehlern."""
    req = urllib.request.Request(
        url, headers={"User-Agent": "PortableHub/" + __import__("portablehub").__version__}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if not validate_catalog(data):
        raise ValueError("Katalog hat ungueltiges Format")
    return data


def load_catalog(settings: Optional[dict] = None, force_refresh: bool = False) -> dict:
    """Liefert den Katalog (dict mit 'apps').

    Reihenfolge: Netzwerk -> Cache. Gibt {'apps': [...], 'source': 'net'|'cache'|'empty'} zurueck.
    """
    if settings is None:
        settings = cfg.load_settings()
    url = settings.get("catalog_url") or cfg.DEFAULT_CATALOG_URL

    if not force_refresh:
        cached = cfg.load_catalog_cache()
        # Cache ist gueltig, solange er Apps enthaelt
        if validate_catalog(cached) and cached.get("apps"):
            # Trotzdem kurz versuchen, frisch zu laden? Nein: Aufrufer entscheidet.
            pass

    try:
        catalog = fetch_catalog(url)
        cfg.save_catalog_cache(catalog)
        return {"apps": catalog["apps"], "source": "net"}
    except Exception:
        cached = cfg.load_catalog_cache()
        if validate_catalog(cached):
            return {"apps": cached.get("apps", []), "source": "cache"}
        bundled = cfg.bundled_catalog()
        if validate_catalog(bundled):
            return {"apps": bundled.get("apps", []), "source": "bundled"}
        return {"apps": [], "source": "empty"}


def load_catalog_offline() -> dict:
    """Nur Cache, kein Netzwerk (fuer schnellen Start)."""
    cached = cfg.load_catalog_cache()
    if validate_catalog(cached):
        return {"apps": cached.get("apps", []), "source": "cache"}
    bundled = cfg.bundled_catalog()
    if validate_catalog(bundled):
        return {"apps": bundled.get("apps", []), "source": "bundled"}
    return {"apps": [], "source": "empty"}


def apps_for_platform(catalog: dict) -> list:
    """Filtert Katalog-Apps auf die aktuelle Plattform."""
    return [a for a in catalog.get("apps", []) if validate_app(a)]


def app_status(app: dict, installed: dict) -> str:
    """'installiert' | 'update' | 'nicht installiert'."""
    entry = installed.get(app["id"])
    if not entry:
        return "nicht installiert"
    if version_newer(app.get("version", ""), entry.get("version", "")):
        return "update"
    return "installiert"
