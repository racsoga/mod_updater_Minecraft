"""Traducciones: `mod_updater/locales/<idioma>.json`, compartidas por Python y la interfaz.

- Idiomas: es, en. Si una clave falta en un idioma se usa la de inglés.
- "auto" = idioma de la interfaz de Windows (no la región): español para cualquier variante
  de español y también para catalán, gallego y euskera; inglés para cualquier otro.
- Plurales: `t("clave", count=n)` busca `clave_one` (n == 1) o `clave_other`.
- Parámetros con llaves: `"Leyendo mods {done}/{total}"`.
"""

from __future__ import annotations

import json
import locale
import os
from functools import lru_cache
from pathlib import Path

LOCALES_DIR = Path(__file__).resolve().parent / "locales"
SUPPORTED = ("es", "en")
FALLBACK = "en"
# Idioma principal de un LANGID de Windows -> idioma de la app ("Language Identifier Constants").
# Español: cualquier variante de español (0x0A) y catalán (0x03), gallego (0x56) y euskera (0x2D).
_WINDOWS_PRIMARY = {0x0A: "es", 0x03: "es", 0x56: "es", 0x2D: "es", 0x09: "en"}
# Lo mismo para códigos ISO (fuera de Windows): es, ca, gl, eu -> español.
_ISO_TO_APP = {"es": "es", "ca": "es", "gl": "es", "eu": "es", "en": "en"}

_current = FALLBACK


def system_language() -> str:
    """Idioma de la interfaz del sistema (en Windows, GetUserDefaultUILanguage)."""
    if os.name == "nt":
        try:
            import ctypes

            langid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            return _WINDOWS_PRIMARY.get(langid & 0x3FF, FALLBACK)
        except (AttributeError, OSError):
            return FALLBACK
    code = (os.environ.get("LANGUAGE") or os.environ.get("LANG") or (locale.getlocale()[0] or "")).lower()
    return _ISO_TO_APP.get(code[:2], FALLBACK)


def resolve(preference: str | None) -> str:
    """'auto' / None / desconocido -> idioma del sistema; 'es'/'en' -> tal cual."""
    return preference if preference in SUPPORTED else system_language()


def set_language(code: str | None) -> str:
    global _current
    _current = resolve(code)
    return _current


def get_language() -> str:
    return _current


@lru_cache(maxsize=None)
def _load(code: str) -> dict:
    try:
        return json.loads((LOCALES_DIR / f"{code}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def strings(code: str | None = None) -> dict:
    """Todas las cadenas de un idioma, completadas con inglés donde falten."""
    code = resolve(code) if code else _current
    return {**_load(FALLBACK), **_load(code)}


def t(key: str, count: int | None = None, **params) -> str:
    table = strings()
    if count is not None:
        params["count"] = count
        plural_key = f"{key}_one" if count == 1 else f"{key}_other"
        if plural_key in table:
            key = plural_key
    text = table.get(key, key)
    try:
        return text.format(**params) if params else text
    except (KeyError, IndexError, ValueError):
        return text
