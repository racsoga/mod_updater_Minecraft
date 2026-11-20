"""Ventana de la app (pywebview). Arranque: `python -m mod_updater.gui` o `ModUpdater.pyw`."""

from __future__ import annotations

import os
import sys
from pathlib import Path

WEB = Path(__file__).resolve().parent / "web"


def main() -> int:
    import webview

    from .api import Api

    api = Api()
    window = webview.create_window(
        "Mod Updater",
        str(WEB / "index.html"),
        js_api=api,
        width=1200,
        height=840,
        min_size=(760, 560),
        background_color="#000000",
    )
    api._attach(window)
    webview.start(debug=os.environ.get("MOD_UPDATER_DEBUG") == "1")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
