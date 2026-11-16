"""Startet installierte Apps mit korrektem Arbeitsverzeichnis."""

import os
import subprocess
import sys
from pathlib import Path

from . import settings as cfg
from . import installer


def app_exe_path(app_id: str) -> Path:
    """Pfad zur Start-Exe einer installierten App."""
    installed = cfg.load_installed()
    entry = installed.get(app_id)
    if not entry:
        raise installer.InstallError(f"App '{app_id}' ist nicht installiert")
    rel = entry.get("exe") or ""
    # Pfad aus installed.json + Katalog-exe-Fallback
    exe = cfg.apps_dir() / app_id / rel
    if not exe.exists():
        # Fallback: Suche *.exe im App-Ordner
        app_dir = cfg.apps_dir() / app_id
        exes = sorted(app_dir.rglob("*.exe")) if app_dir.exists() else []
        if not exes:
            raise installer.InstallError(f"Keine .exe in {app_dir} gefunden")
        exe = exes[0]
    return exe


def launch(app_id: str) -> subprocess.Popen:
    """Startet die App; Arbeitsverzeichnis = App-Ordner."""
    exe = app_exe_path(app_id)
    cwd = exe.parent
    if sys.platform.startswith("win"):
        return subprocess.Popen([str(exe)], cwd=str(cwd))
    # Linux: evtl. kein +x-bit auf exFAT - chmod versuchen, sonst sh
    try:
        os.chmod(exe, 0o755)
    except OSError:
        pass
    return subprocess.Popen([str(exe)], cwd=str(cwd))
