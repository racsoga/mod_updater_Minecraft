"""Abre Mod Updater sin consola (doble clic). Usa el entorno .venv del proyecto si existe."""

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
VENV_PYTHONW = HERE / ".venv" / "Scripts" / "pythonw.exe"

if VENV_PYTHONW.exists() and Path(sys.executable).resolve() != VENV_PYTHONW.resolve():
    subprocess.Popen([str(VENV_PYTHONW), str(Path(__file__).resolve())], cwd=HERE)
    sys.exit(0)

sys.path.insert(0, str(HERE))
from mod_updater.gui.app import main  # noqa: E402

sys.exit(main())
