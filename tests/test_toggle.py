"""Hito 2 (v4): activar y desactivar mods (`x.jar` <-> `x.jar.disabled`)."""

import os
import zipfile
from pathlib import Path

import pytest

from mod_updater import i18n
from mod_updater.scanner import is_mod_file, scan_folder


def setup_module():
    i18n.set_language("es")


def make_jar(path: Path, mod_id: str) -> Path:
    toml = f'modLoader="javafml"\nloaderVersion="[1,)"\n[[mods]]\nmodId="{mod_id}"\nversion="1.0"\n'
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("META-INF/neoforge.mods.toml", toml)
    return path


@pytest.mark.parametrize("name,ok", [
    ("a.jar", True), ("A.JAR", True), ("a.jar.disabled", True), ("A.JAR.DISABLED", True),
    ("a.jar.Disabled", True), ("a.jar.disabled.disabled", False), ("a.zip.disabled", False),
    ("a.disabled", False), ("a.jar.bak", False), ("a.txt", False),
])
def test_is_mod_file(name, ok):
    assert is_mod_file(name) is ok


def test_scan_lists_disabled_jars(tmp_path):
    make_jar(tmp_path / "on.jar", "on")
    make_jar(tmp_path / "off.jar.disabled", "off")
    make_jar(tmp_path / "weird.JAR.DISABLED", "weird")
    make_jar(tmp_path / "double.jar.disabled.disabled", "double")
    mods = {m.file_name: m for m in scan_folder(tmp_path)}
    assert sorted(mods) == ["off.jar.disabled", "on.jar", "weird.JAR.DISABLED"]
    assert not mods["on.jar"].disabled and mods["off.jar.disabled"].disabled and mods["weird.JAR.DISABLED"].disabled
    assert mods["off.jar.disabled"].mod_id == "off"
    assert mods["off.jar.disabled"].enabled_name == "off.jar" and mods["on.jar"].enabled_name == "on.jar"
    assert mods["weird.JAR.DISABLED"].enabled_name == "weird.JAR"


def test_hash_does_not_change_when_disabled(tmp_path):
    jar = make_jar(tmp_path / "m.jar", "m")
    before = scan_folder(tmp_path)[0]
    os.replace(jar, tmp_path / "m.jar.disabled")
    after = scan_folder(tmp_path)[0]
    assert (before.sha1, before.cf_fingerprint) == (after.sha1, after.cf_fingerprint)


def test_cache_is_reused_after_renaming(tmp_path, monkeypatch):
    from mod_updater import scanner
    mods, cache = tmp_path / "mods", tmp_path / "cache.json"
    mods.mkdir()
    jar = make_jar(mods / "m.jar", "m")
    scan_folder(mods, cache_path=cache)
    os.replace(jar, mods / "m.jar.disabled")  # os.replace conserva la fecha de modificación
    monkeypatch.setattr(scanner, "scan_file", lambda p: pytest.fail("no debería volver a calcular hashes"))
    assert scan_folder(mods, cache_path=cache)[0].disabled
