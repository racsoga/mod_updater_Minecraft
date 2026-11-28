"""Hito 8 (v4): copia y exportación de la configuración (`config` y `defaultconfigs`)."""

import json
import zipfile
from pathlib import Path

import pytest

from mod_updater import i18n
from mod_updater.configpack import (
    MAX_FILE,
    ConfigPackError,
    backup_config,
    export_zip,
    import_config,
    preview_import,
    read_zip,
)

LIST = {"formato": 1, "app": "Mod Updater", "minecraft": "1.21.1", "cargador": "neoforge",
        "mods": [{"nombre": "Create", "fuente": "curseforge", "proyecto": 328085, "archivo": 1, "version": "6.0"}]}


def setup_module():
    i18n.set_language("es")


def game(tmp_path, name="juego"):
    g = tmp_path / name
    (g / "config" / "create").mkdir(parents=True)
    (g / "config" / "create" / "client.toml").write_text("zoom = 2\n", encoding="utf-8")
    (g / "config" / "jei.toml").write_text("x = 1\n", encoding="utf-8")
    (g / "defaultconfigs").mkdir()
    (g / "defaultconfigs" / "server.toml").write_text("s = 1\n", encoding="utf-8")
    (g / "mods").mkdir()
    return g


# ---------------------------------------------------------------- copias de seguridad

def test_backup_only_when_config_changed(tmp_path):
    g = game(tmp_path)
    b1, b2, b3 = (tmp_path / "b1", tmp_path / "b2", tmp_path / "b3")
    for b in (b1, b2, b3):
        b.mkdir()
    state = tmp_path / "estado.json"
    assert backup_config(g, b1, state) is True and (b1 / "config.zip").exists()
    assert backup_config(g, b2, state) is False and not (b2 / "config.zip").exists()  # no ha cambiado
    (g / "config" / "jei.toml").write_text("x = 2\n", encoding="utf-8")
    assert backup_config(g, b3, state) is True
    names = zipfile.ZipFile(b3 / "config.zip").namelist()
    assert sorted(names) == ["config/create/client.toml", "config/jei.toml", "defaultconfigs/server.toml"]


def test_backup_without_config_folder(tmp_path):
    g = tmp_path / "vacio"
    g.mkdir()
    b = tmp_path / "b"
    b.mkdir()
    assert backup_config(g, b, tmp_path / "e.json") is False


# ---------------------------------------------------------------- exportar

def test_export_zip_round_trip_relative_paths_and_big_files_out(tmp_path):
    g = game(tmp_path)
    (g / "config" / "enorme.dat").write_bytes(b"0" * (MAX_FILE + 1))
    out = tmp_path / "Principal.zip"
    excluded = export_zip(out, LIST, g)
    assert excluded == ["config/enorme.dat"]
    z = zipfile.ZipFile(out)
    names = sorted(z.namelist())
    assert names == ["config/create/client.toml", "config/jei.toml", "defaultconfigs/server.toml", "lista.modlist.json"]
    blob = b"".join(z.read(n) for n in names)
    assert str(tmp_path).encode() not in blob and b"Users" not in blob  # sin rutas del PC
    data, entries = read_zip(out)
    assert data["mods"][0]["nombre"] == "Create" and sorted(entries) == names[:-1]


def test_read_zip_rejects_dangerous_paths(tmp_path):
    bad = tmp_path / "malo.zip"
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr("lista.modlist.json", json.dumps(LIST))
        z.writestr("config/../../fuera.txt", "x")
    with pytest.raises(ConfigPackError):
        read_zip(bad)
    abs_ = tmp_path / "abs.zip"
    with zipfile.ZipFile(abs_, "w") as z:
        z.writestr("lista.modlist.json", json.dumps(LIST))
        z.writestr("C:/Windows/x.txt", "x")
    with pytest.raises(ConfigPackError):
        read_zip(abs_)


def test_read_zip_ignores_files_outside_config_and_needs_a_list(tmp_path):
    z1 = tmp_path / "otros.zip"
    with zipfile.ZipFile(z1, "w") as z:
        z.writestr("lista.modlist.json", json.dumps(LIST))
        z.writestr("mods/virus.jar", "x")
        z.writestr("config/a.toml", "a")
    data, entries = read_zip(z1)
    assert entries == ["config/a.toml"]
    z2 = tmp_path / "sinlista.zip"
    with zipfile.ZipFile(z2, "w") as z:
        z.writestr("config/a.toml", "a")
    with pytest.raises(ConfigPackError):
        read_zip(z2)


# ---------------------------------------------------------------- importar

def test_import_over_existing_config_with_backup(tmp_path):
    src = game(tmp_path, "origen")
    (src / "config" / "jei.toml").write_text("x = 99\n", encoding="utf-8")
    (src / "config" / "nuevo.toml").write_text("n = 1\n", encoding="utf-8")
    pack = tmp_path / "p.zip"
    export_zip(pack, LIST, src)
    dst = game(tmp_path, "destino")
    data, entries = read_zip(pack)
    prev = preview_import(pack, dst)
    assert prev["overwrite"] == ["config/jei.toml"] and prev["new"] == ["config/nuevo.toml"]
    saved = import_config(pack, dst, tmp_path / "antes")
    assert (dst / "config" / "jei.toml").read_text(encoding="utf-8") == "x = 99\n"
    assert (dst / "config" / "nuevo.toml").exists()
    assert (saved / "config" / "jei.toml").read_text(encoding="utf-8") == "x = 1\n"  # copia de lo sobrescrito
