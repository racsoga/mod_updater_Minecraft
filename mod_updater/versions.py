"""Versiones publicadas de Minecraft (solo "release"), para el desplegable de Ajustes.

Se consultan a Modrinth (`/v2/tag/game_version`), se guardan 7 días en caché y,
sin conexión, se usa una lista de respaldo.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from .net import ApiError

CACHE_TTL = 7 * 24 * 3600
# Respaldo sin conexión (de más nueva a más vieja). Solo versiones con mods habituales.
FALLBACK = [
    "26.3", "26.2", "26.1.2", "26.1.1", "26.1",
    "1.21.11", "1.21.10", "1.21.9", "1.21.8", "1.21.7", "1.21.6", "1.21.5", "1.21.4", "1.21.3", "1.21.2", "1.21.1", "1.21",
    "1.20.6", "1.20.4", "1.20.2", "1.20.1", "1.20",
    "1.19.4", "1.19.2", "1.18.2", "1.17.1", "1.16.5", "1.12.2",
]


def _version_key(v: str) -> tuple:
    return tuple(int(p) if p.isdigit() else 0 for p in v.split("."))


def fetch_releases(modrinth) -> list[str]:
    data = modrinth._call("GET", "/v2/tag/game_version") or []
    releases = [d for d in data if isinstance(d, dict) and d.get("version_type") == "release" and d.get("version")]
    releases.sort(key=lambda d: d.get("date") or "", reverse=True)
    return [d["version"] for d in releases]


def minecraft_versions(modrinth, cache_file: Path, *, now: float | None = None, include: list[str] | None = None) -> list[str]:
    """Lista de versiones "release" de más nueva a más vieja. `include` añade versiones
    que deben aparecer aunque no estén (la deducida o la guardada)."""
    now = time.time() if now is None else now
    versions: list[str] | None = None
    try:
        cached = json.loads(cache_file.read_text(encoding="utf-8"))
        if now - float(cached.get("time", 0)) < CACHE_TTL and cached.get("versions"):
            versions = list(cached["versions"])
    except (OSError, ValueError, TypeError):
        pass
    if versions is None:
        try:
            versions = fetch_releases(modrinth)
            if versions:
                cache_file.parent.mkdir(parents=True, exist_ok=True)
                cache_file.write_text(json.dumps({"time": now, "versions": versions}), encoding="utf-8")
        except (ApiError, OSError, ValueError):
            versions = None
    versions = versions or list(FALLBACK)
    for v in include or []:
        if v and v not in versions:
            versions.append(v)
    versions.sort(key=_version_key, reverse=True)
    return versions
