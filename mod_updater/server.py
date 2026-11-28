"""Preparar el servidor (hito 7 del plan v4).

- `plan_copy`: qué hay que llevar del perfil de cliente al de servidor. Van los mods de ambos lados
  y los de servidor; los de solo cliente se quedan fuera (y, si ya están en el servidor, sobran);
  los de lado desconocido se preguntan. También compara versiones ("el servidor tiene Create
  6.0.1 y tú 6.0.4") y dice qué sobra en el servidor.
- `copy_into`: copia los mismos archivos del cliente (así las versiones son exactamente iguales y
  no hace falta descargar nada), con copia de seguridad y `cambios.json` como cualquier cambio,
  para que Deshacer funcione en el perfil del servidor.
- `server_running`: el servidor está en marcha si un proceso java menciona su carpeta o si el
  mundo tiene `session.lock` bloqueado (Minecraft lo bloquea mientras lo usa).
"""

from __future__ import annotations

import os
import re
import shutil
import tomllib
import zipfile
from pathlib import Path
from types import SimpleNamespace

from .downloader import Changelog, Outcome, friendly_error, make_backup_dir
from .i18n import t
from .procs import list_java_processes, minecraft_running
from .scanner import ModFile, _lower_bound


def _key(m: ModFile) -> str:
    return m.mod_id or m.file_name


def _ids(m: ModFile) -> set[str]:
    """Todos los modIds de un jar (algunos traen varios mods dentro)."""
    return ({m.mod_id, *m.extra_mod_ids} - {None, ""}) or {m.file_name}


def _version_key(v: str | None) -> tuple:
    return tuple(int(n) for n in re.findall(r"\d+", v or "")[:4])


def loader_min(jar_path: Path) -> str | None:
    """Versión mínima de NeoForge (o Forge) que pide un jar en su mods.toml, si la pide."""
    try:
        with zipfile.ZipFile(jar_path) as z:
            names = set(z.namelist())
            name = next((n for n in ("META-INF/neoforge.mods.toml", "META-INF/mods.toml") if n in names), None)
            if name is None:
                return None
            data = tomllib.loads(z.read(name).decode("utf-8", errors="replace"))
    except (OSError, zipfile.BadZipFile, tomllib.TOMLDecodeError):
        return None
    for group in (data.get("dependencies") or {}).values() if isinstance(data.get("dependencies"), dict) else []:
        for d in group if isinstance(group, list) else []:
            if isinstance(d, dict) and d.get("modId") in ("neoforge", "forge"):
                return _lower_bound(str(d.get("versionRange") or ""))
    return None


def server_loader_version(game_dir: Path) -> str | None:
    """Versión de NeoForge instalada en el servidor (carpeta libraries que deja su instalador)."""
    for base in (Path(game_dir) / "libraries" / "net" / "neoforged" / "neoforge",):
        try:
            versions = [p.name for p in base.iterdir() if p.is_dir()]
        except OSError:
            continue
        if versions:
            return max(versions, key=_version_key)
    return None


def plan_copy(results: list, server_mods: list[ModFile], server_loader: str | None = None) -> dict:
    active_server = [m for m in server_mods if not m.disabled]
    by_sha = {m.sha1: m for m in active_server}
    by_key: dict[str, list[ModFile]] = {}
    for m in active_server:
        for i in _ids(m):
            by_key.setdefault(i, []).append(m)
    used: set[str] = set()
    copy, update, client_only, on_server, unknown, same = [], [], [], [], [], 0
    for r in results:
        if r.mod is None or r.unreadable or r.mod.disabled:
            continue
        exact = by_sha.get(r.mod.sha1)
        # Todos los jars del servidor con alguno de sus modIds: al actualizar se apartan todos.
        matches = list({id(m): m for i in _ids(r.mod) for m in by_key.get(i, [])}.values()) or ([exact] if exact else [])
        s = exact or (matches[0] if matches else None)
        item = {"name": r.name, "file": r.mod.file_name, "src": str(r.mod.path),
                "server_file": s.file_name if s else None,
                "server_files": sorted({m.file_name for m in matches} | ({s.file_name} if s else set())),
                "same": bool(s and s.sha1 == r.mod.sha1),
                "client_version": r.current_version or r.mod.version, "server_version": s.version if s else None,
                "preselect": bool(matches)}  # lado desconocido pero el servidor ya lo usa: se propone marcado
        used.update(item["server_files"])
        if r.side == "client":
            client_only.append(item)
            if item["server_files"]:
                on_server.append(item)  # el servidor ya tiene un mod solo de cliente: se puede quitar
            continue
        if item["same"] and len(item["server_files"]) == 1:
            same += 1
        elif r.side is None:
            unknown.append(item)
        elif s is not None:
            update.append(item)
        else:
            copy.append(item)
    extra = sorted((m.file_name for m in active_server if m.file_name not in used), key=str.lower)
    too_old = []
    if server_loader:
        for it in copy + update:
            need = loader_min(Path(it["src"]))
            if need and _version_key(need) > _version_key(server_loader):
                too_old.append({"name": it["name"], "needs": need, "server": server_loader})
    order = lambda items: sorted(items, key=lambda i: i["name"].lower())  # noqa: E731
    return {"copy": order(copy), "update": order(update), "client_only": order(client_only),
            "client_only_on_server": order(on_server), "unknown": order(unknown), "same": same, "extra": extra,
            "loader_too_old": order(too_old), "server_loader": server_loader}


