"""Exportar e importar la lista de mods (.modlist.json y .mrpack) y comparar perfiles."""

import io
import json
import zipfile
from pathlib import Path

import pytest

from mod_updater.modlist import (
    ModlistError,
    build,
    build_mrpack,
    compare,
    compare_folders,
    dumps,
    parse,
    readable,
)
from mod_updater.modrinth import MrFile, MrVersion
from mod_updater.resolver import AL_DIA, CF, MR, NO_ENCONTRADO, Resolution
from mod_updater.scanner import ModFile

SECRET = "clave-super-secreta-1234"


def inst(name, source=CF, pid="1", file_id="100", sha1=None, version="1.0", cat="tecnologia", folder="C:/Users/Ana/mods"):
    mod = ModFile(path=Path(folder) / f"{name}.jar", file_name=f"{name}.jar", size=10, sha1=sha1 or f"sha-{name}",
                  sha512="", cf_fingerprint=0, mod_id=name.lower())
    return Resolution(mod=mod, status=AL_DIA if source else NO_ENCONTRADO, source=source, project_id=pid if source else None,
                      project_name=name, current_version=version, current_file_id=file_id if source else None,
                      categories=[cat] if source else [], known_ids={(source, pid)} if source else set())


def collection():
    return [inst("Create", CF, "328085", "5001", version="6.0"), inst("Sodium", MR, "AANobbMI", "abcd", version="0.6"),
            inst("Propio", None)]


def test_build_has_versioned_format_and_no_paths_or_key():
    data = build(collection(), minecraft="1.21.1", loader="neoforge", app="Mod Updater 0.3.0")
    assert (data["formato"], data["minecraft"], data["cargador"], data["app"]) == (1, "1.21.1", "neoforge", "Mod Updater 0.3.0")
    create = data["mods"][0]
    assert create == {"nombre": "Create", "fuente": "curseforge", "proyecto": 328085, "archivo": 5001,
                      "version": "6.0", "sha1": "sha-Create", "categoria": "tecnologia"}
    assert data["mods"][1]["proyecto"] == "AANobbMI" and data["mods"][1]["archivo"] == "abcd"
    assert data["mods"][2]["fuente"] is None and data["mods"][2]["nombre_archivo"] == "Propio.jar"
    text = dumps(data)
    assert "Users" not in text and "Ana" not in text and ":/" not in text and SECRET not in text


def test_roundtrip_parse():
    text = dumps(build(collection(), minecraft="1.21.1", loader="neoforge", app="x"))
    again = parse(text)
    assert [m["nombre"] for m in again["mods"]] == ["Create", "Sodium", "Propio"]


@pytest.mark.parametrize("text", ["{no es json", "[]", '{"formato": 1}', '{"formato": 99, "minecraft": "1.21.1", "cargador": "neoforge", "mods": []}',
                                  '{"formato": 1, "minecraft": "1.21.1", "cargador": "neoforge", "mods": [{"fuente": "curseforge"}]}'])
def test_corrupt_or_unknown_files_rejected(text):
    with pytest.raises(ModlistError):
        parse(text)


def test_compare_add_update_remove_same_unavailable():
    mine = [inst("Create", CF, "328085", "5001"), inst("JEI", CF, "238222", "7000"), inst("Viejo", CF, "9", "90")]
    theirs = build([inst("Create", CF, "328085", "5001"), inst("JEI", CF, "238222", "7100", sha1="otro"),
                    inst("Waystones", CF, "245755", "8000"), inst("Propio", None)],
                   minecraft="1.21.1", loader="neoforge", app="x")
    c = compare(theirs, mine, minecraft="1.21.1", loader="neoforge")
    assert [m["nombre"] for m in c["add"]] == ["Waystones"]
    assert [m["nombre"] for m in c["update"]] == ["JEI"]
    assert [r.name for r in c["remove"]] == ["Viejo"]
    assert [m["nombre"] for m in c["same"]] == ["Create"]
    assert [m["nombre"] for m in c["unavailable"]] == ["Propio"]
    assert c["mismatch"] is None


