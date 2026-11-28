"""Perfiles: varias carpetas de mods (o instancias de launchers), cada una con su versión de
Minecraft, cargador y ajustes propios.

Los campos de siempre de `Settings` (mods_dir, minecraft_version, loader, allow_beta,
backups_to_keep) son el reflejo del perfil activo: el resto de la app los sigue usando igual y
`save_settings` los copia a su perfil. Las copias de seguridad y Deshacer van con la carpeta de
cada perfil (`<carpeta>\\..\\mods_backup`), así que también son por perfil.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from . import i18n
from .i18n import t

PROFILE_FIELDS = ("mods_dir", "minecraft_version", "loader", "allow_beta", "backups_to_keep", "answers", "pins", "diag_seen")


def _norm(folder: str) -> str:
    return os.path.normcase(os.path.normpath(folder or ""))


def _new_id(name: str, existing: set[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", (name or "perfil").lower()).strip("-") or "perfil"
    pid, n = base, 2
    while pid in existing:
        pid, n = f"{base}-{n}", n + 1
    return pid


def get(s, pid: str) -> dict | None:
    return next((p for p in s.profiles if p.get("id") == pid), None)


def apply_active(s) -> None:
    """Copia los campos del perfil activo a los campos de siempre de Settings (los que falten,
    con su valor por defecto: un perfil nunca hereda nada de otro)."""
    p = get(s, s.active_profile) or (s.profiles[0] if s.profiles else None)
    if p is None:
        return
    from .settings import Settings  # aquí para no crear un import circular
    defaults = Settings()
    s.active_profile = p["id"]
    for f in PROFILE_FIELDS:
        setattr(s, f, p[f] if f in p else getattr(defaults, f))


def sync_active(s) -> None:
    """Lo contrario: guarda en el perfil activo los campos de siempre (antes de escribir a disco)."""
    p = get(s, s.active_profile)
    if p is not None:
        p.update({f: getattr(s, f) for f in PROFILE_FIELDS})


def ensure(s) -> None:
    """Migración: unos ajustes sin perfiles (versión anterior) pasan a un perfil "Principal"."""
    if s.profiles or not s.setup_done:
        return
    # El nombre, en el idioma de los ajustes (al cargar aún no se ha fijado el de la interfaz).
    previous = i18n.get_language()
    i18n.set_language(s.language)
    name = t("profile.default_name")
    i18n.set_language(previous)
    s.profiles = [{"id": "principal", "name": name, **{f: getattr(s, f) for f in PROFILE_FIELDS}}]
    s.active_profile = "principal"


def add(s, *, name: str, mods_dir: str, minecraft_version: str, loader: str) -> str:
    ensure(s)
    sync_active(s)
    pid = _new_id(name, {p["id"] for p in s.profiles})
    s.profiles.append({"id": pid, "name": (name or "").strip() or t("profile.default_name"), "mods_dir": mods_dir,
                       "minecraft_version": minecraft_version, "loader": loader, "allow_beta": False,
                       "backups_to_keep": s.backups_to_keep, "answers": {}})
    return pid


def switch(s, pid: str) -> None:
    if get(s, pid) is None:
        raise KeyError(pid)
    sync_active(s)
    s.active_profile = pid
    apply_active(s)


def rename(s, pid: str, name: str) -> None:
    p = get(s, pid)
    if p is None:
        raise KeyError(pid)
    p["name"] = (name or "").strip()[:60] or p["name"]


def remove(s, pid: str) -> None:
    """Quita un perfil de la lista (no toca su carpeta). Nunca el último."""
    if len(s.profiles) <= 1:
        raise ValueError("último perfil")
    sync_active(s)
    s.profiles = [p for p in s.profiles if p.get("id") != pid]
    if s.active_profile == pid:
        s.active_profile = s.profiles[0]["id"]
    apply_active(s)


def same_folder(s) -> list[list[str]]:
    """Grupos de perfiles que apuntan a la misma carpeta (nombres), para avisar."""
    groups: dict[str, list[str]] = {}
    for p in s.profiles:
        groups.setdefault(_norm(p.get("mods_dir", "")), []).append(p.get("name", "?"))
    return [names for names in groups.values() if len(names) > 1]


def listing(s) -> list[dict]:
    sync_active(s)
    return [{"id": p["id"], "name": p.get("name", "?"), "mods_dir": p.get("mods_dir", ""),
             "minecraft_version": p.get("minecraft_version"), "loader": p.get("loader"),
             "active": p["id"] == s.active_profile, "exists": Path(p.get("mods_dir") or "").is_dir()}
            for p in s.profiles]
