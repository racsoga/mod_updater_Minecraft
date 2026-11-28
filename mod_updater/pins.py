"""Mods fijados ("No actualizar este"), por perfil.

Se guardan en los ajustes del perfil (`Settings.pins`) como
`{"<fuente>:<id de proyecto>": {"name", "version", "reason", "ids"}}`, donde `ids` son todos los
IDs con los que se conocía el mod al fijarlo (CurseForge y Modrinth): así la fijación sigue
valiendo aunque un día solo responda una de las dos webs. Un mod fijado no entra en
"Actualizar todo" ni lo actualiza la CLI, y si otro mod necesita una versión más nueva de él,
ese otro mod se bloquea con un aviso en vez de actualizar el fijado.
"""

from __future__ import annotations

import os
from pathlib import Path

from .resolver import CF, MR, Resolution


def pin_key(res: Resolution) -> str | None:
    """Clave de la fijación: la fuente principal del mod y su proyecto."""
    if res.source in (CF, MR) and res.project_id:
        return f"{res.source}:{res.project_id}"
    return None


def _keys(res: Resolution) -> set[str]:
    return {f"{src}:{pid}" for src, pid in res.known_ids} | ({pin_key(res)} - {None})


def _entry_keys(key: str, entry: dict) -> set[str]:
    return {key} | {str(k) for k in (entry.get("ids") or [])}


def pin_entry(res: Resolution, *, version: str | None, reason: str) -> dict:
    return {"name": res.name, "version": version or "", "reason": reason, "ids": sorted(_keys(res))}


def find_pins(res: Resolution, pins: dict) -> list[str]:
    """Todas las claves de `pins` que corresponden a `res` (puede haber más de una)."""
    mine = _keys(res)
    return [k for k, v in pins.items() if mine & _entry_keys(k, v if isinstance(v, dict) else {})]


def apply_pins(results: list[Resolution], pins: dict) -> None:
    """Marca como fijados los mods de `results` que estén en `pins` (por cualquiera de sus IDs)."""
    for r in results:
        if r.mod is None:
            continue
        hits = find_pins(r, pins)
        if hits:
            r.pinned = True
            r.pin_reason = str(pins[hits[0]].get("reason") or "")


def pins_for_folder(mods_dir: Path, settings_file: Path | None = None) -> dict:
    """Fijaciones del perfil de la app que usa esa carpeta (para la CLI). {} si no hay."""
    from .settings import load_settings  # aquí para no crear un import circular

    s = load_settings(settings_file)
    norm = lambda p: os.path.normcase(os.path.normpath(str(p)))  # noqa: E731
    for p in s.profiles:
        if p.get("mods_dir") and norm(p["mods_dir"]) == norm(mods_dir):
            return dict(p.get("pins") or {})
    return {}
