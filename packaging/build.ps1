# Compila Mod Updater para Windows: ModUpdater.exe (un archivo) y ModUpdater-<versión>-carpeta.zip.
#
#   powershell -ExecutionPolicy Bypass -File packaging\build.ps1 [-Python .venv\Scripts\python.exe]
#
# 1. Reinstala PyInstaller compilando su cargador (bootloader) desde el código fuente: el
#    precompilado lo usan muchos programas maliciosos y algunos antivirus lo marcan por parecido.
#    Necesita las Build Tools de Visual Studio (C++). Usar -SkipBootloader para no recompilarlo.
# 2. Compila las dos variantes con packaging/ModUpdater.spec.
# 3. Escribe los SHA-256 junto a cada archivo.
param(
    [string]$Python = ".venv\Scripts\python.exe",
    [switch]$SkipBootloader
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$version = (& $Python -c "import mod_updater; print(mod_updater.__version__)").Trim()
Write-Host "Mod Updater $version"

if (-not $SkipBootloader) {
    $pyiVersion = (Select-String -Path requirements-dev.txt -Pattern '^pyinstaller==(.+)$').Matches[0].Groups[1].Value
    Write-Host "Compilando el cargador de PyInstaller $pyiVersion desde el código fuente..."
    $env:PYINSTALLER_COMPILE_BOOTLOADER = "1"
    & $Python -m pip install --force-reinstall --no-deps --no-binary pyinstaller "pyinstaller==$pyiVersion"
    if ($LASTEXITCODE -ne 0) { throw "No se pudo compilar el cargador de PyInstaller" }
}

$dist = Join-Path $root "dist"
if (Test-Path $dist) { Remove-Item -Recurse -Force $dist }

# Un solo archivo
Remove-Item Env:MODUPDATER_ONEDIR -ErrorAction SilentlyContinue
& $Python -m PyInstaller packaging\ModUpdater.spec --noconfirm --distpath dist --workpath build\work-onefile
if ($LASTEXITCODE -ne 0) { throw "Falló la compilación (un archivo)" }

# En carpeta, comprimida en zip
$env:MODUPDATER_ONEDIR = "1"
& $Python -m PyInstaller packaging\ModUpdater.spec --noconfirm --distpath dist\carpeta --workpath build\work-onedir
if ($LASTEXITCODE -ne 0) { throw "Falló la compilación (carpeta)" }
Remove-Item Env:MODUPDATER_ONEDIR
$zip = "dist\ModUpdater-$version-carpeta.zip"
# Con zipfile de Python: Compress-Archive de PowerShell 5.1 falla con archivos que un antivirus
# tiene abiertos un instante (p. ej. base_library.zip).
& $Python -c "import shutil, sys; shutil.make_archive(sys.argv[1], 'zip', 'dist/carpeta', 'ModUpdater')" ($zip -replace '\.zip$', '')
if ($LASTEXITCODE -ne 0) { throw "No se pudo crear el zip" }
Remove-Item -Recurse -Force dist\carpeta

foreach ($file in @("dist\ModUpdater.exe", $zip)) {
    $hash = (Get-FileHash $file -Algorithm SHA256).Hash.ToLower()
    $name = Split-Path $file -Leaf
    "$hash  $name" | Out-File -Encoding ascii "$file.sha256"
    Write-Host "$hash  $name"
}
