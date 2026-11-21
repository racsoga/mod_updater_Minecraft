"""Puente entre la interfaz (JS) y la lógica (Python).

pywebview expone al JS los métodos públicos de `Api` como
`window.pywebview.api.<método>()`. Python avisa al JS con
`window.onBackend(evento, datos)` (progreso, resultados, errores).

Reglas:
- La API key nunca sale de Python: el JS solo recibe `key_hint` (••••1a2b).
- El escaneo y las consultas van en un hilo aparte para no congelar la ventana.
- Todos los textos salen de locales/<idioma>.json (el JS recibe las cadenas en `strings`).
- Solo `apply` y `undo_last` modifican la carpeta de mods, y nunca con Minecraft abierto.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import webbrowser
from dataclasses import asdict
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

from .. import credentials, i18n
from ..analysis import analyze
from ..categories import Catalog
from ..config import DEFAULT_USER_AGENT, default_mods_dir
from ..curseforge import LOADER_TYPES, CurseForgeAuthError, CurseForgeClient
from ..deps import DependencyFinder, DepPlan, plan_with_dependencies
from .. import net
from ..downloader import (
    Outcome,
    friendly_error,
    interrupted_backup,
    last_undoable,
    apply_updates,
    backup_info,
    clear_backups,
    list_backups,
    prune_backups,
    undo_backup,
    updatable,
)
from ..i18n import t
from ..modrinth import ModrinthClient
from ..net import ApiError
from ..procs import minecraft_running
from ..resolver import ACTUALIZABLE, AL_DIA, CF, DESCARGA_MANUAL, INSTALL, MR, NO_ENCONTRADO, Resolution, resolve_all
from ..scanner import ModFile, peek_folder, scan_folder
from ..settings import Settings, app_dir, load_settings, save_settings
from ..versions import minecraft_versions

LOADER_LABEL = {"neoforge": "NeoForge", "forge": "Forge", "fabric": "Fabric", "quilt": "Quilt"}
SOURCE_LABEL = {"curseforge": "CurseForge", "modrinth": "Modrinth"}
STATUS_CODE = {ACTUALIZABLE: "up", AL_DIA: "ok", DESCARGA_MANUAL: "manual", NO_ENCONTRADO: "missing"}
LANGUAGE_NAMES = {"es": "Español", "en": "English"}  # cada idioma en su propia lengua


def _beta_note(r: Resolution, s: str, allow_beta: bool) -> str | None:
    """Por qué se propone una beta (tooltip de la etiqueta "beta")."""
    channel = r.new_channel if s in ("up", "dep") else r.current_channel
    if channel not in ("beta", "alpha"):
        return None
    if s == "dep":
        names = ", ".join(r.required_by)
        return t("beta.only_published", names=names) if r.only_prerelease else t("beta.allowed_dep", names=names)
    if s == "up":
        return t("beta.already") if r.current_channel in ("beta", "alpha") else t("beta.allowed")
    return t("beta.installed")


def serialize(results: list[Resolution], plan: DepPlan, *, allow_beta: bool = False) -> dict:
    """Convierte la revisión en datos para la pantalla de Resultados (sin secretos)."""
    in_plan = {id(r) for r in plan.items}
    added = {id(r) for r in plan.added_updates}
    broken = {id(b.res): b for b in plan.broken}
    rows = []
    for r in plan.installs + results:
        s = "dep" if r.kind == INSTALL else STATUS_CODE.get(r.status, "missing")
        sub, url = "", r.project_url
        if r.unreadable:
            s, sub = "unreadable", r.note  # el jar no se pudo leer: requiere atención
        elif id(r) in broken:
            # Instalado y ya roto: le falta algo que no se puede instalar solo. Requiere atención.
            b = broken[id(r)]
            s, sub, url = "manual", b.reason[:1].upper() + b.reason[1:], b.url or r.project_url
        elif s == "up" and id(r) not in in_plan:
            s, sub = "manual", t("row.duplicate")  # actualizable pero fuera del plan: duplicados
        elif s == "manual":
            sub = r.note or t("row.manual_default")
        elif s == "missing":
            file_name = r.mod.file_name if r.mod else ""
            sub = file_name if file_name != r.name else t("row.missing_default")
        elif id(r) in added:
            sub = t("row.needed_by", names=", ".join(r.required_by))
        elif s == "ok" and r.cf_gone:
            sub = t("row.cf_gone")
        elif s == "ok" and r.newer_prerelease:
            sub = t("row.newer_beta", version=r.newer_prerelease)
        rows.append({
            "id": len(rows),
            "s": s,
            "name": r.name,
            "icon": r.icon_url,
            "from": r.current_version if r.kind != INSTALL else None,
            "to": r.new_version if s in ("up", "dep") or r.status == DESCARGA_MANUAL else None,
            "beta": _beta_note(r, s, allow_beta) is not None,
            "betaNote": _beta_note(r, s, allow_beta),
            "src": SOURCE_LABEL.get(r.source or "", ""),
            "url": url,
            "sub": sub,
            "neededBy": list(r.required_by) if r.kind == INSTALL else [],
            "checked": id(r) in in_plan,
            "cat": r.categories[0] if r.categories else None,  # categoría principal (categories.py)
            "cats": list(r.categories),
            "lib": r.is_library,
        })
    return {"rows": rows, "details": list(plan.ignored), "warnings": list(plan.conflicts)}


class Api:
    def __init__(
        self,
        settings_file: Path | None = None,
        *,
        get_key: Callable = credentials.get_key,
        cf_factory: Callable = CurseForgeClient,
        mr_factory: Callable = ModrinthClient,
        run_async: Callable | None = None,
        cache_dir: Path | None = None,
        running: Callable = minecraft_running,
    ):
        self._settings_file = settings_file
        self._get_key = get_key
        self._cf_factory = cf_factory
        self._mr_factory = mr_factory
        self._run_async = run_async or (lambda fn: threading.Thread(target=fn, daemon=True).start())
        self._cache_dir = cache_dir
        self._running = running
        self._rows: list[Resolution] = []   # mismo orden que las filas enviadas al JS
        self._row_s: list[str] = []         # estado de cada fila ("up", "dep", ...)
        self._applying = False              # hay una actualización en curso (aviso al cerrar)
        self._window = None
        self._busy = threading.Lock()
        self._results: list[Resolution] = []
        self._plan: DepPlan | None = None
        i18n.set_language(self._settings().language)

    # ------------------------------------------------------------------ infraestructura

    def _attach(self, window) -> None:
        self._window = window

    def _emit(self, event: str, payload: dict) -> None:
        if self._window is not None:
            self._window.evaluate_js(f"window.onBackend({json.dumps(event)}, {json.dumps(payload, ensure_ascii=False)})")

    def _settings(self) -> Settings:
        return load_settings(self._settings_file)

    def _cache(self) -> Path:
        return self._cache_dir or app_dir() / "cache"

    # ------------------------------------------------------------------ idioma

    def get_strings(self, language: str = "auto") -> dict:
        """Cadenas de un idioma (para previsualizar el selector de Ajustes)."""
        code = i18n.resolve(language)
        return {"lang": code, "strings": i18n.strings(code)}

    # ------------------------------------------------------------------ configuración

    def get_state(self) -> dict:
        s = self._settings()
        lang = i18n.set_language(s.language)
        key, source = self._get_key()
        return {
            "settings": asdict(s) | {"mods_dir": str(s.mods_path)},
            "default_mods_dir": str(default_mods_dir()),
            "folder": peek_folder(s.mods_path),
            "has_key": bool(key),
            "key_hint": credentials.hint(key),
            "key_source": source,
            "loaders": [{"value": k, "label": LOADER_LABEL.get(k, k)} for k in LOADER_TYPES],
            "languages": [{"value": "auto", "label": None}] + [{"value": c, "label": LANGUAGE_NAMES[c]} for c in i18n.SUPPORTED],
            "lang": lang,
            "strings": i18n.strings(lang),
        }

    def mc_versions(self, include: list[str] | None = None) -> list[str]:
        """Versiones "release" de Minecraft para el desplegable (con caché y respaldo sin red)."""
        return minecraft_versions(self._mr_factory(DEFAULT_USER_AGENT), self._cache() / "mc_versions.json", include=include)

    def peek(self, path: str) -> dict:
        return peek_folder(Path(path))

    def choose_folder(self) -> dict | None:
        if self._window is None:
            return None
        import webview  # solo con ventana real

        current = str(self._settings().mods_path)
        picked = self._window.create_file_dialog(webview.FOLDER_DIALOG, directory=current)
        if not picked:
            return None
        path = picked[0] if isinstance(picked, (list, tuple)) else picked
        return {"path": path, "folder": peek_folder(Path(path))}

    def test_key(self, key: str = "") -> dict:
        """Prueba la key escrita (o la que está en uso si viene vacía). Nunca la devuelve."""
        key = (key or "").strip() or (self._get_key()[0] or "")
        if not key:
            return {"ok": False, "message": t("key.paste_first")}
        try:
            self._cf_factory(key).check()
        except CurseForgeAuthError:
            return {"ok": False, "message": t("key.rejected")}
        except (ApiError, OSError):
            return {"ok": False, "message": t("key.offline")}
        return {"ok": True, "message": t("key.valid")}

    def save_setup(self, data: dict) -> dict:
        """Guarda la pantalla de bienvenida / ajustes. Devuelve {ok, message?, state?}."""
        s = self._settings()
        if data.get("language") in ("auto", *i18n.SUPPORTED):
            s.language = data["language"]
            i18n.set_language(s.language)
        mods_dir = Path(str(data.get("mods_dir") or s.mods_path))
        if not mods_dir.is_dir():
            return {"ok": False, "field": "mods_dir", "message": t("setup.err_folder", path=mods_dir)}
        loader = data.get("loader") or s.loader
        if loader not in LOADER_TYPES:
            return {"ok": False, "field": "loader", "message": t("setup.err_loader")}
        version = str(data.get("minecraft_version") or s.minecraft_version).strip()
        if not version or not version[0].isdigit():
            return {"ok": False, "field": "minecraft_version", "message": t("setup.err_version")}

        key = str(data.get("key") or "").strip()
        if key:
            try:
                credentials.set_key(key)
            except Exception:  # noqa: BLE001 - KeyringError, RuntimeError, OSError...
                return {"ok": False, "field": "key", "message": t("key.store_failed")}
        s.mods_dir, s.loader, s.minecraft_version = str(mods_dir), loader, version
        s.use_curseforge = bool(data.get("use_curseforge", True))
        if "allow_beta" in data:
            s.allow_beta = bool(data["allow_beta"])
        if "backups_to_keep" in data:
            s.backups_to_keep = max(1, int(data["backups_to_keep"] or 1))
        s.setup_done = True
        save_settings(s, self._settings_file)
        return {"ok": True, "state": self.get_state()}

    def forget_key(self) -> dict:
        try:
            credentials.delete_key()
        except Exception:  # noqa: BLE001
            return self.get_state() | {"error": t("key.delete_failed")}
        return self.get_state()

    # ------------------------------------------------------------------ revisión

    def start_scan(self) -> bool:
        if not self._busy.acquire(blocking=False):
            return False
        self._run_async(self._scan)
        return True

    def _scan(self) -> None:
        try:
            self._emit("results", self._do_scan())
        except FileNotFoundError as exc:
            self._emit("error", {"message": t("scan.err_folder", error=exc)})
        except ApiError as exc:
            msg = t("scan.err_offline") if exc.kind == "offline" else t("scan.err_network")
            self._emit("error", {"message": msg})
        except Exception as exc:  # noqa: BLE001 - la ventana no debe quedarse colgada
            self._emit("error", {"message": t("scan.err_unknown", error=type(exc).__name__)})
        finally:
            net.retry_listener = None
            self._busy.release()

    def _retry_label(self, host: str, reason: str, wait: float) -> str:
        source = "CurseForge" if ("curseforge" in host or "forgecdn" in host) else "Modrinth" if "modrinth" in host else host
        key = {"offline": "net.retry_offline", "busy": "net.retry_busy"}.get(reason, "net.retry_error")
        return t(key, source=source, seconds=max(1, round(wait)))

    def _do_scan(self) -> dict:
        s = self._settings()
        i18n.set_language(s.language)
        notices: list[str] = []

        def progress(phase: str, label: str, done: int = 0, total: int = 0) -> None:
            self._emit("progress", {"phase": phase, "label": label, "done": done, "total": total})

        progress("read", t("scan.reading"))
        unreadable: list = []
        mods = scan_folder(
            s.mods_path,
            cache_path=self._cache() / "scan_cache.json",
            on_item=lambda i, n, p: progress("read", t("scan.reading_n", done=i, total=n), i, n),
            unreadable=unreadable,
        )
        current_phase = {"code": "cf"}
        net.retry_listener = lambda host, reason, wait: progress(current_phase["code"], self._retry_label(host, reason, wait))

        key = self._get_key()[0] if s.use_curseforge else None
        cf = self._cf_factory(key) if key else None
        mr = self._mr_factory(DEFAULT_USER_AGENT)
        if cf is None:
            notices.append(t("notice.no_key"))
        opts = dict(loader=s.loader, game_version=s.minecraft_version, allow_beta=s.allow_beta)
        labels = {"cf": t("scan.querying_cf"), "mr": t("scan.querying_mr")}

        def on_phase(code: str) -> None:
            current_phase["code"] = code
            progress(code, labels.get(code, code))

        failed: list[str] = []
        # Jerarquía de categorías de CurseForge (caché de una semana; sin key o sin red, la caché o nada).
        catalog = Catalog.load(self._cache() / "categories.json", curseforge=cf)
        try:
            results = resolve_all(mods, curseforge=cf, modrinth=mr, on_phase=on_phase, failed=failed,
                                  catalog=catalog, **opts)
        except CurseForgeAuthError:
            notices.append(t("notice.key_rejected"))
            cf = None
            results = resolve_all(mods, curseforge=None, modrinth=mr, on_phase=on_phase, failed=failed, **opts)
        if CF in failed:
            notices.append(t("notice.cf_down"))
            cf = None
        if MR in failed:
            notices.append(t("notice.mr_down"))

        progress("deps", t("scan.checking_deps"))
        current_phase["code"] = "deps"
        selected, _ = updatable(results)
        try:
            plan = plan_with_dependencies(results, selected, DependencyFinder(cf, mr, **opts))
        except ApiError:
            notices.append(t("notice.deps_unchecked"))
            plan = DepPlan(items=list(selected))

        # Jars que no se pudieron leer: se muestran en "Requieren atención" sin abortar la revisión.
        for path, exc in unreadable:
            mod = ModFile(path=path, file_name=path.name, size=0, sha1="", sha512="", cf_fingerprint=0)
            results.append(Resolution(mod=mod, status=NO_ENCONTRADO, unreadable=True,
                                      note=t("row.unreadable", error=friendly_error(exc))))
        self._results, self._plan = results, plan

        data = serialize(results, plan, allow_beta=s.allow_beta)
        self._rows = plan.installs + results
        self._row_s = [row["s"] for row in data["rows"]]
        data["notices"] = notices
        data["env"] = {
            "mods_dir": str(s.mods_path),
            "minecraft_version": s.minecraft_version,
            "loader": LOADER_LABEL.get(s.loader, s.loader),
            "curseforge": cf is not None,
        }
        return data

    # ------------------------------------------------------------------ acciones

    def apply(self, ids: list[int]) -> dict:
        """Aplica los cambios elegidos (filas "up" y "dep") en segundo plano.

        Emite "apply_progress" {id, state, message?, done, total} y al final "apply_done".
        """
        if self._plan is None:
            return {"ok": False, "message": t("apply.no_scan")}
        chosen = [self._rows[i] for i in sorted(set(ids)) if 0 <= i < len(self._rows) and self._row_s[i] in ("up", "dep")]
        if not chosen:
            return {"ok": False, "message": t("apply.nothing")}
        s = self._settings()
        if self._running(s.mods_path.parent):
            return {"ok": False, "reason": "minecraft", "message": t("apply.minecraft_open")}
        if not self._busy.acquire(blocking=False):
            return {"ok": False, "message": t("apply.busy")}
        self._run_async(lambda: self._apply(chosen, s))
        return {"ok": True, "total": len(chosen)}

    def _apply(self, chosen: list[Resolution], s: Settings) -> None:
        index = {id(r): i for i, r in enumerate(self._rows)}
        total, done = len(chosen), 0
        self._applying = True
        net.retry_listener = lambda host, reason, wait: self._emit(
            "apply_wait", {"label": self._retry_label(host, reason, wait)})
        try:
            key = self._get_key()[0] if s.use_curseforge else None
            cf = self._cf_factory(key) if key else None
            mr = self._mr_factory(DEFAULT_USER_AGENT)

            def on_state(res: Resolution, state) -> None:
                nonlocal done
                payload = {"id": index[id(res)], "total": total}
                if isinstance(state, Outcome):
                    done += 1
                    payload |= {"state": ("installed" if res.kind == INSTALL else "done") if state.ok else "error",
                                "message": "" if state.ok else state.message}
                else:
                    payload["state"] = state
                self._emit("apply_progress", payload | {"done": done})

            backup_dir, outcomes = apply_updates(
                chosen, s.mods_path,
                modrinth_session=mr.session, curseforge_session=cf.session if cf else None,
                on_state=on_state,
            )
            ok = [o for o in outcomes if o.ok]
            pruned = prune_backups(s.mods_path, s.backups_to_keep) if ok else []
            self._plan = None  # la revisión ya no refleja la carpeta: hay que volver a revisar
            self._emit("apply_done", {
                "updated": sum(1 for o in ok if o.resolution.kind != INSTALL),
                "installed": sum(1 for o in ok if o.resolution.kind == INSTALL),
                "failed": [{"name": o.resolution.name, "message": o.message} for o in outcomes if not o.ok],
                "backup": backup_info(backup_dir) if backup_dir.exists() else None,
                "pruned": len(pruned),
            })
        except Exception as exc:  # noqa: BLE001 - la ventana no debe quedarse colgada
            self._emit("apply_done", {"updated": 0, "installed": 0, "failed": [], "backup": None, "pruned": 0,
                                      "error": t("apply.err_unknown", error=friendly_error(exc))})
        finally:
            self._applying = False
            net.retry_listener = None
            self._busy.release()

    def _is_applying(self) -> bool:
        """Para el aviso al cerrar la ventana (gui/app.py)."""
        return self._applying

    # ------------------------------------------------------------------ análisis

    def analysis(self, include_libraries: bool = False) -> dict:
        """Cifras de la colección según la última revisión (pestaña Análisis)."""
        if not self._results:
            return {"ready": False}
        return {"ready": True, **analyze(self._results, include_libraries=bool(include_libraries),
                                          game_version=self._settings().minecraft_version)}

    # ------------------------------------------------------------------ backups y deshacer

    def backups_info(self) -> dict:
        mods_path = self._settings().mods_path
        backups = list_backups(mods_path)
        target = last_undoable(mods_path)
        return {"count": len(backups), "last": backup_info(target) if target else None}

    def interrupted(self) -> dict | None:
        """Al abrir la app: ¿hay una actualización que se quedó a medias? (para ofrecer restaurarla)."""
        try:
            target = interrupted_backup(self._settings().mods_path)
        except OSError:
            return None
        return backup_info(target) if target else None

    def restore_interrupted(self) -> dict:
        """Deshace la actualización interrumpida: la carpeta queda como antes de empezarla."""
        return self._undo(interrupted_backup(self._settings().mods_path))

    def undo_last(self) -> dict:
        """Deshace la última actualización que se pueda deshacer (aunque después haya
        habido un intento fallido o una actualización interrumpida a medias)."""
        return self._undo(last_undoable(self._settings().mods_path))

    def _undo(self, target: Path | None) -> dict:
        s = self._settings()
        if target is None:
            return {"ok": False, "message": t("undo.none")}
        if self._running(s.mods_path.parent):
            return {"ok": False, "reason": "minecraft", "message": t("undo.minecraft_open")}
        if not self._busy.acquire(blocking=False):
            return {"ok": False, "message": t("apply.busy")}
        try:
            r = undo_backup(target)
        finally:
            self._busy.release()
        self._plan = None
        return {"ok": not r.errors, "restored": r.restored, "removed": r.removed, "errors": r.errors,
                "message": t("undo.done", count=r.restored, removed=r.removed)}

    def clear_backups(self) -> dict:
        if not self._busy.acquire(blocking=False):
            return {"ok": False, "message": t("apply.busy")}
        try:
            n = clear_backups(self._settings().mods_path)
        finally:
            self._busy.release()
        return {"ok": True, "count": n, "message": t("backups.cleared", count=n)}

    def open_url(self, url: str) -> bool:
        if urlparse(url or "").scheme not in ("http", "https"):
            return False
        webbrowser.open(url)
        return True

    def open_mods_folder(self) -> bool:
        path = self._settings().mods_path
        if not path.is_dir() or os.name != "nt":
            return False
        # explorer.exe <carpeta> abre una ventana nueva en esa carpeta y en primer plano
        # (os.startfile puede dejarla detrás de la app).
        subprocess.Popen(["explorer.exe", str(path.resolve())], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return True
