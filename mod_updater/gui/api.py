"""Puente entre la interfaz (JS) y la lógica (Python).

pywebview expone al JS los métodos públicos de `Api` como
`window.pywebview.api.<método>()`. Python avisa al JS con
`window.onBackend(evento, datos)` (progreso, resultados, errores).

Reglas:
- La API key nunca sale de Python: el JS solo recibe `key_hint` (••••1a2b).
- El escaneo y las consultas van en un hilo aparte para no congelar la ventana.
- Nada aquí modifica la carpeta de mods (eso es el paso 5, `apply`).
"""

from __future__ import annotations

import json
import os
import threading
import webbrowser
from dataclasses import asdict
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

from .. import credentials
from ..config import DEFAULT_USER_AGENT, default_mods_dir
from ..curseforge import LOADER_TYPES, CurseForgeAuthError, CurseForgeClient
from ..deps import DependencyFinder, DepPlan, plan_with_dependencies
from ..downloader import updatable
from ..modrinth import ModrinthClient
from ..net import ApiError
from ..resolver import (
    ACTUALIZABLE,
    AL_DIA,
    CF,
    DESCARGA_MANUAL,
    INSTALL,
    NO_ENCONTRADO,
    Resolution,
    resolve_all,
)
from ..scanner import peek_folder, scan_folder
from ..settings import Settings, app_dir, load_settings, save_settings

LOADER_LABEL = {"neoforge": "NeoForge", "forge": "Forge", "fabric": "Fabric", "quilt": "Quilt"}
SOURCE_LABEL = {"curseforge": "CurseForge", "modrinth": "Modrinth"}
STATUS_CODE = {ACTUALIZABLE: "up", AL_DIA: "ok", DESCARGA_MANUAL: "manual", NO_ENCONTRADO: "missing"}


def serialize(results: list[Resolution], plan: DepPlan) -> dict:
    """Convierte la revisión en datos para la pantalla de Resultados (sin secretos)."""
    in_plan = {id(r) for r in plan.items}
    added = {id(r) for r in plan.added_updates}
    rows = []
    for r in plan.installs + results:
        if r.kind == INSTALL:
            s = "dep"
        else:
            s = STATUS_CODE.get(r.status, "missing")
        sub = ""
        if s == "up" and id(r) not in in_plan:
            # Actualizable pero fuera del plan: hoy solo pasa con duplicados.
            s, sub = "manual", "Está duplicado en la carpeta: deja solo uno y vuelve a revisar"
        elif s == "manual":
            sub = r.note or "El autor no permite descargarlo desde aquí"
        elif s == "missing":
            file_name = r.mod.file_name if r.mod else ""
            sub = file_name if file_name != r.name else "No aparece en CurseForge ni en Modrinth"
        elif id(r) in added:
            sub = f"La necesita {', '.join(r.required_by)}"
        channel = r.new_channel if s in ("up", "dep") else r.current_channel
        rows.append({
            "id": len(rows),
            "s": s,
            "name": r.name,
            "icon": r.icon_url,
            "from": r.current_version if r.kind != INSTALL else None,
            "to": r.new_version,
            "beta": channel in ("beta", "alpha"),
            "src": SOURCE_LABEL.get(r.source or "", ""),
            "url": r.project_url,
            "sub": sub,
            "neededBy": list(r.required_by) if r.kind == INSTALL else [],
            "checked": id(r) in in_plan,
        })
    return {"rows": rows, "broken": list(plan.broken), "ignored": list(plan.ignored)}


