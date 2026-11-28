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
import shutil
from pathlib import Path
from types import SimpleNamespace

from .downloader import Changelog, Outcome, friendly_error, make_backup_dir
from .i18n import t
from .procs import list_java_processes, minecraft_running
from .scanner import ModFile


def _key(m: ModFile) -> str:
    return m.mod_id or m.file_name


def plan_copy(results: list, server_mods: list[ModFile]) -> dict:
    by_sha = {m.sha1: m for m in server_mods}
    by_id = {_key(m): m for m in server_mods}
    used: set[str] = set()
    copy, update, client_only, unknown, same = [], [], [], [], 0
    for r in results:
        if r.mod is None or r.unreadable or r.mod.disabled:
            continue
        s = by_sha.get(r.mod.sha1) or by_id.get(_key(r.mod))
        item = {"name": r.name, "file": r.mod.file_name, "src": str(r.mod.path),
                "server_file": s.file_name if s else None, "same": bool(s and s.sha1 == r.mod.sha1),
                "client_version": r.current_version or r.mod.version, "server_version": s.version if s else None}
        if r.side == "client":
            client_only.append(item)  # si está en el servidor, sobra (no se marca como usado)
            continue
        if s is not None:
            used.add(s.file_name)
        if r.side is None:
            unknown.append(item)
        elif item["same"]:
            same += 1
        elif s is not None:
            update.append(item)
        else:
            copy.append(item)
    extra = sorted((m.file_name for m in server_mods if m.file_name not in used and not m.disabled), key=str.lower)
    order = lambda items: sorted(items, key=lambda i: i["name"].lower())  # noqa: E731
    return {"copy": order(copy), "update": order(update), "client_only": order(client_only),
            "unknown": order(unknown), "same": same, "extra": extra}


def copy_into(plan: dict, chosen_unknown: list[str], mods_dir: Path) -> tuple[Path, list[Outcome]]:
    """Copia al servidor lo de `copy` y `update` (y los de lado desconocido elegidos). Lo que se
    sustituye va a la copia de seguridad del servidor; Deshacer lo devuelve."""
    mods_dir = Path(mods_dir)
    items = plan["copy"] + plan["update"] + [u for u in plan["unknown"] if u["file"] in set(chosen_unknown) and not u["same"]]
    backup_dir = make_backup_dir(mods_dir)
    log = Changelog(backup_dir, mods_dir)
    outcomes = []
    for it in items:
        old = mods_dir / it["server_file"] if it["server_file"] else None
        new = mods_dir / it["file"]
        entry = {"state": "pending", "ok": False, "action": "update" if old else "install", "name": it["name"],
                 "source": None, "project_id": None, "old_file": it["server_file"], "new_file": it["file"],
                 "backup_file": it["server_file"], "old_version": it["server_version"],
                 "new_version": it["client_version"], "required_by": [], "message": ""}
        ok, message, backup_path = False, "", None
        if new.exists() and (old is None or new.resolve() != old.resolve()):
            message = t("dl.exists", name=it["file"])
        else:
            log.data["changes"].append(entry)
            log.save()
            try:
                if old is not None and old.exists():
                    backup_path = backup_dir / old.name
                    os.replace(old, backup_path)
                shutil.copy2(it["src"], new)
                ok, message = True, t("sv.copied")
            except OSError as exc:
                if backup_path is not None and backup_path.exists() and not old.exists():
                    os.replace(backup_path, old)  # se deshace: el del servidor vuelve a su sitio
                message = t("dl.failed", error=friendly_error(exc))
        entry.update({"state": "ok" if ok else "failed", "ok": ok, "message": message,
                      "backup_file": backup_path.name if ok and backup_path else None})
        if entry not in log.data["changes"]:
            log.data["changes"].append(entry)
        log.save()
        outcomes.append(Outcome(SimpleNamespace(name=it["name"]), ok, message, new_path=new if ok else None,
                                backup_path=backup_path if ok else None))
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
