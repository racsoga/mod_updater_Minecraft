"""Hito 4 (v4): diagnóstico de crasheos. Los informes de ejemplo están en tests/fixtures/crash/
(anonimizados a partir de informes reales o inventados)."""

import zipfile
from pathlib import Path

import pytest

from mod_updater import i18n
from mod_updater.scanner import read_metadata

FIX = Path(__file__).parent / "fixtures" / "crash"


def setup_module():
    i18n.set_language("es")


def jar_with(tmp_path, toml: str, classes=()):
    p = tmp_path / "m.jar"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("META-INF/neoforge.mods.toml", toml)
        for c in classes:
            z.writestr(c, b"")
    return zipfile.ZipFile(p)


SODIUM_TOML = '''modLoader="javafml"
loaderVersion="[1,)"
[[mods]]
modId="sodium"
version="0.8.13"
[[dependencies.sodium]]
modId="minecraft"
type="required"
versionRange="1.21.1"
[[dependencies.sodium]]
modId="embeddium"
type="incompatible"
reason="Sodium and Embeddium cannot be used together. Please remove Embeddium."
versionRange="[0.0.1,)"
'''


def test_scanner_reads_incompatible_mods_and_packages(tmp_path):
    classes = ["net/caffeinemc/mods/sodium/client/SodiumClientMod.class",
               "net/caffeinemc/mods/sodium/client/gui/Options.class",
               "net/caffeinemc/mods/sodium/mixin/Foo.class", "assets/sodium/lang/en_us.json"]
    meta = read_metadata(jar_with(tmp_path, SODIUM_TOML, classes))
    assert meta["incompatible"] == ["embeddium"]
    assert meta["packages"] == ["net.caffeinemc.mods.sodium"]


def test_packages_are_capped_and_skip_the_default_package(tmp_path):
    classes = ["Top.class"] + [f"com/a{i}/x/Y.class" for i in range(60)]
    meta = read_metadata(jar_with(tmp_path, SODIUM_TOML, classes))
    assert len(meta["packages"]) == 40 and "" not in meta["packages"]
