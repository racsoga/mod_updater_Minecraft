"""Análisis de la colección: cifras y listas a partir del resultado de una revisión.

Función pura (sin red ni disco): la pestaña Análisis llama a `analyze` con los resultados
de la última revisión.
"""

from __future__ import annotations

import time
from collections import Counter
from datetime import datetime

from .categories import LIBRARY, OTHER, OURS
from .resolver import ACTUALIZABLE, AL_DIA, CF, DESCARGA_MANUAL, MR, Resolution

STALE_DAYS = 365
TOP_HEAVIEST = 5


def _timestamp(iso: str | None) -> float | None:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _orphans(installed: list[Resolution]) -> list[Resolution]:
    """Librerías que ningún otro mod instalado necesita (ni según la API ni según el jar).
    Se repite hasta estabilizarse: si una librería solo la necesitaba otra huérfana,
    también lo es."""
    remaining = list(installed)
    orphans: list[Resolution] = []
    while True:
        needed_keys: set[tuple[str, str]] = set()
        needed_ids: set[str] = set()
        for r in remaining:
            needed_keys |= {d.key for d in r.current_deps}
            if r.mod is not None:
                needed_ids |= set(r.mod.requires)
        found = []
        for r in remaining:
            if not r.is_library:
                continue
            own_ids = {r.mod.mod_id, *r.mod.extra_mod_ids} - {None} if r.mod else set()
            others_keys = needed_keys - {d.key for d in r.current_deps}
            if not (r.known_ids & others_keys) and not (own_ids & needed_ids):
                found.append(r)
        if not found:
            return sorted(orphans, key=lambda r: r.name.lower())
        orphans += found
        remaining = [r for r in remaining if r not in found]


def analyze(results: list[Resolution], *, include_libraries: bool = False, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    installed = [r for r in results if r.mod is not None]

    groups: dict[str, list[str]] = {}
    for r in installed:
        cat = r.categories[0] if r.categories else OTHER
        if cat == LIBRARY and not include_libraries:
            continue
        groups.setdefault(cat, []).append(r.name)
    order = {c: i for i, c in enumerate(OURS + (OTHER,))}
    by_category = sorted(
        ({"cat": c, "count": len(names), "mods": sorted(names, key=str.lower)} for c, names in groups.items()),
        key=lambda b: (-b["count"], order.get(b["cat"], 99)),
    )

    sources = Counter(r.source for r in installed)
    totals = {
        "mods": len(installed),
        "libraries": sum(r.is_library for r in installed),
        "size": sum(r.mod.size for r in installed),
        "up_to_date": sum(r.status == AL_DIA for r in installed),
        "updates": sum(r.status in (ACTUALIZABLE, DESCARGA_MANUAL) for r in installed),
        "sources": {"curseforge": sources.get(CF, 0), "modrinth": sources.get(MR, 0),
                    "none": sum(r.source not in (CF, MR) for r in installed)},
    }

    heaviest = [{"name": r.name, "size": r.mod.size}
                for r in sorted(installed, key=lambda r: -r.mod.size)[:TOP_HEAVIEST]]

    stale = []
    for r in installed:
        ts = _timestamp(r.project_updated)
        if ts is not None and now - ts > STALE_DAYS * 24 * 3600:
            stale.append({"name": r.name, "date": r.project_updated, "url": r.project_url})
    stale.sort(key=lambda s: s["date"])

    sides = Counter(r.side or "unknown" for r in installed)
    return {
        "by_category": by_category,
        "totals": totals,
        "heaviest": heaviest,
        "stale": stale,
        "orphans": [{"name": r.name, "size": r.mod.size} for r in _orphans(installed)],
        "sides": {k: sides.get(k, 0) for k in ("client", "server", "both", "unknown")},
    }