def copy_into(plan: dict, chosen_unknown: list[str], mods_dir: Path, remove: list[str] = ()) -> tuple[Path, list[Outcome]]:
    """Copia al servidor lo de `copy` y `update` (y los de lado desconocido elegidos). Al actualizar
    un mod se apartan todas sus versiones del servidor: nunca quedan dos. `remove`: archivos del
    servidor que se quitan (lo que sobra o los mods solo de cliente), solo si se eligen. Todo lo que
    se aparta va a la copia de seguridad del servidor; Deshacer lo devuelve."""
    mods_dir = Path(mods_dir)
    chosen = set(chosen_unknown)
    items = plan["copy"] + plan["update"] + [u for u in plan["unknown"] if u["file"] in chosen and not u["same"]]
    removals = sorted(n for n in set(remove) if (mods_dir / n).is_file())
    if not items and not removals:
        return None, []  # nada que hacer: sin copia de seguridad vacía
    backup_dir = make_backup_dir(mods_dir)
    log = Changelog(backup_dir, mods_dir)
    outcomes: list[Outcome] = []
    source = t("sv.source")

    def entry(action, name, old=None, new=None, old_v=None, new_v=None) -> dict:
        e = {"state": "pending", "ok": False, "action": action, "name": name, "source": source, "project_id": None,
             "old_file": old, "new_file": new, "backup_file": old, "old_version": old_v, "new_version": new_v,
             "required_by": [], "message": ""}
        log.data["changes"].append(e)
        log.save()
        return e

    def finish(e, ok, message, backup=None) -> None:
        e.update({"state": "ok" if ok else "failed", "ok": ok, "message": message,
                  "backup_file": backup.name if ok and backup else None})
        log.save()

    def set_aside(name: str, label: str) -> bool:
        """Mueve un archivo del servidor a la copia (como "quitado")."""
        path = mods_dir / name
        e = entry("remove", label, old=name)
        try:
            os.replace(path, backup_dir / name)
        except OSError as exc:
            finish(e, False, t("dl.move_old_failed", error=friendly_error(exc)))
            outcomes.append(Outcome(SimpleNamespace(name=label), False, e["message"]))
            return False
        finish(e, True, t("dl.removed"), backup_dir / name)
        return True

    for name in removals:
        set_aside(name, name)
    for it in items:
        olds = [f for f in it["server_files"] if (mods_dir / f).is_file()]
        main = it["server_file"] if it["server_file"] in olds else (olds[0] if olds else None)
        new = mods_dir / it["file"]
        if new.exists() and new.name not in olds:
            outcomes.append(Outcome(SimpleNamespace(name=it["name"]), False, t("dl.exists", name=it["file"])))
            continue
        # Primero se copia a un .part fuera de la carpeta del servidor: si falla (disco lleno, antivirus),
        # el servidor no se ha tocado y no queda ningún jar a medias.
        part = backup_dir / f"{it['file']}.part"
        try:
            shutil.copy2(it["src"], part)
        except OSError as exc:
            part.unlink(missing_ok=True)
            outcomes.append(Outcome(SimpleNamespace(name=it["name"]), False, t("dl.failed", error=friendly_error(exc))))
            continue
        if not all(set_aside(f, it["name"]) for f in olds if f != main):  # otras versiones del mismo mod
            part.unlink(missing_ok=True)
            continue
        e = entry("update" if main else "install", it["name"], old=main, new=it["file"],
                  old_v=it["server_version"], new_v=it["client_version"])
        backup = backup_dir / main if main else None
        try:
            if main:
                os.replace(mods_dir / main, backup)
            os.replace(part, new)
        except OSError as exc:
            try:
                if backup is not None and backup.exists() and not (mods_dir / main).exists():
                    os.replace(backup, mods_dir / main)  # se deshace: el del servidor vuelve a su sitio
            except OSError:
                pass  # queda en la copia de seguridad y en cambios.json como pendiente: Deshacer lo devuelve
            part.unlink(missing_ok=True)
            finish(e, False, t("dl.failed", error=friendly_error(exc)))
            outcomes.append(Outcome(SimpleNamespace(name=it["name"]), False, e["message"]))
            continue
        finish(e, True, t("sv.copied"), backup)
        outcomes.append(Outcome(SimpleNamespace(name=it["name"]), True, e["message"], new_path=new, backup_path=backup))
    log.close()
    return backup_dir, outcomes


def server_running(game_dir: Path, lister=list_java_processes) -> bool:
    if minecraft_running(Path(game_dir), lister):
        return True
    if os.name != "nt":
        return False
    import msvcrt

    try:
        worlds = [p for p in Path(game_dir).iterdir() if p.is_dir()]
    except OSError:
        return False
    for w in worlds:
        lock = w / "session.lock"
        if not lock.is_file():
            continue
        try:
            with open(lock, "r+b") as f:
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            return True  # bloqueado: el servidor (o un cliente) tiene ese mundo abierto
    return False
