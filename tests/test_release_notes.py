"""Las notas de la Release salen de CHANGELOG.md y la versión del código coincide con el changelog."""

import importlib.util
from pathlib import Path

import mod_updater

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("release_notes", ROOT / "packaging" / "release_notes.py")
release_notes = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release_notes)

CHANGELOG = """# Registro

## [0.3.0] - 2026-12-01
### Añadido
- Algo nuevo.

## [0.2.0] - 2026-11-21
### Añadido
- Ventana.
"""


def test_extracts_only_that_version():
    body = release_notes.section(CHANGELOG, "0.2.0")
    assert body == "### Añadido\n- Ventana."
    assert "Algo nuevo" in release_notes.section(CHANGELOG, "0.3.0")
    assert "Ventana" not in release_notes.section(CHANGELOG, "0.3.0")


def test_missing_version_returns_none():
    assert release_notes.section(CHANGELOG, "9.9.9") is None


def test_current_version_has_changelog_section():
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert release_notes.section(changelog, mod_updater.__version__), "Falta la sección del changelog de la versión actual"


def test_main_output_includes_footer(tmp_path, capsys):
    sha = tmp_path / "x.sha256"
    sha.write_text("abc123  ModUpdater.exe", encoding="ascii")
    assert release_notes.main(["x", f"v{mod_updater.__version__}", str(sha)]) == 0
    out = capsys.readouterr().out
    assert "abc123  ModUpdater.exe" in out and "Ejecutar de todas formas" in out
