"""Ventana de la app (pywebview). Arranque: `python -m mod_updater.gui`, `ModUpdater.pyw` o el .exe."""

from __future__ import annotations

import os
import sys
from pathlib import Path

WEB = Path(__file__).resolve().parent / "web"
# assets/ está en la raíz del proyecto; en el .exe, PyInstaller lo deja en la misma posición relativa.
ICON = Path(__file__).resolve().parents[2] / "assets" / "ModUpdater.ico"
APP_ID = "racsoga.ModUpdater"


def _taskbar_identity() -> None:
    """Identificador propio para que Windows agrupe la ventana con su icono (no el de Python)."""
    if os.name != "nt":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except (AttributeError, OSError):
        pass


def _set_window_icon(window) -> None:
    """Pone el icono en la ventana (WinForms) desde su propio hilo de interfaz."""
    if os.name != "nt" or not ICON.exists():
        return
    try:
        from System import Action  # pythonnet
        from System.Drawing import Icon

        form = window.native
        form.Invoke(Action(lambda: setattr(form, "Icon", Icon(str(ICON)))))
    except Exception:  # noqa: BLE001 - sin icono la app funciona igual
        pass


def main() -> int:
    import webview

    from .api import Api

    _taskbar_identity()
    api = Api()
    window = webview.create_window(
        "Mod Updater",
        str(WEB / "index.html"),
        js_api=api,
        width=1200,
        height=840,
        min_size=(760, 560),
        background_color="#111214",
    )
    api._attach(window)
    window.events.shown += lambda: _set_window_icon(window)
    webview.start(debug=os.environ.get("MOD_UPDATER_DEBUG") == "1")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
