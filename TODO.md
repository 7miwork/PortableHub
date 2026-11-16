# PortableHub — Was noch fehlt / Checkliste

Stand: alle 6 Etappen implementiert, 9/9 Tests grün, `dist\PortableHub.exe` baut und startet.

## 1. Erster echter Inhalt (Katalog ist noch leer)

Der Katalog `catalog.json` hat aktuell **keine Apps**. Für den ersten
End-to-End-Test brauche ich von dir:

- Einen App-Ordner zum Veröffentlichen, z. B. ein portables Tool
  (Notepad++, VLC, 7-Zip, qBittorrent …) — als entpacktes Portable-Verzeichnis.
- Die Start-Exe innerhalb des Ordners (`--exe`).

Befehl (PowerShell, im Repo-Ordner):

```powershell
python tools\publish.py "C:\Pfad\zur\App" `
    --id notepadpp --name "Notepad++" --category Coding `
    --version 8.7.1 --exe notepad++.exe `
    --description "Mächtiger Texteditor"
```

→Legt ZIP an, lädt es ins GitHub-Release `apps` hoch, committed `catalog.json`.
Danach erscheint die App sofort im Download-Manager.

## 2. Manuelle GUI-Tests (ich konnte nur den Start prüfen)

- [ ] `PortableHub.exe` auf dem Stick: Tray-Icon erscheint in der Taskleiste
- [ ] Tray Rechtsklick → Kategorien → App starten (CWD = App-Ordner)
- [ ] Download-Manager: Liste, Suche, ☐-Auswahl, Installieren mit Fortschritt
- [ ] Abbrechen-Button während eines Downloads
- [ ] Update-Flow: `data`-Ordner bleibt nach Update erhalten
- [ ] Manipuliertes ZIP (falscher Hash) wird abgelehnt → Fehlermeldung prüfen
- [ ] Stick an anderen PC / anderem Laufwerksbuchstaben → alles läuft

## 3. Optionale Entscheidungen

- [ ] **App-Icon für PortableHub.exe** — eigene `.ico`-Datei, dann in
      `build.ps1` `--icon icon.ico` ergänzen (Tray nutzt aktuell
      `IDI_APPLICATION`, also das Windows-Standardicon)
- [ ] **Autostart-Option** — `settings.json` hat `start_with_windows`, aber
      es gibt noch keinen Mechanismus (USB-Stick starten ist eh manuell;
      evtl. einfach weglassen oder Doku anpassen)
- [ ] **Update-Prüfung beim Start** — `check_updates_on_start` existiert in
      den Settings, ist aber noch nicht im GUI verdrahtet
- [ ] **Katalog-URL ändern** — geht bereits über `PortableHub/settings.json`
      (`catalog_url`), evtl. im GUI ein Einstellungs-Dialog ergänzen

## 4. Bekannte technische Grenzen

- Tray-Menü-Icons: Best Effort via `SHGetFileInfo`; Apps ohne Exe-Icon
  erscheinen textbasiert.
- Tray nur unter Windows; Linux → Fenster-Modus.
- ExFAT: keine Symlinks — portable Apps müssen symlink-frei sein.
- `publish.py --remove` löscht nur den Katalogeintrag; das Release-Asset
  bleibt (muss ggf. von Hand im GitHub-Release `apps` gelöscht werden).

## 5. Nächster sinnvoller Schritt

1. Du gibst mir einen App-Ordner (oder sagst, welche App zuerst rein soll)
   → ich führe `publish.py` aus und verifiziere den kompletten Flow.
2. Du testest `dist\PortableHub.exe` einmal manuell durch (Punkte unter 2).
3. Optional: Icon + Autostart-Entscheidung klären.