def test_compare_warns_about_other_minecraft_version():
    theirs = build([inst("Create", CF, "328085", "5001")], minecraft="1.20.1", loader="forge", app="x")
    c = compare(theirs, [], minecraft="1.21.1", loader="neoforge")
    assert c["mismatch"] == {"minecraft": "1.20.1", "loader": "forge"}


def test_readable_list():
    text = readable(collection())
    assert text.splitlines() == ["Create 6.0", "Propio 1.0", "Sodium 0.6"]


def test_compare_folders_locally(tmp_path):
    a = [inst("Create", sha1="x1"), inst("JEI", sha1="j1"), inst("SoloA", sha1="a1")]
    b = [inst("Create", sha1="x1"), inst("JEI", sha1="j2"), inst("SoloB", sha1="b1")]
    c = compare_folders([r.mod for r in a], [r.mod for r in b])
    assert c["only_a"] == ["SoloA"] and c["only_b"] == ["SoloB"] and c["different"] == ["JEI"] and c["same"] == 1


def test_mrpack_only_includes_mods_with_allowed_urls():
    def ver(pid, url):
        return MrVersion(id="v" + pid, project_id=pid, name="v", version_number="1", version_type="release",
                         date_published="2026-01-01", files=[MrFile(url, f"{pid}.jar", "s1" + pid, "s512" + pid, 42, True)])
    by_sha = {"sha-Create": ver("LNytGWDc", "https://cdn.modrinth.com/data/LNytGWDc/create.jar"),
              "sha-Sodium": ver("AANobbMI", "https://evil.example/sodium.jar")}
    blob, excluded = build_mrpack(collection(), by_sha, name="Mi perfil", minecraft="1.21.1", loader="neoforge",
                                  loader_version="21.1.77")
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        index = json.loads(z.read("modrinth.index.json"))
    assert index["formatVersion"] == 1 and index["game"] == "minecraft" and index["name"] == "Mi perfil"
    assert index["dependencies"] == {"minecraft": "1.21.1", "neoforge": "21.1.77"}
    assert [f["path"] for f in index["files"]] == ["mods/LNytGWDc.jar"]
    assert index["files"][0]["hashes"] == {"sha1": "s1LNytGWDc", "sha512": "s512LNytGWDc"}
    assert sorted(excluded) == ["Propio", "Sodium"]


# --------------------------------------------------------------------------- API


def make_jar(path: Path, mod_id: str, extra: bytes = b""):
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("META-INF/neoforge.mods.toml", f'[[mods]]\nmodId="{mod_id}"\nversion="1"\n')
        z.writestr("x.bin", extra)


@pytest.fixture
def api(tmp_path):
    from mod_updater.gui.api import Api
    from mod_updater.settings import Settings, save_settings
    mods = tmp_path / "a" / "mods"
    mods.mkdir(parents=True)
    f = tmp_path / "s.json"
    save_settings(Settings(mods_dir=str(mods), setup_done=True), f)
    a = Api(f, get_key=lambda: (None, None), run_async=lambda fn: fn(), cache_dir=tmp_path / "c", running=lambda d: [])
    a._results = collection()
    return a


def test_api_export_writes_file_without_paths(api, tmp_path):
    out = tmp_path / "lista.modlist.json"
    api._file_dialog = lambda save, name="", types=(): str(out)
    res = api.modlist_export("modlist")
    assert res["ok"] and res["file"] == "lista.modlist.json"
    text = out.read_text(encoding="utf-8")
    assert parse(text)["minecraft"] == "1.21.1" and str(tmp_path) not in text and "Users" not in text
    api._file_dialog = lambda *a, **k: None
    assert api.modlist_export("modlist").get("cancelled")


def test_api_import_compares_and_rejects_corrupt(api, tmp_path):
    good = tmp_path / "b.modlist.json"
    good.write_text(dumps(build([inst("Create", CF, "328085", "5001", version="6.0"), inst("Waystones", CF, "245755", "8000")],
                                minecraft="1.20.1", loader="neoforge", app="x")), encoding="utf-8")
    api._file_dialog = lambda save, name="", types=(): str(good)
    res = api.modlist_import()
    assert res["ok"] and [m["name"] for m in res["add"]] == ["Waystones"] and res["same"] == 1
    assert res["mismatch"] == {"minecraft": "1.20.1", "loader": "neoforge"}
    assert {r["name"] for r in res["remove"]} == {"Sodium", "Propio"}
    bad = tmp_path / "roto.json"
    bad.write_text("{basura", encoding="utf-8")
    api._file_dialog = lambda save, name="", types=(): str(bad)
    assert api.modlist_import()["ok"] is False


