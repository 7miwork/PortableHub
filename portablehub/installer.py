"""Download, Hash-Pruefung, Entpacken und Deinstallation von Apps.

Sicherheitsmerkmale:
- SHA-256-Checksumme aus dem Katalog wird vor dem Entpacken geprueft.
- ZIP-Inhalte werden auf Pfad-Durchgriffe (../, absolute Pfade) geprueft.
- Bei Updates bleiben die Ordner "data"/"Data" der App erhalten.
- Alles laeuft relativ zur Programmwurzel (portabel, kein Laufwerksbezug).
"""

import hashlib
import os
import shutil
import tempfile
import threading
import zipfile
from pathlib import Path, PurePosixPath
from typing import Optional

from . import settings as cfg
from . import catalog as cat

USER_DATA_DIRS = ("data", "Data")
MAX_RETRIES = 3
_CHUNK = 1024 * 256


class InstallError(Exception):
    """Fehler mit benutzerverstaendlicher Nachricht."""


def sha256_file(path: Path, cancel: threading.Event = None) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            if cancel is not None and cancel.is_set():
                raise InstallError("Abgebrochen")
            chunk = f.read(_CHUNK)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _check_cancel(cancel):
    if cancel is not None and cancel.is_set():
        raise InstallError("Abgebrochen")


def download(url: str, dest: Path, progress=None, cancel=None) -> Path:
    """Laedt url nach dest. progress(bytes_done, bytes_total|None).
    Wirft InstallError bei Netzwerk-/Abbruchfehlern."""
    import urllib.request
    import urllib.error

    dest.parent.mkdir(parents=True, exist_ok=True)
    last_exc = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            _download_once(url, dest, progress, cancel)
            return dest
        except InstallError:
            raise
        except Exception as e:  # Netzwerkfehler etc.
            last_exc = e
            _check_cancel(cancel)
            try:
                dest.unlink(missing_ok=True)
            except OSError:
                pass
    raise InstallError(f"Download fehlgeschlagen nach {MAX_RETRIES} Versuchen: {last_exc}")


