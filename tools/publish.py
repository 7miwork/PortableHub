#!/usr/bin/env python3
"""Veroeffentlicht eine portable App im PortableHub-Katalog.

Aufruf:
  python tools/publish.py <Ordner> --id notepadpp --name "Notepad++" \\
      --category Coding --version 8.7.1 --exe notepad++.exe \\
      [--description "..."] [--platform windows] [--icon icon.ico]
  python tools/publish.py --list
  python tools/publish.py --remove <id>

Schritte: ZIP erzeugen -> SHA-256 -> catalog.json aktualisieren ->
"gh release upload apps <zip> --repo 7miwork/PortableHub --clobber" ->
git commit + push.
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CATALOG = REPO_ROOT / "catalog.json"
REPO = "7miwork/PortableHub"
RELEASE_TAG = "apps"
CHUNK = 1024 * 256


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def make_zip(folder: Path, out: Path) -> None:
    """Zippt den Inhalt von folder direkt ins ZIP-Root."""
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for p in sorted(folder.rglob("*")):
            if p.is_file():
                zf.write(p, p.relative_to(folder).as_posix())


def load_catalog() -> dict:
    with open(CATALOG, "r", encoding="utf-8") as f:
        return json.load(f)


def save_catalog(cat: dict) -> None:
    with open(CATALOG, "w", encoding="utf-8") as f:
        json.dump(cat, f, ensure_ascii=False, indent=2)
        f.write("\n")


def find_app(cat: dict, app_id: str):
    for a in cat.get("apps", []):
        if a.get("id") == app_id:
            return a
    return None


def gh(*args, check=True) -> subprocess.CompletedProcess:
    return subprocess.run(["gh", *args], check=check, capture_output=True, text=True)


def ensure_release() -> None:
    """Stellt sicher, dass das Release 'apps' existiert."""
    r = subprocess.run(
        ["gh", "release", "view", RELEASE_TAG, "--repo", REPO],
        capture_output=True, text=True)
    if r.returncode == 0:
        return
    print(f"Release '{RELEASE_TAG}' existiert nicht, lege es an …")
    gh("release", "create", RELEASE_TAG, "--repo", REPO,
       "--title", "PortableHub Apps", "--notes", "App-Archive fuer PortableHub")


def upload_asset(zip_path: Path) -> str:
    """Laedt das ZIP ins Release hoch und gibt die Download-URL zurueck."""
    ensure_release()
    gh("release", "upload", RELEASE_TAG, str(zip_path), "--repo", REPO, "--clobber")
    # Download-URL: github.com/<repo>/releases/download/<tag>/<asset>
    return (f"https://github.com/{REPO}/releases/download/"
            f"{RELEASE_TAG}/{zip_path.name}")


def git_commit_push(message: str) -> None:
    subprocess.run(["git", "add", "catalog.json"], cwd=REPO_ROOT, check=True)
    r = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=REPO_ROOT)
    if r.returncode == 0:
        print("catalog.json unveraendert, kein Commit noetig.")
        return
    subprocess.run(["git", "commit", "-m", message], cwd=REPO_ROOT, check=True)
    subprocess.run(["git", "push"], cwd=REPO_ROOT, check=True)


def cmd_publish(args) -> int:
    folder = Path(args.folder).resolve()
    if not folder.is_dir():
        print(f"Fehler: Ordner nicht gefunden: {folder}", file=sys.stderr)
        return 2
    exe_rel = args.exe
    if not (folder / exe_rel).exists():
        print(f"Warnung: '{exe_rel}' nicht im Ordner gefunden.", file=sys.stderr)

    app_id = args.id
    if not app_id.replace("-", "").replace("_", "").isalnum():
        print("Fehler: ungueltige App-ID (nur Buchstaben, Ziffern, - _).", file=sys.stderr)
        return 2

    # 1) ZIP erzeugen
    with tempfile.TemporaryDirectory(prefix="ph-publish-") as td:
        zip_path = Path(td) / f"{app_id}-{args.version}.zip"
        print(f"ZIP wird erstellt: {zip_path.name} …")
        make_zip(folder, zip_path)
        size = zip_path.stat().st_size
        digest = sha256_file(zip_path)

        # 2) Katalog aktualisieren
        cat = load_catalog()
        cat.setdefault("apps", [])
        entry = find_app(cat, app_id)
        is_new = entry is None
        if is_new:
            entry = {"id": app_id}
            cat["apps"].append(entry)
        entry.update({
            "name": args.name,
            "category": args.category,
            "description": args.description or "",
            "platform": args.platform,
            "version": args.version,
            "exe": exe_rel.replace("\\", "/"),
            "size": size,
            "sha256": digest,
            "url": "",  # wird nach Upload gesetzt
        })
        if args.icon:
            entry["icon"] = args.icon

        # 3) Upload (vor Commit, damit URL bekannt ist)
        print("Release-Asset wird hochgeladen …")
        url = upload_asset(zip_path)
        entry["url"] = url
        save_catalog(cat)

    # 4) Commit + Push
    action = "Hinzufuegen" if is_new else "Aktualisieren"
    git_commit_push(f"catalog: {action} {app_id} v{args.version}")
    print(f"Fertig: {args.name} v{args.version} ({size/1e6:.1f} MB) -> {url}")
    return 0


def cmd_list(_args) -> int:
    cat = load_catalog()
    apps = cat.get("apps", [])
    if not apps:
        print("Katalog ist leer.")
        return 0
    print(f"{'ID':<20} {'Name':<25} {'Kategorie':<15} {'Version':<10} {'Plattform'}")
    for a in sorted(apps, key=lambda x: x.get("id", "")):
        print(f"{a.get('id',''):<20} {a.get('name',''):<25} "
              f"{a.get('category',''):<15} {a.get('version',''):<10} {a.get('platform','')}")
    return 0


def cmd_remove(args) -> int:
    cat = load_catalog()
    apps = cat.get("apps", [])
    before = len(apps)
    cat["apps"] = [a for a in apps if a.get("id") != args.id]
    if len(cat["apps"]) == before:
        print(f"App '{args.id}' nicht im Katalog.")
        return 1
    save_catalog(cat)
    git_commit_push(f"catalog: Entferne {args.id}")
    # Hinweis: Release-Asset bleibt (historische Downloads)
    print(f"'{args.id}' aus dem Katalog entfernt. "
          f"Asset im Release '{RELEASE_TAG}' ggf. manuell loeschen.")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="PortableHub App veroeffentlichen")
    p.add_argument("folder", nargs="?", help="Ordner mit der App (Inhalt = ZIP-Root)")
    p.add_argument("--id", help="eindeutige App-ID (z. B. notepadpp)")
    p.add_argument("--name", help="Anzeigename")
    p.add_argument("--category", default="Sonstiges", help="Kategorie")
    p.add_argument("--version", help="Versionsnummer")
    p.add_argument("--exe", help="Pfad zur Start-Exe relativ zum Ordner")
    p.add_argument("--description", default="", help="Beschreibung")
    p.add_argument("--platform", default="windows", choices=["windows", "linux", "any"])
    p.add_argument("--icon", help="Pfad zu einem Icon (optional)")
    p.add_argument("--list", action="store_true", help="Katalog auflisten")
    p.add_argument("--remove", metavar="ID", help="App aus dem Katalog entfernen")
    args = p.parse_args()

    if args.list:
        return cmd_list(args)
    if args.remove:
        return cmd_remove(args)
    if not args.folder:
        p.error("Ordner fehlt (oder --list / --remove verwenden)")
    for req in ("id", "name", "version", "exe"):
        if not getattr(args, req):
            p.error(f"--{req} ist erforderlich")
    return cmd_publish(args)


if __name__ == "__main__":
    sys.exit(main())
