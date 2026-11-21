"""Base de conocimiento propia (JSON versionados en esta carpeta, con tests): correcciones de
categoría, mods que hacen lo mismo, incompatibilidades conocidas, mods recomendados por estilo
de partida y mods que suben mucho la dificultad."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _read(name: str) -> dict:
    try:
        return json.loads((HERE / name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


@lru_cache(maxsize=1)
def load_knowledge() -> dict:
    return {
        "solapamientos": _read("solapamientos.json").get("grupos") or [],
        "incompatibilidades": _read("incompatibilidades.json").get("pares") or [],
        "esenciales": _read("esenciales.json").get("estilos") or {},
        "duros": _read("duros.json").get("mods") or [],
    }