def _download_once(url: str, dest: Path, progress, cancel):
    import urllib.request

    tmp = dest.with_suffix(dest.suffix + ".part")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "PortableHub"})
        with urllib.request.urlopen(req, timeout=30) as resp, open(tmp, "wb") as out:
            total = resp.headers.get("Content-Length")
            total = int(total) if total else None
            done = 0
            while True:
                _check_cancel(cancel)
                chunk = resp.read(_CHUNK)
                if not chunk:
                    break
                out.write(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
        os.replace(tmp, dest)
    except InstallError:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    except Exception as e:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise InstallError(f"Downloadfehler: {e}") from e


def _safe_extract(zf: zipfile.ZipFile, target: Path) -> None:
    """Entpackt zipfile in target, verhindert Pfad-Durchgriffe."""
    target = target.resolve()
    for member in zf.infolist():
        # Nur Vorwaertsslash-Pfade; Windows-Backslash wird normalisiert
        name = member.filename.replace("\\", "/")
        pure = PurePosixPath(name)
        if pure.is_absolute() or ".." in pure.parts:
            raise InstallError(f"Unsicherer Pfad im Archiv: {member.filename}")
        dest = (target / name).resolve()
        try:
            dest.relative_to(target)
        except ValueError:
            raise InstallError(f"Pfad-Durchgriff im Archiv: {member.filename}")
    zf.extractall(target)


def _merge_dir(src: Path, dst: Path) -> None:
    """Kopiert Inhalt von src nach dst (ueberschreibend, rekursiv)."""
    for item in src.iterdir():
        s = item
        d = dst / item.name
        if item.is_dir():
            if d.exists():
                shutil.rmtree(d)
            shutil.copytree(s, d)
        else:
            d.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(s, d)


def install_app(app: dict, progress=None, cancel=None, staging_root: Path = None) -> dict:
    """Installiert oder aktualisiert eine App aus dem Katalog.

    Returns Eintrag fuer installed.json. Wirft InstallError.
    """
    _check_cancel(cancel)
    app_id = app["id"]
    target = cfg.apps_dir() / app_id
    staging_root = staging_root or cfg.tmp_dir()
    staging_root.mkdir(parents=True, exist_ok=True)

    # 1) ZIP herunterladen
    zip_path = staging_root / f"{app_id}-{app.get('version', '0')}.zip"
    expected_size = app.get("size")

    def dl_progress(done, total):
        if progress:
            progress("download", done, total)

    download(app["url"], zip_path, progress=dl_progress, cancel=cancel)

    # 2) Groesse pruefen (falls angegeben)
    actual_size = zip_path.stat().st_size
    if expected_size and actual_size != int(expected_size):
        raise InstallError(
            f"Groesse stimmt nicht ueberein: erwartet {expected_size}, "
            f"erhalten {actual_size} Bytes"
        )

    # 3) SHA-256 pruefen
    expected_hash = (app.get("sha256") or "").lower()
    if expected_hash:
        digest = sha256_file(zip_path, cancel=cancel)
        if digest != expected_hash:
            raise InstallError(
                f"SHA-256-Pruefung fehlgeschlagen: erwartet {expected_hash[:12]}…, "
                f"erhalten {digest[:12]}… (Datei wurde evtl. manipuliert)"
            )

    # 4) In Staging-Verzeichnis entpacken
    extract_dir = staging_root / f"extract-{app_id}"
    if extract_dir.exists():
        shutil.rmtree(extract_dir, ignore_errors=True)
    extract_dir.mkdir(parents=True)
    try:
        with zipfile.ZipFile(zip_path) as zf:
            _safe_extract(zf, extract_dir)
    except zipfile.BadZipFile as e:
        raise InstallError(f"Beschadigtes ZIP-Archiv: {e}") from e
    finally:
        try:
            zip_path.unlink(missing_ok=True)
        except OSError:
            pass

    # 5) Aufraeumen: leeres Zip-Verzeichnis Falls das Archiv einen
    #    einzigen Top-Level-Ordner enthaelt, dessen Inhalt hochziehen.
    _normalize_extract_dir(extract_dir)

    # 6) In Zielordner verschieben, dabei User-Daten erhalten
    cfg.apps_dir().mkdir(parents=True, exist_ok=True)
    is_update = target.exists()
    backup_dirs = []
    try:
        if is_update:
            # data/Data zuruecklegen, damit sie nicht ueberschrieben werden
            for name in USER_DATA_DIRS:
                src = target / name
                if src.is_dir():
                    bak = staging_root / f"userdata-{app_id}-{name}"
                    if bak.exists():
                        shutil.rmtree(bak)
                    shutil.move(str(src), str(bak))
                    backup_dirs.append((bak, name))
                elif src.exists():
                    # data als Datei: ebenfalls bewahren
                    bak = staging_root / f"userdata-{app_id}-{name}"
                    shutil.move(str(src), str(bak))
                    backup_dirs.append((bak, name))
            shutil.rmtree(target)
        shutil.move(str(extract_dir), str(target))
        # User-Daten zurueckkopieren
        for bak, name in backup_dirs:
            dst = target / name
            if bak.is_dir():
                if dst.exists():
                    _merge_dir(bak, dst)
                    shutil.rmtree(bak, ignore_errors=True)
                else:
                    shutil.move(str(bak), str(dst))
            else:
                shutil.copy2(bak, dst)
                bak.unlink(missing_ok=True)
    except Exception:
        # Rollback: alten Stand wiederherstellen, falls moeglich
        if is_update and target.exists():
            shutil.rmtree(target, ignore_errors=True)
        for bak, name in backup_dirs:
            if bak.exists() and not (target / name).exists():
                if target.exists():
                    shutil.move(str(bak), str(target / name))
        raise InstallError("Installation fehlgeschlagen (Dateisystem)")
    finally:
        shutil.rmtree(extract_dir, ignore_errors=True)
        for bak, _name in backup_dirs:
            shutil.rmtree(bak, ignore_errors=True) if bak.is_dir() else bak.unlink(missing_ok=True)

    _check_cancel(cancel)

    # 7) installed.json aktualisieren
    installed = cfg.load_installed()
    installed[app_id] = {
        "version": app.get("version", ""),
        "path": str(target.relative_to(cfg.app_root())),
        "name": app.get("name", app_id),
        "exe": app.get("exe", ""),
        "category": app.get("category", ""),
    }
    cfg.save_installed(installed)
    return installed[app_id]


def _normalize_extract_dir(extract_dir: Path) -> None:
    """Wenn das Archiv genau einen Ordner enthaelt, dessen Inhalt hochziehen."""
    entries = [p for p in extract_dir.iterdir()]
    if len(entries) == 1 and entries[0].is_dir():
        inner = entries[0]
        for child in inner.iterdir():
            shutil.move(str(child), str(extract_dir / child.name))
        inner.rmdir()


def uninstall_app(app_id: str) -> bool:
    """Entfernt eine App komplett (inkl. User-Daten). True bei Erfolg."""
    if not app_id.replace("-", "").replace("_", "").isalnum():
        raise InstallError(f"Ungueltige App-ID: {app_id}")
    installed = cfg.load_installed()
    if app_id not in installed:
        return False
    target = cfg.apps_dir() / app_id
    if target.exists():
        shutil.rmtree(target)
    del installed[app_id]
    cfg.save_installed(installed)
    return True


def check_disk_space(app: dict) -> Optional[str]:
    """Grobe Speicherpruefung. Gibt Warnung zurueck oder None."""
    size = int(app.get("size") or 0)
    if not size:
        return None
    try:
        usage = shutil.disk_usage(cfg.app_root())
        # ZIP + entpackte Dateien: grob 3x ZIP-Groesse noetig
        if usage.free < size * 3:
            return (
                f"Wenig Speicher: benoetigt ca. {size * 3 / 1e6:.0f} MB, "
                f"frei {usage.free / 1e6:.0f} MB"
            )
    except OSError:
        pass
    return None
