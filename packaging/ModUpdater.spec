# PyInstaller: genera Mod Updater para Windows.
#
#   Un solo archivo (por defecto):  dist/ModUpdater.exe
#   En carpeta (MODUPDATER_ONEDIR=1): dist/ModUpdater/ModUpdater.exe + sus DLL (se reparte en zip;
#   suele dar menos falsos positivos de antivirus que el .exe único).
#
# Usar packaging/build.ps1, que además compila el cargador de PyInstaller desde el código
# fuente, calcula los SHA-256 y crea el zip.
#
# Solo se empaqueta lo que se lista aquí: nunca .env, .cache, config.toml ni jars.
# El simulador de desarrollo (dev-mock.js) tampoco va dentro.
import os
import re
from pathlib import Path

from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo,
    StringFileInfo,
    StringStruct,
    StringTable,
    VarFileInfo,
    VarStruct,
    VSVersionInfo,
)

ROOT = Path(SPECPATH).parent  # noqa: F821 (SPECPATH lo define PyInstaller)
WEB = ROOT / "mod_updater" / "gui" / "web"
ICON = ROOT / "assets" / "ModUpdater.ico"
ONEDIR = os.environ.get("MODUPDATER_ONEDIR") == "1"

VERSION = re.search(r'__version__\s*=\s*"([^"]+)"', (ROOT / "mod_updater" / "__init__.py").read_text(encoding="utf-8")).group(1)
NUMS = tuple(int(x) for x in (VERSION.split(".") + ["0", "0", "0"])[:4])

# Información de versión del ejecutable (Propiedades > Detalles en Windows). Sin ella, el .exe
# parece anónimo y algunos antivirus le dan menos confianza.
version_info = VSVersionInfo(
    ffi=FixedFileInfo(filevers=NUMS, prodvers=NUMS, mask=0x3F, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0),
    kids=[
        StringFileInfo([StringTable("040904B0", [
            StringStruct("CompanyName", "Oscar Gonzalez"),
            StringStruct("FileDescription", "Mod Updater - actualizador de mods de Minecraft"),
            StringStruct("FileVersion", VERSION),
            StringStruct("InternalName", "ModUpdater"),
            StringStruct("LegalCopyright", "Copyright (c) 2026 Oscar Gonzalez. Licencia MIT."),
            StringStruct("OriginalFilename", "ModUpdater.exe"),
            StringStruct("ProductName", "Mod Updater"),
            StringStruct("ProductVersion", VERSION),
            StringStruct("Comments", "https://github.com/racsoga/mod_updater_Minecraft"),
        ])]),
        VarFileInfo([VarStruct("Translation", [0x0409, 1200])]),
    ],
)

datas = []
for f in WEB.rglob("*"):
    if f.is_file() and f.name != "dev-mock.js":
        datas.append((str(f), str(f.parent.relative_to(ROOT))))
for f in (ROOT / "mod_updater" / "locales").glob("*.json"):
    datas.append((str(f), "mod_updater/locales"))
for f in (ROOT / "mod_updater" / "knowledge").glob("*.json"):  # base de conocimiento (categorías...)
    datas.append((str(f), "mod_updater/knowledge"))
datas.append((str(ICON), "assets"))  # icono de la ventana (gui/app.py lo busca en assets/)

a = Analysis(  # noqa: F821
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT)],
    datas=datas,
    hiddenimports=["keyring.backends.Windows", "clr"],
    excludes=["tkinter", "pytest", "PIL", "PyInstaller"],
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821

common = dict(
    name="ModUpdater",
    console=False,
    icon=str(ICON),
    version=version_info,
    upx=False,  # sin UPX: la compresión UPX es un disparador clásico de falsos positivos
)

if ONEDIR:
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, **common)  # noqa: F821
    coll = COLLECT(exe, a.binaries, a.datas, name="ModUpdater", upx=False)  # noqa: F821
else:
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], **common)  # noqa: F821
