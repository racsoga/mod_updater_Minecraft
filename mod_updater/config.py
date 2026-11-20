"""Configuración: `.env` (secretos) + `config.toml` (opciones) + argumentos CLI."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_USER_AGENT = "racsoga/mod-updater/0.1 (github.com/racsoga/mod-updater)"


def default_mods_dir() -> Path:
    appdata = os.environ.get("APPDATA", "")
    return Path(appdata) / ".minecraft" / "mods"


@dataclass
class Config:
    mods_dir: Path
    minecraft_version: str = "1.21.1"
    loader: str = "neoforge"
    user_agent: str = DEFAULT_USER_AGENT
    cf_api_key: str | None = None
    cache_dir: Path = PROJECT_ROOT / ".cache"

    @property
    def scan_cache(self) -> Path:
        return self.cache_dir / "scan_cache.json"


def load_config(config_path: Path | None = None) -> Config:
    load_dotenv(PROJECT_ROOT / ".env")

    path = config_path or PROJECT_ROOT / "config.toml"
    data: dict = {}
    if path.exists():
        with path.open("rb") as f:
            data = tomllib.load(f)

    mods_dir = data.get("mods_dir")
    return Config(
        mods_dir=Path(os.path.expandvars(mods_dir)) if mods_dir else default_mods_dir(),
        minecraft_version=data.get("minecraft_version", "1.21.1"),
        loader=data.get("loader", "neoforge"),
        user_agent=data.get("user_agent", DEFAULT_USER_AGENT),
        cf_api_key=os.environ.get("CF_API_KEY") or None,
    )
