# PyInstaller: genera dist/ModUpdater.exe (un solo archivo, sin consola).
#   .venv\Scripts\python -m PyInstaller packaging\ModUpdater.spec --noconfirm
#
# Solo se empaqueta lo que se lista aquí: nunca .env, .cache, config.toml ni jars.
# El simulador de desarrollo (dev-mock.js) tampoco va en el ejecutable.
from pathlib import Path

ROOT = Path(SPECPATH).parent  # noqa: F821 (SPECPATH lo define PyInstaller)
WEB = ROOT / "mod_updater" / "gui" / "web"
ICON = ROOT / "assets" / "ModUpdater.ico"

datas = []
for f in WEB.rglob("*"):
    if f.is_file() and f.name != "dev-mock.js":
        datas.append((str(f), str(f.parent.relative_to(ROOT))))
for f in (ROOT / "mod_updater" / "locales").glob("*.json"):
    datas.append((str(f), "mod_updater/locales"))

a = Analysis(  # noqa: F821
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT)],
    datas=datas,
    hiddenimports=["keyring.backends.Windows", "clr"],
    excludes=["tkinter", "pytest", "PIL", "PyInstaller"],
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821
exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="ModUpdater",
    console=False,
    icon=str(ICON) if ICON.exists() else None,
    upx=False,
)
