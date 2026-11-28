"""Ajustes de la app de escritorio, en `%APPDATA%\\mod_updater\\settings.json`.

La CLI sigue usando `config.toml` + `.env`; la app guarda aquí lo que el
usuario elige en la pantalla de configuración. La API key NO va aquí: va al
Administrador de credenciales de Windows (ver `credentials.py`).
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from .config import default_mods_dir


def app_dir() -> Path:
    return Path(os.environ.get("APPDATA") or Path.home()) / "mod_updater"


@dataclass
class Settings:
    mods_dir: str = ""
    minecraft_version: str = "1.21.1"
    loader: str = "neoforge"
    allow_beta: bool = False
    backups_to_keep: int = 1
    setup_done: bool = False  # ya pasó por la pantalla de bienvenida
    use_curseforge: bool = True  # False = "continuar sin key (solo Modrinth)"
    language: str = "auto"  # "auto" = idioma de la interfaz de Windows; o "es", "en"
    check_updates: bool = True  # avisar de nuevas versiones de la app (como mucho una vez al día)
    answers: dict = field(default_factory=dict)  # cuestionario de Sugerencias (por perfil)
    pins: dict = field(default_factory=dict)  # mods fijados (por perfil): {"fuente:proyecto": {name, version, reason}}
    profiles: list = field(default_factory=list)  # [{id, name, mods_dir, minecraft_version, loader, ...}]
    active_profile: str = ""  # id del perfil activo (sus campos se reflejan arriba)

    @property
    def mods_path(self) -> Path:
        return Path(self.mods_dir) if self.mods_dir else default_mods_dir()


def settings_path() -> Path:
    return app_dir() / "settings.json"


def load_settings(path: Path | None = None) -> Settings:
    path = path or settings_path()
    s = Settings(mods_dir=str(default_mods_dir()))
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return s
    known = {f.name for f in fields(Settings)}
    for k, v in (data.items() if isinstance(data, dict) else []):
        if k in known:
            setattr(s, k, v)
    if not isinstance(s.profiles, list):
        s.profiles = []
    # Perfiles mal formados (editados a mano): se descartan en vez de impedir que la app arranque.
    s.profiles = [p for p in s.profiles if isinstance(p, dict) and isinstance(p.get("id"), str) and p["id"]]
    from . import profiles  # aquí para no crear un import circular
    profiles.ensure(s)
    profiles.apply_active(s)
    s.backups_to_keep = max(1, int(s.backups_to_keep or 1))
    return s


def save_settings(s: Settings, path: Path | None = None) -> None:
    path = path or settings_path()
    from . import profiles
    profiles.ensure(s)
    profiles.sync_active(s)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(asdict(s), ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