class Api:
    def __init__(
        self,
        settings_file: Path | None = None,
        *,
        get_key: Callable = credentials.get_key,
        cf_factory: Callable = CurseForgeClient,
        mr_factory: Callable = ModrinthClient,
        run_async: Callable | None = None,
    ):
        self._settings_file = settings_file
        self._get_key = get_key
        self._cf_factory = cf_factory
        self._mr_factory = mr_factory
        self._run_async = run_async or (lambda fn: threading.Thread(target=fn, daemon=True).start())
        self._window = None
        self._busy = threading.Lock()
        self._results: list[Resolution] = []
        self._plan: DepPlan | None = None

    # ------------------------------------------------------------------ infraestructura

    def _attach(self, window) -> None:
        self._window = window

    def _emit(self, event: str, payload: dict) -> None:
        if self._window is not None:
            self._window.evaluate_js(f"window.onBackend({json.dumps(event)}, {json.dumps(payload, ensure_ascii=False)})")

    def _settings(self) -> Settings:
        return load_settings(self._settings_file)

    # ------------------------------------------------------------------ configuración

    def get_state(self) -> dict:
        s = self._settings()
        key, source = self._get_key()
        return {
            "settings": asdict(s) | {"mods_dir": str(s.mods_path)},
            "default_mods_dir": str(default_mods_dir()),
            "folder": peek_folder(s.mods_path),
            "has_key": bool(key),
            "key_hint": credentials.hint(key),
            "key_source": source,
            "loaders": [{"value": k, "label": LOADER_LABEL.get(k, k)} for k in LOADER_TYPES],
        }

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
        """Prueba la key escrita (o la guardada si viene vacía). Nunca la devuelve."""
        key = (key or "").strip() or (self._get_key()[0] or "")
        if not key:
            return {"ok": False, "message": "Pega primero tu key de CurseForge."}
        try:
            self._cf_factory(key).check()
        except CurseForgeAuthError:
            return {"ok": False, "message": "CurseForge no acepta esta key. Comprueba que la has copiado entera."}
        except (ApiError, OSError):
            return {"ok": False, "message": "No se pudo conectar con CurseForge. Comprueba tu conexión a internet."}
        return {"ok": True, "message": "Key válida. CurseForge responde."}

    def save_setup(self, data: dict) -> dict:
        """Guarda la pantalla de bienvenida / ajustes. Devuelve {ok, message?, state?}."""
        s = self._settings()
        mods_dir = Path(str(data.get("mods_dir") or s.mods_path))
        if not mods_dir.is_dir():
            return {"ok": False, "field": "mods_dir", "message": f"No existe la carpeta {mods_dir}. Elige la carpeta mods de tu Minecraft."}
        loader = data.get("loader") or s.loader
        if loader not in LOADER_TYPES:
            return {"ok": False, "field": "loader", "message": "Elige un loader de la lista."}
        version = str(data.get("minecraft_version") or s.minecraft_version).strip()
        if not version or not version[0].isdigit():
            return {"ok": False, "field": "minecraft_version", "message": "Escribe la versión de Minecraft, por ejemplo 1.21.1."}

        key = str(data.get("key") or "").strip()
        if key:
            credentials.set_key(key)
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
        credentials.delete_key()
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
            self._emit("error", {"message": f"{exc}. Revisa la carpeta en Ajustes."})
        except ApiError:
            self._emit("error", {"message": "No se pudo conectar con CurseForge ni con Modrinth. Comprueba tu conexión e inténtalo otra vez."})
        except Exception as exc:  # noqa: BLE001 - la ventana no debe quedarse colgada
            self._emit("error", {"message": f"Algo salió mal durante la revisión: {type(exc).__name__}."})
        finally:
            self._busy.release()

    def _do_scan(self) -> dict:
        s = self._settings()
        notices: list[str] = []

        def progress(phase: str, label: str, done: int = 0, total: int = 0) -> None:
            self._emit("progress", {"phase": phase, "label": label, "done": done, "total": total})

        progress("read", "Leyendo mods")
        mods = scan_folder(
            s.mods_path,
            cache_path=app_dir() / "cache" / "scan_cache.json",
            on_item=lambda i, n, p: progress("read", f"Leyendo mods {i}/{n}", i, n),
        )

        key = self._get_key()[0] if s.use_curseforge else None
        cf = self._cf_factory(key) if key else None
        mr = self._mr_factory(DEFAULT_USER_AGENT)
        if cf is None:
            notices.append("Sin key de CurseForge: solo se ha consultado Modrinth, así que algunos mods pueden salir como No encontrado.")
        opts = dict(loader=s.loader, game_version=s.minecraft_version, allow_beta=s.allow_beta)
        phase = {"Consultando CurseForge": "cf", "Consultando Modrinth": "mr"}
        on_phase = lambda text: progress(phase.get(text, "mr"), text)  # noqa: E731
        try:
            results = resolve_all(mods, curseforge=cf, modrinth=mr, on_phase=on_phase, **opts)
        except CurseForgeAuthError:
            notices.append("CurseForge no acepta tu key: solo se ha consultado Modrinth. Cámbiala en Ajustes.")
            cf = None
            results = resolve_all(mods, curseforge=None, modrinth=mr, on_phase=on_phase, **opts)

        progress("deps", "Comprobando dependencias")
        selected, _ = updatable(results)
        plan = plan_with_dependencies(results, selected, DependencyFinder(cf, mr, **opts))
        self._results, self._plan = results, plan

        data = serialize(results, plan)
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
        # Paso 5 del plan: descarga con progreso, pantalla final y Deshacer.
        return {"ok": False, "message": "La actualización desde la ventana llega en la siguiente versión. Mientras tanto, usa actualizar.bat."}

    def open_url(self, url: str) -> bool:
        if urlparse(url or "").scheme not in ("http", "https"):
            return False
        webbrowser.open(url)
        return True

    def open_mods_folder(self) -> bool:
        path = self._settings().mods_path
        if path.is_dir() and os.name == "nt":
            os.startfile(path)  # noqa: S606 - abre el Explorador en la carpeta
            return True
        return False

    def quit(self) -> None:
        if self._window is not None:
            self._window.destroy()
