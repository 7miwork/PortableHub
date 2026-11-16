# PortableHub

Eigenständiges, portables Startmenü mit Download-Manager für den USB-Stick —
ähnlich PortableApps.com / LiberKey, aber komplett eigenständig.

**Keine Installation, keine Registry, keine Python nötig** — alles läuft aus
einem einzigen `PortableHub.exe` plus den Ordnern `Apps/` und `PortableHub/`.

## Auf dem Stick

```
<Stick>/
├── PortableHub.exe          <- Programmstart
├── Apps/<app-id>/...        <- installierte Apps (entpackt)
└── PortableHub/
    ├── installed.json       <- lokaler Installationsstand
    ├── settings.json        <- Katalog-URL, Sprache, Optionen
    ├── catalog_cache.json   <- letzter Katalog (Offline-Fallback)
    └── tmp/                 <- Downloads/Entpacken (wird aufgeräumt)
```

Alle Pfade sind relativ zur `PortableHub.exe` — der Stick funktioniert unter
**jedem Laufwerksbuchstaben** und auf Windows 10/11 (Linux: Fenster-Modus,
Tray nur unter Windows).

## Startmodi

| Aufruf | Verhalten |
|---|---|
| `PortableHub.exe` | Tray-Icon (Windows) + Download-Manager-Fenster |
| `PortableHub.exe --manager` | nur Download-Manager |
| `PortableHub.exe --menu` | nur Startmenü-Fenster (Kachelansicht) |
| `PortableHub.exe --tray` | nur Tray-Icon |

Tray-Menü: Kategorien als Untermenüs → Apps starten sich per Klick
(Arbeitsverzeichnis = App-Ordner), dazu „Download-Manager öffnen",
„Menü neu laden“, „Beenden“.

## Katalog

`catalog.json` ist die App-Liste. Pro App:

```json
{
  "id": "notepadpp",
  "name": "Notepad++",
  "category": "Coding",
  "description": "Mächtiger Texteditor",
  "platform": "windows",
  "version": "8.7.1",
  "exe": "notepad++.exe",
  "size": 4300000,
  "sha256": "<hex>",
  "url": "https://github.com/7miwork/PortableHub/releases/download/apps/notepadpp-8.7.1.zip",
  "icon": "optional.ico"
}
```

- `platform`: `windows` | `linux` | `any` — der Client zeigt nur passende Apps.
- `size`/`sha256`: werden vor dem Entpacken geprüft; manipulierte ZIPs werden abgelehnt.
- Die Download-URL zeigt auf **Release-Assets** (Tag `apps`) — keine GitHub-API.
- Offline? Der zuletzt gecachte Katalog aus `PortableHub/catalog_cache.json`
  wird angezeigt.
- Katalog-URL einstellbar in `PortableHub/settings.json` (`catalog_url`).

## Download-Manager

- Apps nach Kategorie gruppiert, Suchfeld, Status (Nicht installiert /
  Installiert / Update verfügbar), Größe, Beschreibung.
- Mehrfachauswahl per Klick auf die ☐/☑-Spalte oder Leertaste.
- Installieren / Aktualisieren / Deinstallieren / „Alle Updates installieren“.
- Download im Hintergrund-Thread mit Fortschrittsbalken, Abbrechen und
  3 automatischen Wiederholungen bei Netzwerkfehlern.
- **Update-Sicherheit:** die Ordner `data`/`Data` einer App bleiben erhalten
  (Benutzerdaten gehen nicht verloren).

## App veröffentlichen

```powershell
python tools/publish.py <App-Ordner> `
    --id notepadpp --name "Notepad++" --category Coding `
    --version 8.7.1 --exe notepad++.exe
```

Der Befehl zippt den Ordner (Inhalt = ZIP-Root), berechnet SHA-256 und Größe,
aktualisiert `catalog.json`, lädt das ZIP per `gh release upload` in das
Release `apps` hoch (wird bei Bedarf angelegt) und committed + pusht den
Katalog. Danach erscheint die App automatisch im Download-Manager.

Weitere Befehle:

```powershell
python tools/publish.py --list            # Katalog anzeigen
python tools/publish.py --remove <id>     # App aus dem Katalog entfernen
```

## Aus dem Quelltext starten (Entwicklung)

```powershell
python -m portablehub            # wie PortableHub.exe
python -m unittest discover -s tests -v
.\build.ps1                      # baut dist\PortableHub.exe (PyInstaller)
```

## Sicherheitshinweise

- ZIP-Pfade werden auf `../`-Durchgriffe geprüft.
- SHA-256-Mismatch → Installation abgebrochen, keine Dateien geschrieben.
- `mod`-artige Binärformate werden nie geparst; `installed.json`/`settings.json`
  sind einfaches UTF-8-JSON.
- Updates ersetzen die App, bewahren aber `data`/`Data`.

## Bekannte Grenzen

- Tray-Icons in den Menü-Unterpunkten werden über `SHGetFileInfo` extrahiert
  (Best Effort); ohne Exe-Icon erscheint der Eintrag textbasiert.
- Der Tray benötigt Windows; unter Linux startet automatisch der Fenster-Modus.
- ExFAT: keine Symlinks — alle Apps müssen ohne Symlinks auskommen.
