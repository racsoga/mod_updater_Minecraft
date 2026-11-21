"""Aviso de nuevas versiones de Mod Updater (GitHub Releases).

- Como mucho una consulta al día (caché en `%APPDATA%\\mod_updater\\cache`).
- Sin red o con una respuesta inesperada, no se avisa de nada (y no molesta).
- No se actualiza solo: el aviso abre la página de la Release en el navegador (menos riesgo y
  menos falsos positivos de antivirus). Las notas pasan por la misma limpieza que los changelogs.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

import requests

from .changelog import markdown_to_html

RELEASES_URL = "https://api.github.com/repos/racsoga/mod_updater_Minecraft/releases/latest"
RELEASE_PAGE_PREFIX = "https://github.com/racsoga/mod_updater_Minecraft/releases/"
CHECK_EVERY = 24 * 3600
_VERSION = re.compile(r"^v?(\d+)\.(\d+)(?:\.(\d+))?$")


def parse_version(text: str) -> tuple[int, int, int] | None:
    """"v0.3.0" -> (0, 3, 0). Las versiones previas (beta...) no cuentan."""
    m = _VERSION.match((text or "").strip())
    return (int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)) if m else None


def is_newer(candidate: str, current: str) -> bool:
    a, b = parse_version(candidate), parse_version(current)
    return bool(a and b and a > b)


def _fetch(session) -> dict | None:
    try:
        resp = session.get(RELEASES_URL, timeout=8, headers={"Accept": "application/vnd.github+json"})
        data = resp.json() if resp.ok else None
    except (requests.RequestException, ValueError, OSError):  # sin red o respuesta rara: no molestar
        return None
    if not isinstance(data, dict) or data.get("draft") or data.get("prerelease"):
        return None
    tag, url = data.get("tag_name"), data.get("html_url")
    if not isinstance(tag, str) or parse_version(tag) is None:
        return None
    if not isinstance(url, str) or not url.startswith(RELEASE_PAGE_PREFIX):
        return None  # solo se abre la página oficial de Releases
    body = data.get("body") if isinstance(data.get("body"), str) else ""
    return {"version": ".".join(map(str, parse_version(tag))), "url": url,
            "notes_html": markdown_to_html(body[:20000], flag=False)}


def check_latest(current: str, *, cache_path: Path, session=None, now: float | None = None) -> dict | None:
    """Datos de la última versión publicada si es posterior a `current`; si no, None."""
    now = time.time() if now is None else now
    latest = None
    try:
        cached = json.loads(Path(cache_path).read_text(encoding="utf-8"))
        age = now - float(cached["checked"])
        if 0 <= age < CHECK_EVERY and isinstance(cached.get("latest"), dict):  # una fecha futura no vale
            latest = cached["latest"]
    except (OSError, ValueError, KeyError, TypeError):
        latest = None
    if latest is None:
        latest = _fetch(session or requests.Session())
        if latest is None:
            return None  # sin red o respuesta rara: se vuelve a probar en el próximo arranque
        try:
            Path(cache_path).parent.mkdir(parents=True, exist_ok=True)
            Path(cache_path).write_text(json.dumps({"checked": now, "latest": latest}), encoding="utf-8")
        except OSError:
            pass
    if latest and isinstance(latest.get("version"), str) and is_newer(latest["version"], current):
        return latest
    return None
