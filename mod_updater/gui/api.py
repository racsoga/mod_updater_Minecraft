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

import hashlib
import json
import os
import re
import subprocess
import threading
import time
import webbrowser
from datetime import datetime
from dataclasses import asdict, replace
from pathlib import Path
from typing import Callable

import requests
from urllib.parse import urlparse

from .. import credentials, i18n
from ..analysis import analyze
from .. import profiles
from ..categories import Catalog
from ..launchers import detect_instances, loader_version_for
from .. import modlist as modlist_mod
from ..app_update import check_latest
from ..knowledge import load_knowledge
from ..suggest import STYLES, suggest
from .. import __version__
from ..changelog import changelog_for
from ..explore import PAGE_SIZE, _installed_index, detail as explore_detail_of, search as explore_search_in
from ..config import DEFAULT_USER_AGENT, default_mods_dir
from ..curseforge import LOADER_TYPES, CurseForgeAuthError, CurseForgeClient
from ..deps import DependencyFinder, DepPlan, dependents_of, keep_needed, plan_with_dependencies, required_disabled
from ..resolver import DISABLE, ENABLE, REMOVE, UPDATE, Dep
from ..pins import apply_pins, find_pins, pin_entry, pin_key
from .. import diagnose as diag
from .. import bisect as bis
from .. import migrate as migrate_mod
from ..deps import _current_deps, _needs
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
    read_changelog,
    toggle_one,
    write_changelog_json,
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
            # Instalado y ya roto: le falta algo que no se puede instalar solo. Requiere atención
            # (aunque esté fijado: fijar no arregla que no cargue).
            b = broken[id(r)]
            s, sub, url = "manual", b.reason[:1].upper() + b.reason[1:], b.url or r.project_url
        elif r.pinned and r.kind != INSTALL:  # fijado por el usuario: no se actualiza
            s = "pin"
            sub = r.pin_reason or (t("row.pinned", version=r.current_version or "?", new=r.new_version)
                                   if r.new_version else t("row.pinned_same", version=r.current_version or "?"))
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
            "to": r.new_version if s in ("up", "dep", "pin") or r.status == DESCARGA_MANUAL else None,
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
            "off": bool(r.mod is not None and r.mod.disabled),
            "file": r.mod.file_name if r.mod is not None else None,
            "cl": r.kind != INSTALL and bool(r.new_version) and r.status in (ACTUALIZABLE, DESCARGA_MANUAL)
                  and r.source in (CF, MR),
            # Versiones (fijar / volver a una anterior): cualquier mod instalado e identificado.
            "vers": r.kind != INSTALL and r.mod is not None and not r.unreadable and r.source in (CF, MR),
        })
    return {"rows": rows, "details": list(plan.ignored), "warnings": list(plan.conflicts)}


MAX_VERSION_LIST = 40  # versiones que se ofrecen para volver atrás
DIAG_NEW_DAYS = 14
MIGRATE_ROW = 400000  # ids de las filas de la pantalla de aplicar al crear un perfil para otra versión  # un crash report más viejo no se avisa como nuevo
ROLLBACK_ROW = 300000  # id de la fila en la pantalla de aplicar


def _join(names: list[str]) -> str:
    """"A, B y C" en el idioma de la interfaz."""
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + t("ui.and") + names[-1]


