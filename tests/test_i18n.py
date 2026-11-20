"""Traducciones: archivos completos y coherentes, claves usadas existentes, idioma por defecto."""

import json
import re
from pathlib import Path

import pytest

from mod_updater import i18n
from mod_updater.i18n import t

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "mod_updater"
LOCALES = {code: json.loads((i18n.LOCALES_DIR / f"{code}.json").read_text(encoding="utf-8")) for code in i18n.SUPPORTED}
PLACEHOLDER = re.compile(r"\{(\w+)\}")
STATUS_CODES = ("up", "ok", "manual", "missing", "dep")


def test_all_languages_have_the_same_keys():
    keys = {code: set(table) for code, table in LOCALES.items()}
    for code in i18n.SUPPORTED:
        assert keys[code] == keys["es"], f"{code}: faltan {keys['es'] - keys[code]}, sobran {keys[code] - keys['es']}"


def test_placeholders_match_across_languages():
    for key, text in LOCALES["es"].items():
        expected = set(PLACEHOLDER.findall(text))
        for code in ("en", "ca"):
            assert set(PLACEHOLDER.findall(LOCALES[code][key])) == expected, f"{code}:{key}"


def _used_keys() -> set[str]:
    """Claves literales usadas en Python (t("…")), JS (t("…")) y HTML (data-i18n*="…")."""
    used = set()
    for path in list(PKG.rglob("*.py")) + [PKG / "gui" / "web" / "app.js"]:
        # Las claves reales siempre llevan punto ("ui.close"); así se ignoran ejemplos en comentarios.
        used |= set(re.findall(r"""\bt\(\s*["']([\w]+\.[\w.]+)["']""", path.read_text(encoding="utf-8")))
    html = (PKG / "gui" / "web" / "index.html").read_text(encoding="utf-8")
    used |= set(re.findall(r'data-i18n(?:-[\w-]+)?="([\w.]+)"', html))
    # Claves construidas dinámicamente.
    used |= {f"status.{c}" for c in STATUS_CODES} | {f"status_help.{c}" for c in STATUS_CODES}
    js = (PKG / "gui" / "web" / "app.js").read_text(encoding="utf-8")
    used |= set(re.findall(r'(?:title|label): "(ui\.[\w.]+)"', js))
    return used


def test_every_used_key_exists_in_spanish():
    table = LOCALES["es"]
    missing = []
    for key in sorted(_used_keys()):
        if key in table or (f"{key}_one" in table and f"{key}_other" in table):
            continue
        missing.append(key)
    assert not missing, f"Claves sin traducción: {missing}"


def test_plural_and_params():
    i18n.set_language("es")
    assert t("ui.selected", count=1, selected=1) == "1 de 1 cambio seleccionado"
    assert t("ui.selected", count=5, selected=3) == "3 de 5 cambios seleccionados"
    i18n.set_language("en")
    assert t("ui.selected", count=1, selected=1) == "1 of 1 change selected"
    i18n.set_language("ca")
    assert t("ui.go_update", count=2) == "Actualitzar 2 mods"


def test_unknown_key_and_missing_param_do_not_crash():
    assert t("no.existe") == "no.existe"
    assert "{names}" in t("ui.needed_by")


@pytest.mark.real_language
@pytest.mark.parametrize("langid,expected", [(0x0C0A, "es"), (0x080A, "es"), (0x0409, "en"), (0x0809, "en"),
                                             (0x0403, "ca"), (0x040C, "en"), (0x0407, "en")])
def test_windows_ui_language(monkeypatch, langid, expected):
    import ctypes

    class K:
        @staticmethod
        def GetUserDefaultUILanguage():
            return langid

    monkeypatch.setattr(i18n.os, "name", "nt")
    monkeypatch.setattr(ctypes, "windll", type("W", (), {"kernel32": K}), raising=False)
    assert i18n.system_language() == expected


@pytest.mark.real_language
def test_resolve_preference(monkeypatch):
    monkeypatch.setattr(i18n, "system_language", lambda: "ca")
    assert i18n.resolve("auto") == "ca"
    assert i18n.resolve(None) == "ca"
    assert i18n.resolve("xx") == "ca"
    assert i18n.resolve("en") == "en"


def test_cli_help_uses_language():
    from mod_updater.main import build_parser

    i18n.set_language("en")
    assert "download and apply" in build_parser().format_help()
    i18n.set_language("es")
    assert "descargar y aplicar" in build_parser().format_help()