def test_api_import_start_installs_exact_and_optional_removals(api, tmp_path, monkeypatch):
    from mod_updater.gui import api as api_mod
    from mod_updater.resolver import ACTUALIZABLE, INSTALL, REMOVE
    good = tmp_path / "b.modlist.json"
    good.write_text(dumps(build([inst("Create", CF, "328085", "5001"), inst("Waystones", CF, "245755", "8000")],
                                minecraft="1.21.1", loader="neoforge", app="x")), encoding="utf-8")
    api._file_dialog = lambda save, name="", types=(): str(good)
    api.modlist_import()
    way = Resolution(mod=None, kind=INSTALL, status=ACTUALIZABLE, source=CF, project_id="245755", project_name="Waystones",
                     new_version="21.1.47", new_file_name="w.jar", download_url="https://edge.forgecdn.net/w.jar")
    monkeypatch.setattr(api_mod.modlist_mod, "resolve_exact", lambda changes, installed, **k: ([way], []))
    started = []
    api._apply = lambda chosen, s, index: started.append(sorted((r.name, r.kind) for r in chosen))
    res = api.modlist_import_start(remove=True)
    assert res["ok"] and started == [[("Propio", REMOVE), ("Sodium", REMOVE), ("Waystones", INSTALL)]]
    assert {r["s"] for r in res["rows"]} == {"dep", "rm"}


def test_api_copy_list_and_compare_profiles(api, tmp_path):
    from mod_updater import profiles
    from mod_updater.settings import load_settings, save_settings
    copied = []
    api._clipboard = copied.append
    assert api.copy_list()["count"] == 3 and copied[0].startswith("Create 6.0")
    a_mods = Path(api._settings().mods_dir)
    make_jar(a_mods / "create.jar", "create")
    make_jar(a_mods / "jei.jar", "jei", b"a")
    b_mods = tmp_path / "b" / "mods"
    make_jar(b_mods / "create.jar", "create")
    make_jar(b_mods / "jei.jar", "jei", b"b")
    make_jar(b_mods / "waystones.jar", "waystones")
    s = load_settings(api._settings_file)
    pid = profiles.add(s, name="Servidor", mods_dir=str(b_mods), minecraft_version="1.21.1", loader="neoforge")
    save_settings(s, api._settings_file)
    res = api.compare_profiles(pid)
    import hashlib as _h
    dbg = (res, [(p.parent.parent.name, p.name, _h.sha1(p.read_bytes()).hexdigest()[:8], p.stat().st_size, p.stat().st_mtime_ns) for p in sorted(a_mods.glob("*.jar")) + sorted(b_mods.glob("*.jar"))])
    assert res["ok"] and res["only_b"] == ["waystones"] and res["different"] == ["jei"] and res["same"] == 1, dbg


def test_scan_cache_is_per_folder(api, tmp_path):
    """Dos carpetas con un jar de igual nombre, tamaño y fecha pero distinto contenido no comparten caché."""
    import os
    from mod_updater import profiles
    from mod_updater.settings import load_settings, save_settings
    a_mods = Path(api._settings().mods_dir)
    b_mods = tmp_path / "otro" / "mods"
    make_jar(a_mods / "jei.jar", "jei", b"a")
    make_jar(b_mods / "jei.jar", "jei", b"b")
    stamp = (a_mods / "jei.jar").stat().st_mtime_ns
    os.utime(b_mods / "jei.jar", ns=(stamp, stamp))
    assert (a_mods / "jei.jar").stat().st_size == (b_mods / "jei.jar").stat().st_size
    s = load_settings(api._settings_file)
    pid = profiles.add(s, name="Otro", mods_dir=str(b_mods), minecraft_version="1.21.1", loader="neoforge")
    save_settings(s, api._settings_file)
    assert api.compare_profiles(pid)["different"] == ["jei"]
    assert api.compare_profiles(pid)["different"] == ["jei"]  # también con la caché ya escrita
