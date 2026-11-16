# Baut PortableHub.exe mit PyInstaller (Single-File, keine Python noetig).
# Aufruf:  powershell -ExecutionPolicy Bypass -File build.ps1
# Ergebnis: dist\PortableHub.exe  ->  auf den Stick ins Wurzelverzeichnis kopieren.

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

# PyInstaller installieren, falls noetig
python -c "import PyInstaller" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "PyInstaller wird installiert ..."
    python -m pip install --user pyinstaller
}

python -m PyInstaller `
    --onefile `
    --noconsole `
    --name PortableHub `
    --clean `
    --add-data "catalog.json;." `
    app.py

Write-Host ""
Write-Host "Fertig: dist\PortableHub.exe"
Write-Host "Auf den Stick kopieren als: <Stick>\PortableHub.exe"
Write-Host "Die App legt automatisch <Stick>\Apps\ und <Stick>\PortableHub\ an."
