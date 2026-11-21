"""Ventana de la app (pywebview). Arranque: `python -m mod_updater.gui`, `ModUpdater.pyw` o el .exe."""

from __future__ import annotations

import os
import sys
import webbrowser
from pathlib import Path

from ..i18n import t

WEB = Path(__file__).resolve().parent / "web"
# assets/ está en la raíz del proyecto; en el .exe, PyInstaller lo deja en la misma posición relativa.
ICON = Path(__file__).resolve().parents[2] / "assets" / "ModUpdater.ico"
APP_ID = "racsoga.ModUpdater"
WEBVIEW2_URL = "https://developer.microsoft.com/microsoft-edge/webview2/"

DEFAULT_SIZE = (1200, 840)   # px lógicos (a 100 % de escala)
MIN_SIZE = (760, 560)
SCREEN_FRACTION = 0.92       # la ventana nunca ocupa más del 92 % del área útil


def initial_size(work_area: tuple[float, float] | None) -> tuple[tuple[int, int], tuple[int, int]]:
    """(tamaño inicial, tamaño mínimo) para que la ventana quepa siempre en la pantalla.

    `work_area` es el área útil (sin la barra de tareas) en px lógicos, o None si no se sabe.
    """
    if not work_area:
        return DEFAULT_SIZE, MIN_SIZE
    max_w, max_h = int(work_area[0] * SCREEN_FRACTION), int(work_area[1] * SCREEN_FRACTION)
    size = (min(DEFAULT_SIZE[0], max_w), min(DEFAULT_SIZE[1], max_h))
    return size, (min(MIN_SIZE[0], size[0]), min(MIN_SIZE[1], size[1]))


def screen_work_area() -> tuple[float, float] | None:
    """Área útil de la pantalla principal en px lógicos (descuenta escala y barra de tareas)."""
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        user32.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
        user32.SetThreadDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        # Solo para este hilo y solo durante la consulta: área real en px físicos y DPI real.
        previous = user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))  # PER_MONITOR_AWARE_V2
        try:
            rect = wintypes.RECT()
            if not user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0):  # SPI_GETWORKAREA
                return None
            dpi = user32.GetDpiForSystem() or 96
        finally:
            if previous:
                user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(previous))
        scale = dpi / 96
        return ((rect.right - rect.left) / scale, (rect.bottom - rect.top) / scale)
    except (AttributeError, OSError):
        return None


def webview2_installed() -> bool:
    """¿Está instalado el runtime de Microsoft Edge WebView2? (lo necesita la ventana)."""
    if os.name != "nt":
        return True
    try:
        import winreg
    except ImportError:  # pragma: no cover
        return True
    guid = r"{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
    places = [
        (winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{guid}"),
        (winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\Microsoft\EdgeUpdate\Clients\{guid}"),
        (winreg.HKEY_CURRENT_USER, rf"Software\Microsoft\EdgeUpdate\Clients\{guid}"),
    ]
    for root, path in places:
        try:
            with winreg.OpenKey(root, path) as key:
                version, _ = winreg.QueryValueEx(key, "pv")
                if version and version != "0.0.0.0":
                    return True
        except OSError:
            continue
    return False


def _message_box(text: str, yes_no: bool = False) -> bool:
    """Cuadro de diálogo nativo de Windows (sirve aunque la ventana web no pueda abrirse)."""
    try:
        import ctypes

        flags = 0x10 | (0x4 if yes_no else 0)  # MB_ICONERROR | MB_YESNO
        return ctypes.windll.user32.MessageBoxW(None, text, "Mod Updater", flags) == 6  # IDYES
    except (AttributeError, OSError):
        print(text, file=sys.stderr)
        return False


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
    from .api import Api

    api = Api()  # fija el idioma de los mensajes según los ajustes
    if not webview2_installed():
        if _message_box(t("app.no_webview2"), yes_no=True):
            webbrowser.open(WEBVIEW2_URL)
        return 1

    import webview

    _taskbar_identity()
    size, min_size = initial_size(screen_work_area())
    window = webview.create_window(
        "Mod Updater",
        str(WEB / "index.html"),
        js_api=api,
        width=size[0],
        height=size[1],
        min_size=min_size,
        background_color="#111214",
    )
    api._attach(window)
    window.events.shown += lambda: _set_window_icon(window)

    def on_closing():
        # Cerrar a mitad de una actualización la deja incompleta: pedir confirmación.
        if api._is_applying():
            return bool(window.create_confirmation_dialog(t("close.title"), t("close.message")))
        return True

    window.events.closing += on_closing
    try:
        webview.start(debug=os.environ.get("MOD_UPDATER_DEBUG") == "1")
    except Exception as exc:  # noqa: BLE001 - sin consola: el usuario debe ver el motivo
        _message_box(t("app.start_failed", error=type(exc).__name__))
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