def _never_hang(method):
    """Las llamadas desde la ventana siempre responden: un error inesperado se devuelve como
    mensaje en vez de dejar la interfaz esperando (botones desactivados, "Cargando…")."""
    import functools

    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        try:
            return method(self, *args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "message": t("scan.err_unknown", error=type(exc).__name__)}
    return wrapper


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
        self._changelogs: dict = {}         # changelogs ya descargados (por mod y rango de versiones)
        self._version_lists: dict = {}      # versiones publicadas de cada mod (para volver atrás)
        self._migration: dict | None = None  # última comprobación de "pasar a otra versión"
        self._diag_reports: list = []       # informes de la pestaña Diagnóstico (id = posición)
        self._diag_actions: dict = {}       # acciones propuestas por el diagnóstico (id -> diag.Action)
        self._diag_cards: dict = {}         # tarjetas del último diagnóstico de cada informe (para copiar)
        self._explore_cache: dict = {}      # búsquedas recientes (no repetir peticiones al volver atrás)
        self._install: list[Resolution] = []  # plan de la cesta de Explorar, pendiente de confirmar
        self._import: dict | None = None    # lista importada y comparada, pendiente de confirmar
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

    def _scan_cache(self, mods_dir: Path) -> Path:
        """Caché de hashes de UNA carpeta: la clave del escáner es nombre|tamaño|fecha, así que dos
        perfiles con un jar igual de nombre, tamaño y fecha pero distinto contenido no deben compartirla."""
        key = hashlib.sha1(os.path.normcase(str(Path(mods_dir).resolve())).encode("utf-8")).hexdigest()[:12]
        return self._cache() / f"scan_cache_{key}.json"

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
            "profiles": profiles.listing(s),
            "same_folder": profiles.same_folder(s),
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

    # ------------------------------------------------------------------ perfiles

    def _reset_session(self) -> None:
        """Al cambiar de perfil, lo revisado del anterior ya no vale."""
        self._results, self._plan, self._rows, self._row_s = [], None, [], []
        self._explore_cache.clear()
        self._changelogs.clear()
        self._install = []
        self._import = None

    def profile_switch(self, profile_id: str) -> dict:
        if not self._busy.acquire(blocking=False):
            return {"ok": False, "message": t("apply.busy")}
        try:
            s = self._settings()
            profiles.switch(s, str(profile_id))
            save_settings(s, self._settings_file)
            self._reset_session()
        except KeyError:
            return {"ok": False, "message": t("profile.not_found")}
        finally:
            self._busy.release()
        return {"ok": True, "state": self.get_state()}

    def profile_detect(self) -> list[dict]:
        """Instancias de launchers que aún no son un perfil."""
        known = {os.path.normcase(os.path.normpath(p.get("mods_dir", ""))) for p in self._settings().profiles}
        try:
            found = detect_instances()
        except OSError:
            return []
        return [i for i in found if os.path.normcase(os.path.normpath(i["mods_dir"])) not in known]

    @_never_hang
    def profile_add(self, data: dict) -> dict:
        data = data or {}
        mods_dir = Path(str(data.get("mods_dir") or "")).expanduser()
        if not mods_dir.is_dir():
            return {"ok": False, "message": t("setup.err_folder", path=mods_dir)}
        peek = peek_folder(mods_dir)
        loader = data.get("loader") or peek.get("loader") or "neoforge"
        version = data.get("minecraft_version") or peek.get("minecraft_version") or "1.21.1"
        if loader not in LOADER_TYPES:
            loader = "neoforge"
        s = self._settings()
        name = str(data.get("name") or "").strip() or mods_dir.parent.name or t("profile.default_name")
        pid = profiles.add(s, name=name, mods_dir=str(mods_dir), minecraft_version=version, loader=loader)
        save_settings(s, self._settings_file)
        return {"ok": True, "id": pid, "state": self.get_state()}

    def profile_rename(self, profile_id: str, name: str) -> dict:
        s = self._settings()
        try:
            profiles.rename(s, str(profile_id), name)
        except KeyError:
            return {"ok": False, "message": t("profile.not_found")}
        save_settings(s, self._settings_file)
        return {"ok": True, "state": self.get_state()}

    def profile_remove(self, profile_id: str) -> dict:
        """Quita el perfil de la lista; su carpeta y sus mods no se tocan."""
        if self._bisect_file(self._settings(), str(profile_id)).exists():
            return {"ok": False, "reason": "bisect", "message": t("bs.busy")}
        if not self._busy.acquire(blocking=False):  # no cambiar de carpeta a mitad de una revisión
            return {"ok": False, "message": t("apply.busy")}
        try:
            s = self._settings()
            was_active = s.active_profile == profile_id
            try:
                profiles.remove(s, str(profile_id))
            except ValueError:
                return {"ok": False, "message": t("profile.last")}
            save_settings(s, self._settings_file)
        finally:
            self._busy.release()
        if was_active:
            self._reset_session()
        return {"ok": True, "switched": was_active, "state": self.get_state()}

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
        if self._busy.locked():  # a mitad de una revisión o actualización: la carpeta no puede cambiar
            return {"ok": False, "message": t("apply.busy")}
        s = self._settings()
        new_dir = data.get("mods_dir")
        if new_dir and os.path.normcase(os.path.normpath(str(new_dir))) != os.path.normcase(os.path.normpath(str(s.mods_path)))                 and self._bisect_active():  # la búsqueda por mitades se quedaría con mods desactivados sin aviso
            return {"ok": False, "reason": "bisect", "message": t("bs.busy")}
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
        if "check_updates" in data:
            s.check_updates = bool(data["check_updates"])
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
            cache_path=self._scan_cache(s.mods_path),
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

        apply_pins(results, s.pins or {})  # los fijados no se actualizan (pins.py)
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

    def _bisect_active(self) -> bool:
        return self._bisect_load() is not None

    def apply(self, ids: list[int]) -> dict:
        """Aplica los cambios elegidos (filas "up" y "dep") en segundo plano.

        Emite "apply_progress" {id, state, message?, done, total} y al final "apply_done".
        """
        if self._plan is None:
            return {"ok": False, "message": t("apply.no_scan")}
        if self._bisect_active():
            return {"ok": False, "reason": "bisect", "message": t("bs.busy")}
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

    def _apply(self, chosen: list[Resolution], s: Settings, index: dict | None = None, after=None) -> list[Outcome]:
        index = index or {id(r): i for i, r in enumerate(self._rows)}
        result: list[Outcome] = []
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
                    ok_state = {INSTALL: "installed", REMOVE: "removed"}.get(res.kind, "done")
                    payload |= {"state": ok_state if state.ok else "error",
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
            result = outcomes
            if after is not None:  # p. ej. fijar tras volver a una versión anterior (con el bloqueo puesto)
                after(outcomes)
            pruned = prune_backups(s.mods_path, s.backups_to_keep) if ok else []
            self._plan = None  # la revisión ya no refleja la carpeta: hay que volver a revisar
            self._results = []
            self._emit("apply_done", {
                "updated": sum(1 for o in ok if o.resolution.kind not in (INSTALL, REMOVE)),
                "removed": sum(1 for o in ok if o.resolution.kind == REMOVE),
                "installed": sum(1 for o in ok if o.resolution.kind == INSTALL and o.resolution.required_by),
                "added": sum(1 for o in ok if o.resolution.kind == INSTALL and not o.resolution.required_by),
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
            self._version_lists.clear()  # lo instalado ha cambiado
            self._busy.release()
        return result

    def _is_applying(self) -> bool:
        """Para el aviso al cerrar la ventana (gui/app.py)."""
        return self._applying

    # ------------------------------------------------------------------ explorar

    def _clients(self, s: Settings):
        key = self._get_key()[0] if s.use_curseforge else None
        return (self._cf_factory(key) if key else None), self._mr_factory(DEFAULT_USER_AGENT)

    @_never_hang
    def explore_search(self, opts: dict) -> dict:
        """Busca mods para la versión y el cargador de los ajustes. opts: query, category, sort,
        page, hide_installed. Devuelve tarjetas sin duplicados entre fuentes."""
        s = self._settings()
        opts = opts or {}
        args = dict(query=str(opts.get("query") or "").strip()[:100], category=opts.get("category") or None,
                    sort=opts.get("sort") or "popular", page=max(0, int(opts.get("page") or 0)),
                    hide_installed=bool(opts.get("hide_installed")))
        key = (str(s.mods_path), s.minecraft_version, s.loader, tuple(sorted(args.items())), len(self._results))
        if key not in self._explore_cache:
            cf, mr = self._clients(s)
            try:
                cards = explore_search_in(cf, mr, installed=self._results, game_version=s.minecraft_version,
                                          loader=s.loader, **args)
            except ApiError as exc:
                return {"ok": False, "message": t("scan.err_offline") if exc.kind == "offline" else t("ex.err_network")}
            if len(self._explore_cache) > 60:
                self._explore_cache.clear()
            self._explore_cache[key] = cards
        cards = self._explore_cache[key]
        return {"ok": True, "cards": cards, "page": args["page"], "more": len(cards) >= PAGE_SIZE // 2,
                "env": {"minecraft_version": s.minecraft_version, "loader": LOADER_LABEL.get(s.loader, s.loader)},
                "scanned": bool(self._results)}

    @_never_hang
    def explore_detail(self, source: str, project_id: str) -> dict:
        """Descripción, capturas, enlaces y versión que se instalaría (con sus dependencias)."""
        s = self._settings()
        cf, mr = self._clients(s)
        try:
            info = explore_detail_of(cf, mr, source=source, project_id=str(project_id))
            finder = DependencyFinder(cf, mr, loader=s.loader, game_version=s.minecraft_version, allow_beta=s.allow_beta)
            res = finder.find(Dep(source, str(project_id)))
        except ApiError as exc:
            return {"ok": False, "message": t("scan.err_offline") if exc.kind == "offline" else t("ex.err_network")}
        ids, _ = _installed_index(self._results)
        install = None
        if res is not None:
            install = {"version": res.new_version, "beta": res.new_channel not in (None, "release"),
                       "manual": res.status != ACTUALIZABLE, "via": SOURCE_LABEL.get(res.source or "", ""),
                       "deps": [{"name": finder.describe(d), "installed": d.key in ids} for d in res.new_deps]}
        return {"ok": True, **info, "install": install}

    @_never_hang
    def install_plan(self, items: list) -> dict:
        """Prepara la instalación de la cesta: versión de cada mod y dependencias que faltan."""
        if not self._results:
            return {"ok": False, "message": t("ex.need_scan")}
        s = self._settings()
        cf, mr = self._clients(s)
        finder = DependencyFinder(cf, mr, loader=s.loader, game_version=s.minecraft_version, allow_beta=s.allow_beta)
        ids, _ = _installed_index(self._results)
        chosen: list[Resolution] = []
        manual, unavailable, already = [], [], []
        try:
            for it in items or []:
                src, pid, name = it.get("source"), str(it.get("id")), it.get("name") or "?"
                if (src, pid) in ids:
                    already.append(name)
                    continue
                res = finder.find(Dep(src, pid))
                if res is None:
                    unavailable.append(name)
                elif res.status != ACTUALIZABLE:
                    manual.append({"name": res.name, "url": res.project_url})
                else:
                    chosen.append(res)
            plan = plan_with_dependencies(self._results, chosen, finder)
        except ApiError as exc:
            return {"ok": False, "message": t("scan.err_offline") if exc.kind == "offline" else t("ex.err_network")}
        blocked = {id(r) for r in plan.blocked}
        self._install = [r for r in plan.items if id(r) not in blocked]
        overlaps = self._overlaps([r for r in chosen if id(r) not in blocked])
        rows = [{"id": 100000 + i, "s": "dep" if r.kind == INSTALL else "up", "name": r.name, "icon": r.icon_url,
                 "from": r.current_version if r.kind != INSTALL else None, "to": r.new_version,
                 "beta": r.new_channel not in (None, "release"), "neededBy": list(r.required_by), "size": r.new_size}
                for i, r in enumerate(self._install)]
        return {"ok": True, "rows": rows, "size": sum(r.new_size for r in self._install), "overlaps": overlaps,
                "manual": manual, "unavailable": unavailable, "already": already,
                "blocked": [{"name": r.name, "reason": r.note} for r in plan.blocked]}

    def _overlaps(self, new: list[Resolution]) -> list[str]:
        """Avisos: un mod nuevo hace lo mismo que otro que ya tienes (ej.: dos mochilas)."""
        out = []
        for g in load_knowledge()["solapamientos"]:
            keys = [{(CF, str(m["curseforge"])) for m in [x] if m.get("curseforge")}
                    | {(MR, str(m["modrinth"])) for m in [x] if m.get("modrinth")} for x in g["mods"]]
            group_keys = set().union(*keys)
            have = next((r for r in self._results if r.mod is not None and r.known_ids & group_keys), None)
            for r in new:
                if have is not None and r.known_ids & group_keys and not (r.known_ids & have.known_ids):
                    out.append(t("ex.overlap", name=r.name, other=have.name, group=t(f"sug.group.{g['grupo']}")))
        return out

    # ------------------------------------------------------------------ nuevas versiones de la app

    def app_update(self) -> dict | None:
        """¿Hay una versión nueva de Mod Updater? (None si no, sin red o si el aviso está desactivado)."""
        if not self._settings().check_updates:
            return None
        session = requests.Session()
        session.headers["User-Agent"] = DEFAULT_USER_AGENT
        return check_latest(__version__, cache_path=self._cache() / "app_update.json", session=session)

    # ------------------------------------------------------------------ sugerencias

    def suggest_answers(self) -> dict:
        return self._settings().answers or {}

    @_never_hang
    def suggest_run(self, answers: dict) -> dict:
        """Guarda las respuestas en el perfil y calcula Quitar · Mantener · Añadir."""
        if not self._results:
            return {"ok": False, "message": t("ex.need_scan")}
        a = answers or {}
        clean = {"players": a.get("players") if a.get("players") in ("solo", "amigos", "servidor") else "solo",
                 "styles": [x for x in a.get("styles") or [] if x in STYLES],
                 "difficulty": a.get("difficulty") if a.get("difficulty") in ("relajada", "normal", "reto") else "normal",
                 "pc": a.get("pc") if a.get("pc") in ("justo", "normal", "potente") else "normal",
                 "max": a.get("max") if a.get("max") in (0, 50, 100, 150) else 0}
        s = self._settings()
        s.answers = clean
        save_settings(s, self._settings_file)
        cf, mr = self._clients(s)
        finder = DependencyFinder(cf, mr, loader=s.loader, game_version=s.minecraft_version, allow_beta=s.allow_beta)
        try:
            res = suggest(clean, self._results, finder, knowledge=load_knowledge())
        except ApiError as exc:
            return {"ok": False, "message": t("scan.err_offline") if exc.kind == "offline" else t("ex.err_network")}
        return {"ok": True, "answers": clean, "total": len([r for r in self._results if r.mod is not None]), **res}

    @_never_hang
    def suggest_plan(self, selection: dict) -> dict:
        """Prepara lo marcado: añadir (con dependencias, como la cesta) y quitar (a la copia)."""
        sel = selection or {}
        adds = [{"source": x.get("source"), "id": x.get("id"), "name": x.get("name")} for x in sel.get("add") or []]
        res = self.install_plan(adds) if adds else {"ok": True, "rows": [], "size": 0, "overlaps": [], "manual": [],
                                                     "unavailable": [], "already": [], "blocked": []}
        if not adds:
            self._install = []
        if not res.get("ok"):
            return res
        files = set(sel.get("remove") or [])
        wanted = [r for r in self._results if r.mod is not None and r.mod.file_name in files]
        wanted, res["kept"] = keep_needed(self._results, wanted, self._install)  # issue #12
        removals = [replace(r, kind=REMOVE) for r in wanted]
        start = len(self._install)
        self._install += removals
        res["rows"] += [{"id": 100000 + start + i, "s": "rm", "name": r.name, "icon": r.icon_url, "from": r.current_version,
                         "to": None, "beta": False, "neededBy": []} for i, r in enumerate(removals)]
        res["removals"] = [r.name for r in removals]
        return res

    def install_start(self) -> dict:
        """Instala el plan preparado con install_plan (misma pantalla y copia que al actualizar)."""
        if not self._install:
            return {"ok": False, "message": t("apply.nothing")}
        if self._bisect_active():
            return {"ok": False, "reason": "bisect", "message": t("bs.busy")}
        s = self._settings()
        if self._running(s.mods_path.parent):
            return {"ok": False, "reason": "minecraft", "message": t("apply.minecraft_open")}
        if not self._busy.acquire(blocking=False):
            return {"ok": False, "message": t("apply.busy")}
        chosen, self._install = self._install, []
        index = {id(r): 100000 + i for i, r in enumerate(chosen)}
        self._explore_cache.clear()  # "Ya instalado" cambia tras instalar
        self._run_async(lambda: self._apply(chosen, s, index))
        return {"ok": True, "total": len(chosen)}

    # ------------------------------------------------------------------ lista de mods

    def _file_dialog(self, save: bool, file_name: str = "", types: tuple = ()) -> str | None:
        """Diálogo de Windows para guardar o abrir (sustituible en los tests)."""
        if self._window is None:
            return None
        import webview  # solo con ventana real

        kind = webview.SAVE_DIALOG if save else webview.OPEN_DIALOG
        picked = self._window.create_file_dialog(kind, save_filename=file_name, file_types=types)
        if not picked:
            return None
        return picked[0] if isinstance(picked, (list, tuple)) else picked

    def _clipboard(self, text: str) -> None:
        subprocess.run(["clip"], input=text.encode("utf-16-le"), check=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

    def _active_name(self, s: Settings) -> str:
        return (profiles.get(s, s.active_profile) or {}).get("name") or t("profile.default_name")

    @_never_hang
    def modlist_export(self, kind: str = "modlist") -> dict:
        """Guarda la lista del perfil activo (.modlist.json propio o .mrpack de Modrinth)."""
        if not self._results:
            return {"ok": False, "message": t("ex.need_scan")}
        s = self._settings()
        name = self._active_name(s)
        safe = re.sub(r'[\\/:*?"<>|]+', "_", name).strip() or "mods"
        if kind == "mrpack":
            path = self._file_dialog(True, f"{safe}.mrpack", (t("ml.type_mrpack") + " (*.mrpack)",))
            if not path:
                return {"ok": False, "cancelled": True}
            mr = self._mr_factory(DEFAULT_USER_AGENT)
            try:
                by_sha = mr.versions_from_hashes([r.mod.sha1 for r in self._results if r.mod is not None])
            except ApiError:
                return {"ok": False, "message": t("ex.err_network")}
            lv = loader_version_for(str(s.mods_path))
            blob, excluded = modlist_mod.build_mrpack(self._results, by_sha, name=name, minecraft=s.minecraft_version,
                                                      loader=s.loader, loader_version=lv)
            Path(path).write_bytes(blob)
            return {"ok": True, "file": Path(path).name, "excluded": excluded, "no_loader_version": lv is None}
        path = self._file_dialog(True, f"{safe}.modlist.json", (t("ml.type_modlist") + " (*.modlist.json)",))
        if not path:
            return {"ok": False, "cancelled": True}
        data = modlist_mod.build(self._results, minecraft=s.minecraft_version, loader=s.loader,
                                 app=f"Mod Updater {__version__}")
        Path(path).write_text(modlist_mod.dumps(data), encoding="utf-8")
        return {"ok": True, "file": Path(path).name, "excluded": [], "count": len(data["mods"])}

    @_never_hang
    def modlist_import(self) -> dict:
        """Abre una lista y la compara con el perfil activo (no instala nada todavía)."""
        if not self._results:
            return {"ok": False, "message": t("ex.need_scan")}
        path = self._file_dialog(False, "", (t("ml.type_modlist") + " (*.modlist.json;*.json)",))
        if not path:
            return {"ok": False, "cancelled": True}
        try:
            data = modlist_mod.parse(Path(path).read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, modlist_mod.ModlistError):
            return {"ok": False, "message": t("ml.err_file")}
        s = self._settings()
        c = modlist_mod.compare(data, self._results, minecraft=s.minecraft_version, loader=s.loader)
        c["remove"], kept = keep_needed(self._results, c["remove"])  # lo que sobra pero necesita un mod que se queda
        self._import = c
        row = lambda m: {"name": m["nombre"], "version": m.get("version"), "have": m.get("tienes"),  # noqa: E731
                         "off": m.get("activo") is False}
        return {"ok": True, "file": Path(path).name, "mismatch": c["mismatch"],
                "profile": {"minecraft": s.minecraft_version, "loader": LOADER_LABEL.get(s.loader, s.loader)},
                "add": [row(m) for m in c["add"]], "update": [row(m) for m in c["update"]],
                "same": len(c["same"]), "unavailable": [row(m) for m in c["unavailable"]],
                "remove": [{"name": r.name, "version": r.current_version} for r in c["remove"]], "kept": kept}

    @_never_hang
    def modlist_import_start(self, remove: bool = False) -> dict:
        """Instala las versiones exactas de la lista importada (y quita lo que sobra si se pide)."""
        if not self._import:
            return {"ok": False, "message": t("apply.nothing")}
        if self._bisect_active():
            return {"ok": False, "reason": "bisect", "message": t("bs.busy")}
        s = self._settings()
        if self._running(s.mods_path.parent):
            return {"ok": False, "reason": "minecraft", "message": t("apply.minecraft_open")}
        cf, mr = self._clients(s)
        try:
            chosen, manual = modlist_mod.resolve_exact(self._import, self._results, curseforge=cf, modrinth=mr)
        except ApiError as exc:
            return {"ok": False, "message": t("scan.err_offline") if exc.kind == "offline" else t("ex.err_network")}
        pinned = [m for k in ("add", "update", "same") for m in self._import.get(k, []) if m.get("fijado") and m.get("fuente")]
        if pinned:  # la lista trae mods fijados: también quedan fijados aquí
            s.pins = {**{f"{m['fuente']}:{m['proyecto']}": {
                "name": m.get("nombre") or "?", "version": m.get("version") or "", "reason": ""} for m in pinned},
                **(s.pins or {})}  # una fijación que ya tenías (con su motivo) se respeta
            save_settings(s, self._settings_file)
        if remove:  # primero se quitan (así un jar con el mismo nombre que uno nuevo no choca)
            chosen = [replace(r, kind=REMOVE) for r in self._import["remove"]] + chosen
        if not chosen:
            return {"ok": False, "message": t("apply.nothing"), "manual": manual}
        if not self._busy.acquire(blocking=False):
            return {"ok": False, "message": t("apply.busy")}
        self._import = None
        index = {id(r): 200000 + i for i, r in enumerate(chosen)}
        rows = [{"id": 200000 + i, "s": {INSTALL: "dep", REMOVE: "rm"}.get(r.kind, "up"), "name": r.name, "icon": r.icon_url,
                 "from": r.current_version, "to": None if r.kind == REMOVE else r.new_version, "beta": False, "neededBy": []}
                for i, r in enumerate(chosen)]
        self._explore_cache.clear()
        self._run_async(lambda: self._apply(chosen, s, index))
        return {"ok": True, "rows": rows, "manual": manual}

    @_never_hang
    def compare_profiles(self, other_id: str) -> dict:
        """Compara (sin red) la carpeta del perfil activo con la de otro perfil."""
        s = self._settings()
        other = profiles.get(s, str(other_id))
        if other is None:
            return {"ok": False, "message": t("profile.not_found")}
        try:
            a = scan_folder(s.mods_path, cache_path=self._scan_cache(s.mods_path))
            b = scan_folder(Path(other["mods_dir"]), cache_path=self._scan_cache(Path(other["mods_dir"])))
        except FileNotFoundError:
            return {"ok": False, "message": t("ml.err_compare_folder")}
        return {"ok": True, "a": self._active_name(s), "b": other.get("name"), **modlist_mod.compare_folders(a, b)}

    def copy_list(self) -> dict:
        """Copia al portapapeles "Nombre versión" de cada mod, para pegarlo en un chat."""
        if not self._results:
            return {"ok": False, "message": t("ex.need_scan")}
        text = modlist_mod.readable(self._results)
        try:
            self._clipboard(text)
        except (OSError, subprocess.SubprocessError):
            return {"ok": False, "message": t("ml.err_clipboard"), "text": text}
        return {"ok": True, "count": len(text.splitlines())}

    # ------------------------------------------------------------------ changelog

    def changelog(self, row_id: int) -> dict:
        """Notas de todas las versiones entre la instalada y la nueva de una fila de Mis mods."""
        try:
            r = self._rows[int(row_id)]
        except (IndexError, TypeError, ValueError):
            return {"ok": False, "message": t("cl.not_found")}
        key = (r.source, r.project_id, r.current_date, r.new_date)
        if key not in self._changelogs:
            s = self._settings()
            api_key = self._get_key()[0] if s.use_curseforge else None
            try:
                data = changelog_for(
                    r, curseforge=self._cf_factory(api_key) if api_key and r.source == CF else None,
                    modrinth=self._mr_factory(DEFAULT_USER_AGENT), game_version=s.minecraft_version, loader=s.loader)
            except ApiError as exc:
                return {"ok": False, "message": t("scan.err_offline") if exc.kind == "offline" else t("cl.err_network")}
            except Exception as exc:  # noqa: BLE001 - la ventana nunca debe quedarse esperando
                return {"ok": False, "message": t("cl.err_unknown", error=type(exc).__name__)}
            self._changelogs[key] = data
        return {"ok": True, "name": r.name, "from": r.current_version, "to": r.new_version,
                "url": r.project_url, **self._changelogs[key]}

    # ------------------------------------------------------------------ fijar y versiones anteriores

    def _pin_row(self, row_id) -> Resolution | None:
        try:
            r = self._rows[int(row_id)]
        except (IndexError, TypeError, ValueError):
            return None
        return r if r.mod is not None and pin_key(r) else None

    def _save_pin(self, r: Resolution, *, on: bool, version: str | None = None, reason: str = "") -> dict:
        """Fija o suelta `r` en el perfil activo. Devuelve las entradas que había antes."""
        s = self._settings()
        pins = dict(s.pins or {})
        previous = {k: pins.pop(k) for k in find_pins(r, pins)}
        if on:
            pins[pin_key(r)] = pin_entry(r, version=version, reason=reason)
        s.pins = pins
        save_settings(s, self._settings_file)
        return previous

    def pin_set(self, row_id, pinned: bool, reason: str = "") -> dict:
        """Fija ("No actualizar este") o suelta un mod del perfil activo, con un motivo opcional."""
        r = self._pin_row(row_id)
        if r is None:
            return {"ok": False, "message": t("cl.not_found")}
        reason = " ".join(str(reason or "").split())[:200] if pinned else ""
        self._save_pin(r, on=bool(pinned), version=r.current_version, reason=reason)
        r.pinned, r.pin_reason = bool(pinned), reason
        return {"ok": True}

    def _versions(self, r: Resolution, s: Settings) -> list[dict]:
        """Versiones publicadas para la versión de Minecraft y el cargador del perfil (más nuevas primero)."""
        key = (r.source, r.project_id, s.minecraft_version, s.loader)
        if key in self._version_lists:
            return self._version_lists[key]
        out = []
        if r.source == MR:
            for v in self._mr_factory(DEFAULT_USER_AGENT).project_versions(r.project_id, s.loader, s.minecraft_version):
                f = v.primary_file
                out.append({"id": v.id, "version": v.version_number, "date": v.date_published, "channel": v.version_type,
                            "url": f.url if f else None, "file": f.filename if f else None, "sha1": f.sha1 if f else None,
                            "sha512": f.sha512 if f else None, "size": f.size if f else 0})
        elif r.source == CF:
            api_key = self._get_key()[0] if s.use_curseforge else None
            if not api_key:
                return []
            for f in self._cf_factory(api_key).mod_files(int(r.project_id), s.minecraft_version, s.loader):
                # Sin hash no se puede verificar la descarga: se ofrece como descarga manual.
                out.append({"id": f.id, "version": f.display_name, "date": f.date_published, "channel": f.version_type,
                            "url": f.download_url if f.sha1 else None, "file": f.file_name, "sha1": f.sha1,
                            "sha512": None, "size": f.size})
        out.sort(key=lambda v: v["date"] or "", reverse=True)
        self._version_lists[key] = out[:MAX_VERSION_LIST]
        return self._version_lists[key]

    @staticmethod
    def _is_current(r: Resolution, v: dict) -> bool:
        return v["id"] == r.current_file_id or bool(v["sha1"] and r.mod is not None and v["sha1"] == r.mod.sha1)

    @_never_hang
    def versions_for(self, row_id) -> dict:
        """Lista para "Volver a una versión anterior" (en el panel de Ver cambios)."""
        r = self._pin_row(row_id)
        if r is None:
            return {"ok": False, "message": t("cl.not_found")}
        base = {"pinned": r.pinned, "reason": r.pin_reason, "current": r.current_version}
        try:
            versions = self._versions(r, self._settings())
        except ApiError as exc:  # sin red se puede seguir fijando o soltando
            return {"ok": False, "message": t("scan.err_offline") if exc.kind == "offline" else t("cl.err_network"), **base}
        return {"ok": True, **base,
                "versions": [{"id": v["id"], "version": v["version"], "date": v["date"], "channel": v["channel"],
                              "current": self._is_current(r, v), "manual": not v["url"]} for v in versions]}

    @_never_hang
    def rollback(self, row_id, version_id: str) -> dict:
        """Instala esa versión exacta (con copia y Deshacer) y, si sale bien, la deja fijada."""
        r = self._pin_row(row_id)
        if r is None:
            return {"ok": False, "message": t("cl.not_found")}
        s = self._settings()
        if self._running(s.mods_path.parent):
            return {"ok": False, "reason": "minecraft", "message": t("apply.minecraft_open")}
        try:
            v = next((x for x in self._versions(r, s) if x["id"] == str(version_id)), None)
        except ApiError as exc:
            return {"ok": False, "message": t("scan.err_offline") if exc.kind == "offline" else t("cl.err_network")}
        if v is None or self._is_current(r, v) or not v["url"] or not v["file"]:
            return {"ok": False, "message": t("pin.err_version")}
        if self._bisect_active():
            return {"ok": False, "reason": "bisect", "message": t("bs.busy")}
        if not self._busy.acquire(blocking=False):
            return {"ok": False, "message": t("apply.busy")}
        res = replace(r, kind=UPDATE, status=ACTUALIZABLE, new_version=v["version"], new_channel=v["channel"],
                      new_file_name=v["file"], download_url=v["url"], new_sha1=v["sha1"], new_sha512=v["sha512"],
                      new_size=v["size"], new_date=v["date"], required_by=[])
        reason = r.pin_reason

        def pin_after(outcomes: list[Outcome]) -> None:
            o = outcomes[0] if outcomes else None
            if not (o and o.ok):
                return
            previous = self._save_pin(r, on=True, version=v["version"], reason=reason)
            if o.backup_path is not None:  # Deshacer la vuelta atrás también deshace la fijación
                data = read_changelog(o.backup_path.parent) or {}
                data["pin"] = {"key": pin_key(r), "previous": previous}
                write_changelog_json(o.backup_path.parent, data)

        self._run_async(lambda: self._apply([res], s, {id(res): ROLLBACK_ROW}, after=pin_after))
        return {"ok": True, "rows": [{"id": ROLLBACK_ROW, "s": "up", "name": r.name, "icon": r.icon_url,
                                      "from": r.current_version, "to": v["version"], "beta": v["channel"] != "release",
                                      "neededBy": []}]}

    # ------------------------------------------------------------------ diagnóstico

    def _game_dir(self, s: Settings) -> Path:
        return s.mods_path.parent  # la carpeta de la partida contiene mods, logs y crash-reports

    def diag_new(self) -> dict:
        """¿Hay un crash report nuevo (de los últimos 14 días) que aún no se ha visto?"""
        s = self._settings()
        try:
            crashes = [r for r in diag.list_reports(self._game_dir(s)) if r["kind"] != "log"]
        except OSError:
            crashes = []
        newest = max((r["mtime"] for r in crashes), default=0)
        fresh = newest > time.time() - DIAG_NEW_DAYS * 86400
        try:
            seen = float(s.diag_seen or 0)
        except (TypeError, ValueError):  # ajuste editado a mano
            seen = 0.0
        return {"new": bool(newest > seen and fresh),
                "date": datetime.fromtimestamp(newest).isoformat(timespec="minutes") if newest else None}

    @_never_hang
    def diag_reports(self) -> dict:
        """Informes de la partida del perfil activo (y los marca como vistos)."""
        s = self._settings()
        self._diag_reports = diag.list_reports(self._game_dir(s))
        newest = max((r["mtime"] for r in self._diag_reports if r["kind"] != "log"), default=0)
        if newest > (s.diag_seen or 0):
            s.diag_seen = newest
            save_settings(s, self._settings_file)
        return {"ok": True, "scanned": bool(self._results), "reports": [
            {"id": i, "name": r["name"], "kind": r["kind"],
             "date": datetime.fromtimestamp(r["mtime"]).isoformat(timespec="minutes")}
            for i, r in enumerate(self._diag_reports)]}

    def _diag_lookup(self, s: Settings):
        """modId de una dependencia que falta → lo que se instalaría (Modrinth por slug). Sin red: None."""
        cf, mr = self._clients(s)
        finder = DependencyFinder(cf, mr, loader=s.loader, game_version=s.minecraft_version, allow_beta=s.allow_beta)
        cache: dict = {}

        def lookup(modid: str):
            if modid not in cache:
                try:
                    found = finder.find(Dep(MR, modid))
                except ApiError:
                    found = None
                cache[modid] = found if found is not None and found.status == ACTUALIZABLE else None
            return cache[modid]
        return lookup

    @_never_hang
    def diag_run(self, report_id) -> dict:
        """Lee un informe y devuelve las tarjetas con sus acciones (todo en local salvo buscar lo que falta)."""
        try:
            rep_ = self._diag_reports[int(report_id)]
        except (IndexError, TypeError, ValueError):
            return {"ok": False, "message": t("dg.err_report")}
        s = self._settings()
        try:
            text = diag.read_text(rep_["path"])
        except OSError:
            return {"ok": False, "message": t("dg.err_report")}
        findings = diag.analyze(text, log=rep_["kind"] == "log")
        cards = diag.plan_cards(findings, self._results, lookup=self._diag_lookup(s), knowledge=load_knowledge())
        players = diag.players_in(text)  # para quitarlos también de los extractos y del resumen
        self._diag_cards[int(report_id)] = (rep_, cards, players)
        self._diag_actions = {}  # las acciones de un diagnóstico anterior ya no valen
        out_cards = []
        for c in cards:
            acts = []
            for a in c.actions:
                aid = f"a{len(self._diag_actions)}"
                self._diag_actions[aid] = a
                acts.append({"id": aid, "label": a.label, "primary": a.primary, "type": a.type})
            out_cards.append({"kind": c.kind, "kicker": c.kicker, "title": c.title, "why": c.why, "note": c.note,
                              "evidence": [diag.anonymize(e, players=players) for e in c.evidence], "actions": acts})
        load = {"missing", "version", "platform", "incompatible", "duplicate", "wrong_loader"}
        if not cards:
            head, deck = t("dg.h_none_found"), t("dg.d_none_found")
        elif rep_["kind"] == "fml" or all(c.kind in load for c in cards):
            head, deck = t("dg.h_load", count=len(cards)), t("dg.d_load")
        elif cards[0].kind in ("mixin", "suspect"):
            head, deck = t("dg.t_suspect", name=cards[0].subject), t("dg.d_game")
        else:
            head, deck = cards[0].title, t("dg.d_game")
        return {"ok": True, "head": head, "deck": deck, "name": rep_["name"], "cards": out_cards,
                "scanned": bool(self._results)}

    def diag_copy(self, report_id) -> dict:
        """Copia un resumen para pegarlo en el issue del mod, sin usuario de Windows ni de Minecraft."""
        found = self._diag_cards.get(int(report_id)) if str(report_id).lstrip("-").isdigit() else None
        if found is None:
            return {"ok": False, "message": t("dg.err_report")}
        rep_, cards, players = found
        s = self._settings()
        lines = [t("dg.sum_title", file=rep_["name"]),
                 t("dg.sum_env", minecraft=s.minecraft_version, loader=LOADER_LABEL.get(s.loader, s.loader)), ""]
        for c in cards:
            lines.append(f"- {c.title}: {c.why}")
            lines += [f"    {e}" for e in c.evidence]
        if not cards:
            lines.append(t("dg.h_none_found"))
        try:
            self._clipboard(diag.anonymize("\n".join(lines) + "\n", players=players))
        except (OSError, subprocess.SubprocessError):
            return {"ok": False, "message": t("ml.err_clipboard")}
        return {"ok": True}

    @_never_hang
    def diag_do(self, action_id: str) -> dict:
        """Ejecuta una acción del diagnóstico. Desactivar/activar al momento; instalar, cambiar y
        actualizar pasan por la pantalla de aplicar (con copia y Deshacer)."""
        a = self._diag_actions.get(str(action_id))
        if a is None:
            return {"ok": False, "message": t("dg.err_action")}
        index = {id(r): i for i, r in enumerate(self._rows)}
        if a.type in ("disable", "enable", "swap"):
            # Por nombre activo (x.jar): vale aunque el archivo se haya activado o desactivado después.
            wanted = {f[: -len(".disabled")] if f.lower().endswith(".disabled") else f for f in a.files}
            ids = [i for i, r in enumerate(self._rows) if r.mod is not None and r.mod.enabled_name in wanted]
            if not ids:
                return {"ok": False, "message": t("dg.err_action")}
        plan = None
        if a.type in ("install", "swap"):  # primero se prepara la instalación: si falla, no se toca nada
            cand = a.install
            plan = self.install_plan([{"source": cand.source, "id": cand.project_id, "name": cand.name}])
            if not plan.get("ok") or not plan.get("rows"):
                return plan if not plan.get("ok") else {"ok": False, "message": t("dg.err_action")}
        if a.type in ("disable", "enable", "swap"):
            # "with": quien dependa ahora de lo que se desactiva también se desactiva (se recalcula al pulsar).
            res = self.mods_set_enabled(ids, a.type == "enable", "with")
            if not res.get("ok"):
                if res.get("failed") and not res.get("message"):
                    res["message"] = " ".join(t("toggle.failed", name=f["name"], message=f["message"]) for f in res["failed"])
                self._install = []
                return res
            if a.type != "swap":
                return res
        if plan is not None:
            go = self.install_start()
            if not go.get("ok") and a.type == "swap":  # no se pudo empezar: se deshace la desactivación
                self.mods_set_enabled(ids, True, "only")
            return {**go, "rows": plan["rows"]} if go.get("ok") else go
        if a.type == "update":
            i = index.get(id(a.row))
            if i is None:
                return {"ok": False, "message": t("dg.err_action")}
            r = a.row
            if self._plan is not None and r in self._plan.blocked:
                return {"ok": False, "message": r.note or t("dg.err_action")}
            # Con sus dependencias nuevas, igual que al marcarlo en Mis mods.
            deps = [j for j, x in enumerate(self._rows) if x.kind == INSTALL and r.name in x.required_by]
            go = self.apply([i, *deps])
            rows = [{"id": j, "s": "dep" if self._rows[j].kind == INSTALL else "up", "name": self._rows[j].name,
                     "icon": self._rows[j].icon_url, "from": None if self._rows[j].kind == INSTALL else self._rows[j].current_version,
                     "to": self._rows[j].new_version, "beta": False, "neededBy": list(self._rows[j].required_by)}
                    for j in [i, *deps]]
            return {**go, "rows": rows} if go.get("ok") else go
        if a.type == "versions":
            i = index.get(id(a.row))
            return {"ok": True, "open_versions": i} if i is not None else {"ok": False, "message": t("dg.err_action")}
        return {"ok": False, "message": t("dg.err_action")}

    # ------------------------------------------------------------------ búsqueda por mitades

    def _bisect_file(self, s: Settings, profile_id: str | None = None) -> Path:
        return bis.state_file(self._cache(), profile_id or s.active_profile)

    def _bisect_sync_rows(self) -> None:
        """Tras renombrar en disco, las filas apuntan al archivo que hay ahora (x.jar o x.jar.disabled)."""
        mods_dir = self._settings().mods_path
        for r in self._results:
            if r.mod is None:
                continue
            on = mods_dir / r.mod.enabled_name
            off = on.with_name(on.name + bis.SUFFIX)
            target = on if on.exists() else off if off.exists() else None
            if target is not None:
                r.mod.path, r.mod.file_name = target, target.name

    def _bisect_abort(self, b, s: Settings, problems: list) -> dict:
        """Una vuelta que no se pudo preparar (archivo bloqueado o repetido): se deja todo como al
        empezar en vez de hacer una pregunta cuya respuesta sería engañosa."""
        bis.restore(s.mods_path, b)
        self._bisect_save(None)
        self._bisect_sync_rows()
        return {"ok": False, "message": t("bs.apply_failed", names=_join([b.display(j) for j in problems]))}

    def _bisect_load(self) -> bis.Bisect | None:
        s = self._settings()
        try:
            data = json.loads(self._bisect_file(s).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if os.path.normcase(str(data.get("mods_dir"))) != os.path.normcase(str(s.mods_path)):
            return None
        try:
            return bis.Bisect.from_dict(data["state"])
        except (KeyError, TypeError):
            return None

    def _bisect_save(self, b: bis.Bisect | None) -> None:
        s = self._settings()
        path = self._bisect_file(s)
        if b is None:
            path.unlink(missing_ok=True)
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"mods_dir": str(s.mods_path), "state": b.to_dict()}, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)

    def _bisect_view(self, b: bis.Bisect, problems: list | None = None) -> dict:
        rows = {r.mod.enabled_name: i for i, r in enumerate(self._rows) if r.mod is not None}
        return {"ok": True, "active": not b.done, "done": b.done, "round": b.round, "left": b.rounds_left,
                "suspects": len(b.suspects), "testing": [b.display(j) for j in b.testing],
                "result": [b.display(j) for j in b.result], "result_rows": [rows[j] for j in b.result if j in rows],
                "problems": [b.display(j) for j in problems or []]}

    def bisect_status(self) -> dict | None:
        """La búsqueda en curso del perfil activo (para retomarla), o None."""
        b = self._bisect_load()
        if b is None:
            return None
        self._bisect_sync_rows()  # al retomar, las filas pueden venir de una revisión hecha a mitad de vuelta
        return self._bisect_view(b)

    def bisect_start(self, excluded: list) -> dict:
        """Empieza: guarda qué está activo y desactiva la primera mitad. `excluded`: filas
        "seguro que no es este" (no son sospechosos, pero sí se respetan sus dependencias)."""
        if not self._results:
            return {"ok": False, "message": t("ex.need_scan")}
        s = self._settings()
        if self._running(s.mods_path.parent):
            return {"ok": False, "reason": "minecraft", "message": t("apply.minecraft_open")}
        if self._bisect_active():
            return {"ok": False, "reason": "bisect", "message": t("bs.busy")}
        try:
            skip = {self._rows[int(i)].mod.enabled_name for i in excluded or []
                    if 0 <= int(i) < len(self._rows) and self._rows[int(i)].mod is not None}
        except (TypeError, ValueError):
            return {"ok": False, "message": t("bs.none")}
        active = [r for r in self._results if r.mod is not None and not r.unreadable and not r.mod.disabled]
        needs = {r.mod.enabled_name: [x.mod.enabled_name for x in active if x is not r and _needs(_current_deps(r), x)]
                 for r in active}
        b = bis.Bisect.start([r.mod.enabled_name for r in active], needs, excluded=skip,
                             names={r.mod.enabled_name: r.name for r in active})
        if b.done:
            return {"ok": False, "message": t("bs.nothing")}
        if not self._busy.acquire(blocking=False):
            return {"ok": False, "message": t("apply.busy")}
        try:
            self._bisect_save(b)  # primero el estado: si algo se corta, se sabe qué restaurar
            problems = bis.apply_round(s.mods_path, b)
            if problems:
                return self._bisect_abort(b, s, problems)
            self._bisect_sync_rows()
            return self._bisect_view(b)
        finally:
            self._busy.release()

    def bisect_answer(self, fails: bool) -> dict:
        """"¿Sigue fallando?" Sí/No: siguiente vuelta, o resultado (y todo restaurado)."""
        b = self._bisect_load()
        if b is None:
            return {"ok": False, "message": t("bs.none")}
        s = self._settings()
        if self._running(s.mods_path.parent):
            return {"ok": False, "reason": "minecraft", "message": t("bs.close_minecraft")}
        if not self._busy.acquire(blocking=False):
            return {"ok": False, "message": t("apply.busy")}
        try:
            b.answer(bool(fails))
            if b.done:
                problems = bis.restore(s.mods_path, b)
                self._bisect_save(None)
            else:
                self._bisect_save(b)
                problems = bis.apply_round(s.mods_path, b)
                if problems:
                    return self._bisect_abort(b, s, problems)
            self._bisect_sync_rows()
            return self._bisect_view(b, problems)
        finally:
            self._busy.release()

    def bisect_cancel(self) -> dict:
        """Cancela y deja todo como al empezar."""
        b = self._bisect_load()
        if b is None:
            return {"ok": True, "problems": []}
        s = self._settings()
        if self._running(s.mods_path.parent):
            return {"ok": False, "reason": "minecraft", "message": t("bs.close_minecraft")}
        if not self._busy.acquire(blocking=False):
            return {"ok": False, "message": t("apply.busy")}
        try:
            problems = bis.restore(s.mods_path, b)
            self._bisect_save(None)
            self._bisect_sync_rows()
        finally:
            self._busy.release()
        return {"ok": not problems, "problems": [b.display(j) for j in problems],
                "message": t("bs.restore_failed", names=_join([b.display(j) for j in problems])) if problems else ""}

    # ------------------------------------------------------------------ pasar a otra versión de Minecraft

    def _folder_dialog(self) -> str | None:
        """Elegir una carpeta (sustituible en los tests)."""
        if self._window is None:
            return None
        import webview  # solo con ventana real

        picked = self._window.create_file_dialog(webview.FOLDER_DIALOG)
        if not picked:
            return None
        return picked[0] if isinstance(picked, (list, tuple)) else picked

    @_never_hang
    def migrate_check(self, target: str) -> dict:
        """¿Qué mods del perfil hay para `target` (mismo cargador)? Guarda el resultado para
        compararlo la próxima vez ("desde la última vez, N más listos")."""
        target = str(target or "").strip()
        s = self._settings()
        if not target or target == s.minecraft_version:
            return {"ok": False, "message": t("mg.err_target")}
        if not self._results:
            return {"ok": False, "message": t("ex.need_scan")}
        cf, mr = self._clients(s)
        try:
            out = migrate_mod.check(self._results, target=target, loader=s.loader, curseforge=cf, modrinth=mr)
        except ApiError as exc:
            return {"ok": False, "message": t("scan.err_offline") if exc.kind == "offline" else t("ex.err_network")}
        now = {"target": target, "ready": [i["key"] for i in out["ready"]], "date": datetime.now().isoformat(timespec="minutes")}
        delta = migrate_mod.compare_with_last(now, s.migration_last or None)
        last_date = (s.migration_last or {}).get("date") if delta is not None else None
        s.migration_last = now
        save_settings(s, self._settings_file)
        self._migration = out
        return {"ok": True, **{k: v for k, v in out.items() if k != "install"}, "delta": delta, "last_date": last_date,
                "installable": len(out["install"]), "loader": LOADER_LABEL.get(s.loader, s.loader),
                "current": s.minecraft_version}

    def migrate_create(self) -> dict:
        """Crea un perfil nuevo para la versión comprobada, en una carpeta nueva, y descarga en ella
        lo que está listo. El perfil actual no se toca (ni se cambia de perfil)."""
        m = self._migration
        if not m or not m.get("install"):
            return {"ok": False, "message": t("mg.err_nothing")}
        picked = self._folder_dialog()
        if not picked:
            return {"ok": False, "cancelled": True}
        game = Path(picked)
        mods_dir = game if game.name.lower() == "mods" else game / "mods"
        s = self._settings()
        if os.path.normcase(str(mods_dir.resolve())) == os.path.normcase(str(s.mods_path.resolve())):
            return {"ok": False, "message": t("mg.err_same_folder")}
        if mods_dir.is_dir() and any(p.is_file() and p.suffix.lower() in (".jar", ".disabled") for p in mods_dir.iterdir()):
            return {"ok": False, "message": t("mg.err_folder_used", path=str(mods_dir))}
        if not self._busy.acquire(blocking=False):
            return {"ok": False, "message": t("apply.busy")}
        try:
            mods_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self._busy.release()
            return {"ok": False, "message": t("mg.err_folder", error=friendly_error(exc))}
        name = t("mg.profile_name", name=self._active_name(s), version=m["target"])
        profiles.add(s, name=name, mods_dir=str(mods_dir), minecraft_version=m["target"], loader=s.loader)
        save_settings(s, self._settings_file)
        install = [replace(r, required_by=[]) for r in m["install"]]
        index = {id(r): MIGRATE_ROW + i for i, r in enumerate(install)}
        rows = [{"id": MIGRATE_ROW + i, "s": "dep", "name": r.name, "icon": r.icon_url, "from": None, "to": r.new_version,
                 "beta": False, "neededBy": []} for i, r in enumerate(install)]
        target_settings = replace(s, mods_dir=str(mods_dir), minecraft_version=m["target"])
        self._run_async(lambda: self._apply(install, target_settings, index))  # _apply suelta el bloqueo al acabar
        return {"ok": True, "rows": rows, "profile": name, "folder": str(mods_dir)}

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
        if self._bisect_active():
            return {"ok": False, "reason": "bisect", "message": t("bs.busy")}
        if target is None:
            return {"ok": False, "message": t("undo.none")}
        if self._running(s.mods_path.parent):
            return {"ok": False, "reason": "minecraft", "message": t("undo.minecraft_open")}
        if not self._busy.acquire(blocking=False):
            return {"ok": False, "message": t("apply.busy")}
        try:
            pin = (read_changelog(target) or {}).get("pin")
            r = undo_backup(target)
            if pin and r.restored:  # era una vuelta atrás: la fijación vuelve a como estaba
                self._restore_pin(pin)
        finally:
            self._busy.release()
        self._plan = None
        self._results = []  # la carpeta ha cambiado: lo revisado ya no vale
        return {"ok": not r.errors, "restored": r.restored, "removed": r.removed, "errors": r.errors,
                "message": t("undo.done", count=r.restored, removed=r.removed) if r.restored
                else t("undo.done_removed", count=r.removed)}

    # ------------------------------------------------------------------ activar y desactivar

    @_never_hang
    def mods_set_enabled(self, ids: list, enabled: bool, dependents: str = "ask") -> dict:
        """Activa o desactiva mods renombrando `x.jar` <-> `x.jar.disabled` (nunca borra nada).

        Al desactivar algo que necesitan mods activos: con `dependents="ask"` no cambia nada y
        devuelve el aviso; con "with" desactiva también esos; con "only", solo lo elegido. Al
        activar, activa también las librerías desactivadas que hagan falta. No crea copia de
        seguridad: se deshace volviendo a activar o desactivar.
        """
        s = self._settings()
        rows = {id(r): i for i, r in enumerate(self._rows)}
        picked = [self._rows[i] for i in sorted({int(i) for i in ids or []}) if 0 <= i < len(self._rows)]
        targets = [r for r in picked if r.mod is not None and not r.unreadable and r.mod.disabled == enabled]
        if self._bisect_active():
            return {"ok": False, "reason": "bisect", "message": t("bs.busy")}
        if not targets:
            return {"ok": True, "rows": [], "also": [], "failed": []}
        if any(r.mod.path.parent.resolve() != s.mods_path.resolve() for r in targets):
            return {"ok": False, "message": t("apply.no_scan")}  # revisión de otra carpeta (otro perfil)
        if self._running(s.mods_path.parent):
            return {"ok": False, "reason": "minecraft", "message": t("apply.minecraft_open")}
        also: list[Resolution] = []
        if enabled:
            also = required_disabled(self._results, targets)
        else:
            needers = dependents_of(self._results, targets)
            if needers and dependents == "ask":
                names = sorted((r.name for r in needers), key=str.lower)
                return {"ok": False, "reason": "dependents", "names": names,
                        "message": t("toggle.dependents", count=len(names), name=_join([r.name for r in targets]),
                                     names=_join(names))}
            if dependents == "with":
                also = needers
        if not self._busy.acquire(blocking=False):
            return {"ok": False, "message": t("apply.busy")}
        try:
            # Solo se renombra: sin copia de seguridad (no hay nada que guardar) y sin contar para el
            # límite de copias. Deshacer es volver a pulsar el interruptor.
            chosen = [replace(r, kind=ENABLE if enabled else DISABLE) for r in targets + also]
            outcomes = [toggle_one(r) for r in chosen]
            done = []
            for o, original in zip(outcomes, targets + also):
                if o.ok and o.new_path is not None:  # la fila sigue valiendo: solo cambia el nombre
                    original.mod.path, original.mod.file_name = o.new_path, o.new_path.name
                    done.append(original)
        finally:
            self._busy.release()
        failed = [{"name": o.resolution.name, "message": o.message} for o in outcomes if not o.ok]
        return {"ok": not failed, "rows": [{"id": rows[id(r)], "off": r.mod.disabled} for r in done if id(r) in rows],
                "also": [r.name for r in also if r in done], "failed": failed}

    def _restore_pin(self, pin: dict) -> None:
        s = self._settings()
        pins = dict(s.pins or {})
        pins.pop(str(pin.get("key")), None)
        pins.update(pin.get("previous") or {})
        s.pins = pins
        save_settings(s, self._settings_file)

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

    def diag_open_folder(self) -> bool:
        """Abre la carpeta crash-reports de la partida del perfil activo."""
        path = self._game_dir(self._settings()) / "crash-reports"
        if not path.is_dir() or os.name != "nt":
            return False
        subprocess.Popen(["explorer.exe", str(path.resolve())], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return True
