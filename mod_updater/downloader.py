"""Descarga de versiones nuevas con verificación de hash y backup del jar viejo.

Garantías:
- Nunca se borra un jar: el viejo se mueve a `mods_backup/<fecha>/`.
- El nuevo se descarga primero a un `.part` (fuera de la carpeta de mods) y
  solo se coloca si su hash coincide.
- Si algo falla, el jar viejo sigue (o vuelve) a su sitio.
- `cambios.json` se escribe desde el principio y tras cada mod (Deshacer funciona
  aunque el proceso se interrumpa); `cambios.txt` lo describe para revertir a mano.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable
from urllib.parse import urljoin, urlparse

import requests

from .i18n import t
from .net import ApiError, request_with_retry
from .resolver import ACTUALIZABLE, DISABLE, ENABLE, REMOVE, Resolution
from .scanner import DISABLED_SUFFIX

CHUNK = 1 << 16
CF_HOSTS = ("forgecdn.net", "curseforge.com")
MAX_REDIRECTS = 5

SessionFor = Callable[[str], requests.Session]


@dataclass
class Outcome:
    resolution: Resolution
    ok: bool
    message: str
    new_path: Path | None = None
    backup_path: Path | None = None


def backup_root(mods_dir: Path) -> Path:
    return mods_dir.parent / "mods_backup"


def make_backup_dir(mods_dir: Path, now: datetime | None = None) -> Path:
    """Crea `mods_backup/AAAA-MM-DD_HHMM` (con sufijo si ya existe)."""
    stamp = (now or datetime.now()).strftime("%Y-%m-%d_%H%M")
    root = backup_root(mods_dir)
    path = root / stamp
    n = 2
    while path.exists():
        path = root / f"{stamp}_{n}"
        n += 1
    path.mkdir(parents=True)
    return path


def _is_curseforge_url(url: str) -> bool:
    host = urlparse(url).hostname or ""
    return any(host == h or host.endswith("." + h) for h in CF_HOSTS)


def _expected_hash(res: Resolution) -> tuple[str, str] | None:
    if res.new_sha512:
        return "sha512", res.new_sha512.lower()
    if res.new_sha1:
        return "sha1", res.new_sha1.lower()
    return None


def _get_following_redirects(url: str, session_for: SessionFor) -> requests.Response:
    """GET siguiendo redirecciones a mano, para elegir la sesión (y por tanto
    las cabeceras) en cada salto: la key de CurseForge solo va a sus dominios."""
    for _ in range(MAX_REDIRECTS + 1):
        if urlparse(url).scheme != "https":
            raise DownloadError(t("dl.insecure_url", url=url))
        resp = request_with_retry(session_for(url), "GET", url, stream=True, timeout=60, allow_redirects=False)
        if resp.is_redirect:
            url = urljoin(url, resp.headers["Location"])
            resp.close()
            continue
        return resp
    raise DownloadError(t("dl.too_many_redirects"))


def download_verified(res: Resolution, dest: Path, session_for: SessionFor) -> None:
    """Descarga `res.download_url` a `dest` y verifica el hash. Lanza si falla
    (y en ese caso no deja `dest`)."""
    expected = _expected_hash(res)
    if expected is None:
        raise DownloadError(t("dl.no_hash"))
    algo, want = expected
    h = hashlib.new(algo)
    try:
        resp = _get_following_redirects(res.download_url, session_for)
        if not resp.ok:
            raise DownloadError(t("dl.http_error", status=resp.status_code))
        with resp, dest.open("wb") as f:
            for chunk in resp.iter_content(CHUNK):
                f.write(chunk)
                h.update(chunk)
        if h.hexdigest() != want:
            raise DownloadError(t("dl.hash_mismatch", algo=algo))
    except BaseException:
        dest.unlink(missing_ok=True)
        raise


class DownloadError(ApiError):
    """Error de descarga con mensaje ya traducido para el usuario."""


def friendly_error(exc: BaseException) -> str:
    """Mensaje claro, traducido y sin rutas técnicas para un error de archivo o de red."""
    if isinstance(exc, DownloadError):
        return str(exc)
    if isinstance(exc, (requests.RequestException, ApiError)):
        return t("err.network")
    if isinstance(exc, OSError):
        if exc.errno == 28 or getattr(exc, "winerror", None) in (39, 112):
            return t("err.disk_full")
        if isinstance(exc, PermissionError) or getattr(exc, "winerror", None) in (5, 32, 33):
            return t("err.in_use")
        return t("err.file", detail=exc.strerror or type(exc).__name__)
    return t("err.unexpected", error=type(exc).__name__)


def apply_one(
    res: Resolution, mods_dir: Path, backup_dir: Path, session_for: SessionFor, on_state=None, before_change=None
) -> Outcome:
    """Actualiza (si hay jar viejo) o instala (si `res.mod` es None) un mod.

    `on_state`, si se pasa, recibe "downloading" y "verified" según avanza.
    `before_change(info)`, si se pasa, se llama justo antes de tocar la carpeta de mods
    (para dejarlo anotado en `cambios.json` por si el proceso se interrumpe).
    """
    state = on_state or (lambda name: None)
    if res.kind == REMOVE:
        return _remove_one(res, backup_dir, before_change)
    if res.kind in (ENABLE, DISABLE):
        return toggle_one(res, before_change)
    old = res.mod.path if res.mod is not None else None
    new_name = res.new_file_name or ""
    if not res.download_url or not new_name:
        return Outcome(res, False, t("dl.no_url"))
    if Path(new_name).name != new_name or not new_name.lower().endswith(".jar"):
        return Outcome(res, False, t("dl.bad_name", name=new_name))
    if old is not None and not old.exists():
        return Outcome(res, False, t("dl.old_missing"))

    # Un mod desactivado sigue desactivado al actualizarlo; uno de una lista con "activo": false se instala así.
    if (res.mod is not None and res.mod.disabled) or (res.mod is None and res.install_disabled):
        new_name += DISABLED_SUFFIX
    final = mods_dir / new_name
    if final.exists() and (old is None or final.resolve() != old.resolve()):
        return Outcome(res, False, t("dl.exists", name=new_name))

    part = backup_dir / f"{new_name}.part"
    state("downloading")
    try:
        download_verified(res, part, session_for)
    except (ApiError, OSError, requests.RequestException) as exc:
        return Outcome(res, False, t("dl.failed", error=friendly_error(exc)))
    state("verified")

    backup = backup_dir / old.name if old is not None else None
    if before_change:
        before_change({"new_file": new_name, "backup_file": backup.name if backup else None})

    if old is None:  # instalación nueva: no hay nada que mover al backup
        try:
            os.replace(part, final)
        except OSError as exc:
            part.unlink(missing_ok=True)
            return Outcome(res, False, t("dl.place_failed", error=friendly_error(exc)))
        return Outcome(res, True, t("dl.installed"), new_path=final)

    try:
        os.replace(old, backup)  # 1. viejo -> backup
    except OSError as exc:
        part.unlink(missing_ok=True)
        return Outcome(res, False, t("dl.move_old_failed", error=friendly_error(exc)))
    try:
        os.replace(part, final)  # 2. nuevo -> mods
    except OSError as exc:
        os.replace(backup, old)  # deshacer: el viejo vuelve a su sitio
        part.unlink(missing_ok=True)
        return Outcome(res, False, t("dl.restored", error=friendly_error(exc)))
    return Outcome(res, True, t("dl.updated"), new_path=final, backup_path=backup)


def _remove_one(res: Resolution, backup_dir: Path, before_change=None) -> Outcome:
    """Quita un jar moviéndolo a la copia de seguridad (nunca se borra; Deshacer lo devuelve)."""
    old = res.mod.path if res.mod is not None else None
    if old is None or not old.exists():
        return Outcome(res, False, t("dl.old_missing"))
    backup = backup_dir / old.name
    if before_change:
        before_change({"new_file": None, "backup_file": backup.name})
    try:
        os.replace(old, backup)
    except OSError as exc:
        return Outcome(res, False, t("dl.move_old_failed", error=friendly_error(exc)))
    return Outcome(res, True, t("dl.removed"), backup_path=backup)


def toggle_one(res: Resolution, before_change=None) -> Outcome:
    """Activa o desactiva renombrando (`x.jar` <-> `x.jar.disabled`). Nunca sobrescribe."""
    old = res.mod.path if res.mod is not None else None
    if old is None or not old.exists():
        return Outcome(res, False, t("dl.old_missing"))
    name = res.mod.enabled_name if res.kind == ENABLE else res.mod.enabled_name + DISABLED_SUFFIX
    target = old.with_name(name)  # en su propia carpeta, nunca en la de otro perfil
    if target.exists():
        return Outcome(res, False, t("dl.exists", name=name))
    if before_change:
        before_change({"new_file": name, "backup_file": None})
    try:
        os.replace(old, target)
    except OSError as exc:
        return Outcome(res, False, t("dl.rename_failed", error=friendly_error(exc)))
    return Outcome(res, True, t("dl.enabled" if res.kind == ENABLE else "dl.disabled"), new_path=target)


def updatable(results: list[Resolution]) -> tuple[list[Resolution], list[Resolution]]:
    """Separa los actualizables aplicables de los que hay que saltar
    (proyectos duplicados en la carpeta: actualizarlos chocaría)."""
    cands = [r for r in results if r.status == ACTUALIZABLE]
    count = Counter((r.source, r.project_id) for r in cands)
    active = Counter((r.source, r.project_id) for r in cands if not (r.mod and r.mod.disabled))

    def alone(r: Resolution) -> bool:
        key = (r.source, r.project_id)
        if r.mod is not None and r.mod.disabled:  # copia desactivada: solo si no hay otra copia
            return count[key] == 1
        return active[key] == 1  # la activa se actualiza aunque haya copias viejas desactivadas

    ok = [r for r in cands if alone(r) and not r.duplicate]
    skipped = [r for r in cands if r not in ok]
    return ok, skipped


class Changelog:
    """`cambios.json` escrito desde el principio y actualizado tras cada mod.

    Cada cambio se anota como "pending" justo antes de tocar la carpeta de mods y
    pasa a "ok" o "failed" al terminar. Si el proceso se interrumpe (se cierra la
    ventana, se va la luz), Deshacer sabe qué estaba a medias.
    """

    def __init__(self, backup_dir: Path, mods_dir: Path):
        self.backup_dir, self.mods_dir = backup_dir, mods_dir
        self.data = {
            "version": 2,
            "date": datetime.now().isoformat(timespec="seconds"),
            "mods_dir": str(mods_dir),
            "complete": False,
            "changes": [],
        }
        self.save()

    def save(self) -> None:
        _write_json(self.backup_dir / "cambios.json", self.data)

    def _entry(self, r: Resolution) -> dict:
        return {
            "state": "pending", "ok": False,
            "action": "install" if r.mod is None else (r.kind if r.kind in (REMOVE, ENABLE, DISABLE) else "update"),
            "name": r.name, "source": r.source, "project_id": r.project_id,
            "old_file": r.mod.file_name if r.mod else None,
            "new_file": r.new_file_name, "backup_file": None,
            "old_version": r.current_version, "new_version": r.new_version,
            "required_by": list(r.required_by), "message": "",
        }

    def begin(self, r: Resolution, info: dict) -> dict:
        entry = self._entry(r) | info
        self.data["changes"].append(entry)
        self.save()
        return entry

    def finish(self, outcome: Outcome, entry: dict | None) -> None:
        if entry is None:  # falló antes de tocar la carpeta: solo se anota
            entry = self._entry(outcome.resolution)
            self.data["changes"].append(entry)
        entry.update({
            "state": "ok" if outcome.ok else "failed",
            "ok": outcome.ok,
            "message": outcome.message,
            "new_file": outcome.new_path.name if outcome.new_path else None,
            "backup_file": outcome.backup_path.name if outcome.backup_path else None,
        })
        self.save()

    def close(self) -> Path:
        self.data["complete"] = True
        self.save()
        return write_changelog_txt(self.backup_dir, self.mods_dir, self.data["changes"])


def _write_json(path: Path, data: dict) -> None:
    """Escritura atómica: o el archivo viejo o el nuevo, nunca uno a medias."""
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def write_changelog_txt(backup_dir: Path, mods_dir: Path, entries: list[dict]) -> Path:
    """`cambios.txt`: el mismo registro, para leerlo a mano."""
    lines = [
        t("log.title", date=f"{datetime.now():%Y-%m-%d %H:%M}"),
        t("log.folder", path=mods_dir),
        "",
        *t("log.howto").splitlines(),
        "",
    ]
    for e in entries:
        if not e["ok"]:
            lines.append(t("log.failed", name=e["name"], message=e["message"]))
        elif e["action"] in (ENABLE, DISABLE):
            lines.append(t(f"log.{e['action']}d", name=e["name"], file=e["new_file"]))
        elif e["action"] == "remove":
            lines.append(t("log.removed", name=e["name"], file=e["old_file"], version=e["old_version"]))
        elif e["action"] == "install":
            why = t("log.required_by", names=", ".join(e["required_by"])) if e["required_by"] else ""
            lines.append(t("log.installed", name=e["name"], file=e["new_file"], version=e["new_version"], source=e["source"], why=why))
        else:
            lines.append(t("log.updated", name=e["name"], old=e["old_file"], new=e["new_file"],
                           old_version=e["old_version"], new_version=e["new_version"], source=e["source"]))
    path = backup_dir / "cambios.txt"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


_BACKUP_NAME = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{4}(_\d+)?$")


def list_backups(mods_dir: Path) -> list[Path]:
    """Carpetas de backup creadas por este programa, de la más vieja a la más nueva."""
    root = backup_root(mods_dir)
    if not root.is_dir():
        return []
    found = [
        p for p in root.iterdir()
        if p.is_dir() and _BACKUP_NAME.match(p.name)
        and ((p / "cambios.json").exists() or (p / "cambios.txt").exists())
    ]
    def order(p: Path) -> tuple[str, int]:
        stamp, _, n = p.name.partition("_")[2].partition("_")
        return (p.name[:10] + stamp, int(n) if n else 1)

    return sorted(found, key=order)


def prune_backups(mods_dir: Path, keep: int) -> list[Path]:
    """Borra los backups más viejos y deja los `keep` más recientes. Devuelve los borrados.

    Solo toca carpetas con el formato de fecha y un `cambios.json`/`cambios.txt`
    dentro, es decir, creadas por este programa. Nunca borra una copia que haga falta
    para recuperar algo (ver `_must_keep`).
    """
    keep = max(1, keep)
    backups = list_backups(mods_dir)
    logs = {b: read_changelog(b) for b in backups}
    present = _mods_present(logs.values(), mods_dir)
    old = backups[:-keep] if len(backups) > keep else []
    to_delete = [b for b in old if not _must_keep(b, logs[b], mods_dir, present)]
    for b in to_delete:
        shutil.rmtree(b)
    return to_delete


def _mod_key(change: dict) -> tuple:
    if change.get("project_id"):
        return (change.get("source"), str(change["project_id"]))
    return ("file", change.get("old_file") or change.get("new_file"))


def _mods_present(logs, mods_dir: Path) -> set[tuple]:
    """Mods (por proyecto) de los que hay alguna versión en la carpeta de mods, según
    cualquier copia: si un mod se actualizó dos veces, su versión actual sale en la última."""
    present: set[tuple] = set()
    for data in logs:
        for change in (data or {}).get("changes", []):
            if any((mods_dir / n).exists() for n in (change.get("old_file"), change.get("new_file")) if n):
                present.add(_mod_key(change))
    return present


def _must_keep(backup_dir: Path, data: dict | None, mods_dir: Path, present: set[tuple]) -> bool:
    """¿Hay que conservar esta copia aunque sobre?

    - Si es de una actualización interrumpida que no se ha restaurado.
    - Si guarda el jar viejo de un mod del que no queda ninguna versión en la carpeta de
      mods: esa copia es el único sitio donde queda ese mod.
    """
    if data is None:
        return False
    if not data.get("complete", True) and not data.get("undone"):
        return True
    for change in data.get("changes", []):
        backup_file = change.get("backup_file")
        if backup_file and (backup_dir / backup_file).is_file() and _mod_key(change) not in present:
            return True
    return False


def interrupted_backup(mods_dir: Path) -> Path | None:
    """La copia de una actualización que se interrumpió (sin terminar ni restaurar), si hay."""
    for backup in reversed(list_backups(mods_dir)):
        info = backup_info(backup)
        if not info["complete"] and info["undoable"]:
            return backup
    return None


def apply_updates(
    results: list[Resolution],
    mods_dir: Path,
    *,
    modrinth_session: requests.Session,
    curseforge_session: requests.Session | None,
    progress=None,
    on_state=None,
) -> tuple[Path, list[Outcome]]:
    """Aplica las actualizaciones. Devuelve (carpeta de backup, resultados).

    `progress(res)` se llama antes de cada mod; `on_state(res, estado)` con
    "downloading" / "verified" y, al terminar cada uno, con su `Outcome`.
    """
    backup_dir = make_backup_dir(mods_dir)

    def session_for(url: str) -> requests.Session:
        # El CDN de CurseForge acepta la key; ningún otro dominio debe recibirla.
        if curseforge_session is not None and _is_curseforge_url(url):
            return curseforge_session
        return modrinth_session

    log = Changelog(backup_dir, mods_dir)
    outcomes: list[Outcome] = []
    for res in results:
        if progress:
            progress(res)
        notify = (lambda name, r=res: on_state(r, name)) if on_state else None
        pending: dict = {}
        outcome = apply_one(res, mods_dir, backup_dir, session_for, notify,
                            before_change=lambda info, r=res: pending.setdefault("e", log.begin(r, info)))
        log.finish(outcome, pending.get("e"))
        outcomes.append(outcome)
        if on_state:
            on_state(res, outcome)
    log.close()
    return backup_dir, outcomes


# --------------------------------------------------------------------------- deshacer

UNDO_DIR = "undo"  # dentro del backup: los jars nuevos retirados al deshacer (no se borran)


@dataclass
class UndoResult:
    restored: int = 0     # jars viejos devueltos a la carpeta de mods
    removed: int = 0      # jars nuevos retirados (movidos a <backup>/undo)
    errors: list[str] = field(default_factory=list)


def read_changelog(backup_dir: Path) -> dict | None:
    try:
        return json.loads((backup_dir / "cambios.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def backup_info(backup_dir: Path) -> dict:
    """Resumen de un backup para la interfaz: fecha, cambios aplicados y si se puede deshacer."""
    data = read_changelog(backup_dir) or {}
    done = _undoable_changes(data)
    return {
        "path": str(backup_dir),
        "date": data.get("date"),
        "changes": len(done),
        "complete": data.get("complete", True),  # False: la actualización se interrumpió
        "undone": bool(data.get("undone")),
        "undoable": bool(done) and not data.get("undone"),
    }


def _undoable_changes(data: dict) -> list[dict]:
    """Cambios hechos (ok) o que se quedaron a medias (pending) al interrumpirse."""
    return [c for c in data.get("changes", []) if c.get("ok") or c.get("state") == "pending"]


def last_undoable(mods_dir: Path) -> Path | None:
    """La actualización más reciente que se puede deshacer (no solo la última copia:
    un intento fallido posterior no debe impedir deshacer la anterior)."""
    for backup in reversed(list_backups(mods_dir)):
        if backup_info(backup)["undoable"]:
            return backup
    return None


def undo_backup(backup_dir: Path) -> UndoResult:
    """Deshace una actualización usando su `cambios.json`.

    - Los jars nuevos se mueven a `<backup>/undo/` (no se borran).
    - Los jars viejos vuelven a la carpeta de mods.
    - Si algo no cuadra (un archivo ya no está o hay otro con el mismo nombre),
      se salta ese mod y se informa; el resto se deshace igualmente.
    - Marca el backup como deshecho para que no se pueda deshacer dos veces.
    """
    data = read_changelog(backup_dir)
    if data is None:
        return UndoResult(errors=[t("undo.no_log")])
    if data.get("undone"):
        return UndoResult(errors=[t("undo.already")])
    mods_dir = Path(data.get("mods_dir", ""))
    if not mods_dir.is_dir():
        return UndoResult(errors=[t("scan.no_folder", path=mods_dir)])

    result = UndoResult()
    undo_dir = backup_dir / UNDO_DIR
    for change in reversed(_undoable_changes(data)):
        name = change.get("name", "?")
        new_file, old_file, backup_file = change.get("new_file"), change.get("old_file"), change.get("backup_file")
        if change.get("state") == "pending" and change.get("action") in ("update", "remove") \
                and not (backup_file and (backup_dir / backup_file).exists()):
            # Se interrumpió antes de apartar el jar viejo: sigue en su sitio y no hay nada
            # que deshacer. (Si el nuevo se llama igual, lo que hay en mods ES el viejo.)
            continue
        try:
            if change.get("action") in (ENABLE, DISABLE):  # solo se renombró: se vuelve a renombrar
                source, target = mods_dir / (new_file or ""), mods_dir / (old_file or "")
                if not new_file or not source.exists():
                    result.errors.append(t("undo.old_missing", name=name))
                elif target.exists():
                    result.errors.append(t("undo.conflict", name=name, file=old_file))
                else:
                    os.replace(source, target)
                    result.restored += 1
                continue
            if new_file and (mods_dir / new_file).exists():
                undo_dir.mkdir(exist_ok=True)
                os.replace(mods_dir / new_file, undo_dir / new_file)
                result.removed += 1
            if change.get("action") in ("update", "remove") and backup_file and old_file:
                source, target = backup_dir / backup_file, mods_dir / old_file
                if not source.exists():
                    result.errors.append(t("undo.old_missing", name=name))
                elif target.exists():
                    result.errors.append(t("undo.conflict", name=name, file=old_file))
                else:
                    os.replace(source, target)
                    result.restored += 1
        except OSError as exc:
            result.errors.append(t("undo.failed", name=name, error=friendly_error(exc)))

    data["undone"] = datetime.now().isoformat(timespec="seconds")
    _write_json(backup_dir / "cambios.json", data)
    with (backup_dir / "cambios.txt").open("a", encoding="utf-8") as f:
        f.write("\n" + t("log.undone", date=f"{datetime.now():%Y-%m-%d %H:%M}") + "\n")
    return result


def clear_backups(mods_dir: Path) -> int:
    """Borra todos los backups creados por este programa. Devuelve cuántos."""
    backups = list_backups(mods_dir)
    for p in backups:
        shutil.rmtree(p)
    return len(backups)
