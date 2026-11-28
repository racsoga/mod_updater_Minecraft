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


# ---------------------------------------------------------------- renombrado, registro y Deshacer

from mod_updater.downloader import apply_updates, last_undoable, read_changelog, undo_backup  # noqa: E402
from mod_updater.resolver import ACTUALIZABLE, AL_DIA, CF, DISABLE, ENABLE, Resolution  # noqa: E402


def res_for(path: Path, kind: str | None = None, **kw) -> Resolution:
    mod = scan_folder(path.parent)
    mod = next(m for m in mod if m.path == path)
    r = Resolution(mod=mod, status=kw.pop("status", AL_DIA), source=CF, project_id="1", project_name=path.stem, **kw)
    if kind:
        r.kind = kind
    return r


def mods_dir(tmp_path) -> Path:
    d = tmp_path / ".minecraft" / "mods"
    d.mkdir(parents=True)
    return d


def run(results, d):
    return apply_updates(results, d, modrinth_session=None, curseforge_session=None)


def test_disable_and_enable_round_trip(tmp_path):
    d = mods_dir(tmp_path)
    make_jar(d / "Balm.jar", "balm")
    backup, out = run([res_for(d / "Balm.jar", DISABLE)], d)
    assert out[0].ok and sorted(p.name for p in d.iterdir()) == ["Balm.jar.disabled"]
    change = read_changelog(backup)["changes"][0]
    assert (change["action"], change["old_file"], change["new_file"]) == ("disable", "Balm.jar", "Balm.jar.disabled")
    assert "[DESACTIVADO]" in (backup / "cambios.txt").read_text(encoding="utf-8")
    _, out = run([res_for(d / "Balm.jar.disabled", ENABLE)], d)
    assert out[0].ok and sorted(p.name for p in d.iterdir()) == ["Balm.jar"]


def test_toggle_never_overwrites(tmp_path):
    d = mods_dir(tmp_path)
    make_jar(d / "a.jar", "a")
    make_jar(d / "a.jar.disabled", "a_old")
    _, out = run([res_for(d / "a.jar.disabled", ENABLE)], d)
    assert not out[0].ok and "a.jar" in out[0].message
    assert sorted(p.name for p in d.iterdir()) == ["a.jar", "a.jar.disabled"]


def test_undo_reverts_a_toggle(tmp_path):
    d = mods_dir(tmp_path)
    make_jar(d / "x.jar", "x")
    run([res_for(d / "x.jar", DISABLE)], d)
    r = undo_backup(last_undoable(d))
    assert not r.errors and r.restored == 1 and sorted(p.name for p in d.iterdir()) == ["x.jar"]


def test_undo_toggle_with_file_moved_by_hand(tmp_path):
    d = mods_dir(tmp_path)
    make_jar(d / "x.jar", "x")
    run([res_for(d / "x.jar", DISABLE)], d)
    (d / "x.jar.disabled").unlink()
    r = undo_backup(last_undoable(d))
    assert r.errors and r.restored == 0


def test_updating_a_disabled_mod_keeps_it_disabled(tmp_path, monkeypatch):
    from mod_updater import downloader
    d = mods_dir(tmp_path)
    make_jar(d / "m-1.0.jar.disabled", "m")
    r = res_for(d / "m-1.0.jar.disabled", status=ACTUALIZABLE, new_file_name="m-2.0.jar",
                download_url="https://cdn.modrinth.com/m-2.0.jar", new_version="2.0")
    monkeypatch.setattr(downloader, "download_verified", lambda res, dest, sf: make_jar(dest, "m"))
    backup, out = run([r], d)
    assert out[0].ok and sorted(p.name for p in d.iterdir()) == ["m-2.0.jar.disabled"]
    assert read_changelog(backup)["changes"][0]["new_file"] == "m-2.0.jar.disabled"
    undo_backup(backup)
    assert sorted(p.name for p in d.iterdir()) == ["m-1.0.jar.disabled"]


# ---------------------------------------------------------------- dependientes

from mod_updater.deps import dependents_of, plan_with_dependencies  # noqa: E402
from mod_updater.resolver import Dep  # noqa: E402
from mod_updater.scanner import ModFile  # noqa: E402


def fake(name, pid, *, deps=(), requires=(), disabled=False, mod_id=None):
    file_name = f"{name}.jar" + (".disabled" if disabled else "")
    mod = ModFile(path=Path(file_name), file_name=file_name, size=1, sha1=name, sha512="", cf_fingerprint=0,
                  mod_id=mod_id or name.lower(), requires=list(requires))
    return Resolution(mod=mod, status=AL_DIA, source=CF, project_id=pid, project_name=name,
                      current_deps=list(deps), known_ids={(CF, pid)})


def test_dependents_of_a_library():
    balm = fake("Balm", "1")
    users = [fake(n, str(i), deps=[Dep(CF, "1")]) for i, n in enumerate(["Waystones", "A", "B", "C"], 10)]
    other = fake("Otro", "99")
    assert sorted(r.name for r in dependents_of([balm, *users, other], [balm])) == ["A", "B", "C", "Waystones"]


def test_dependents_are_recursive_and_use_mods_toml():
    lib = fake("Lib", "1", mod_id="lib")
    mid = fake("Medio", "2", requires=["lib"])
    top = fake("Arriba", "3", deps=[Dep(CF, "2")])
    assert sorted(r.name for r in dependents_of([lib, mid, top], [lib])) == ["Arriba", "Medio"]


def test_disabled_mods_are_not_dependents():
    lib = fake("Lib", "1")
    off = fake("Apagado", "2", deps=[Dep(CF, "1")], disabled=True)
    assert dependents_of([lib, off], [lib]) == []


def test_disabled_mod_does_not_pull_or_break_dependencies():
    class NoFinder:
        def find(self, dep):
            pytest.fail("no debería buscar dependencias de un mod desactivado")

        def version_date(self, dep):
            return None

    off = fake("Apagado", "2", deps=[Dep(CF, "404")], disabled=True)
    plan = plan_with_dependencies([off], [], NoFinder())
    assert plan.items == [] and plan.broken == [] and plan.ignored == []


# ---------------------------------------------------------------- API

def make_api(tmp_path, names_deps, running=()):
    """names_deps: [(archivo, pid, [pids que necesita])]. Devuelve (api, carpeta de mods)."""
    from mod_updater.gui.api import Api
    from mod_updater.settings import Settings, save_settings
    d = mods_dir(tmp_path)
    f = tmp_path / "s.json"
    save_settings(Settings(mods_dir=str(d), setup_done=True), f)
    a = Api(f, get_key=lambda: (None, None), run_async=lambda fn: fn(), cache_dir=tmp_path / "c",
            running=lambda game_dir: list(running))
    results = []
    for file_name, pid, needs in names_deps:
        make_jar(d / file_name, file_name.split(".")[0].lower())
        r = res_for(d / file_name)
        r.project_id, r.known_ids, r.project_name = pid, {(CF, pid)}, file_name.split(".")[0]
        r.current_deps = [Dep(CF, n) for n in needs]
        results.append(r)
    a._results, a._rows = results, list(results)
    a._row_s = ["ok"] * len(results)
    return a, d


def files(d):
    return sorted(p.name for p in d.iterdir())


def test_api_disable_and_enable(tmp_path):
    a, d = make_api(tmp_path, [("Jei.jar", "1", [])])
    res = a.mods_set_enabled([0], False)
    assert res["ok"] and res["rows"] == [{"id": 0, "off": True}] and files(d) == ["Jei.jar.disabled"]
    assert a._results[0].mod.disabled  # en memoria también, sin volver a revisar
    res = a.mods_set_enabled([0], True)
    assert res["ok"] and res["rows"] == [{"id": 0, "off": False}] and files(d) == ["Jei.jar"]


def test_api_blocks_when_minecraft_is_open(tmp_path):
    a, d = make_api(tmp_path, [("Jei.jar", "1", [])], running=[1234])
    res = a.mods_set_enabled([0], False)
    assert not res["ok"] and res["reason"] == "minecraft" and files(d) == ["Jei.jar"]


def test_api_warns_before_disabling_a_library(tmp_path):
    a, d = make_api(tmp_path, [("Balm.jar", "1", []), ("Waystones.jar", "2", ["1"]), ("A.jar", "3", ["1"]),
                               ("Otro.jar", "4", [])])
    res = a.mods_set_enabled([0], False)
    assert not res["ok"] and res["reason"] == "dependents" and res["names"] == ["A", "Waystones"]
    assert res["message"] == "Si desactivas Balm, dejarán de cargar A y Waystones."
    assert files(d) == ["A.jar", "Balm.jar", "Otro.jar", "Waystones.jar"]
    res = a.mods_set_enabled([0], False, "with")
    assert res["ok"] and files(d) == ["A.jar.disabled", "Balm.jar.disabled", "Otro.jar", "Waystones.jar.disabled"]
    assert sorted(r["id"] for r in res["rows"] if r["off"]) == [0, 1, 2]


def test_api_disable_only_the_library(tmp_path):
    a, d = make_api(tmp_path, [("Balm.jar", "1", []), ("Waystones.jar", "2", ["1"])])
    assert a.mods_set_enabled([0], False, "only")["ok"]
    assert files(d) == ["Balm.jar.disabled", "Waystones.jar"]


def test_api_enabling_also_enables_its_disabled_library(tmp_path):
    a, d = make_api(tmp_path, [("Balm.jar.disabled", "1", []), ("Waystones.jar.disabled", "2", ["1"])])
    res = a.mods_set_enabled([1], True)
    assert res["ok"] and res["also"] == ["Balm"] and files(d) == ["Balm.jar", "Waystones.jar"]


def test_api_toggle_makes_no_backup_and_keeps_the_last_update_copy(tmp_path):
    """Activar/desactivar no crea copia ni cuenta para el límite (por defecto 1): la copia de la
    última actualización sigue ahí. Deshacer = volver a pulsar el interruptor."""
    import json
    from mod_updater.downloader import backup_root, list_backups
    from mod_updater.settings import load_settings, save_settings
    a, d = make_api(tmp_path, [("Jei.jar", "1", [])])
    s = load_settings(a._settings_file)
    s.backups_to_keep = 1
    save_settings(s, a._settings_file)
    update_copy = backup_root(d) / "2026-11-28_1000"
    update_copy.mkdir(parents=True)
    (update_copy / "cambios.json").write_text(json.dumps({"complete": True, "mods_dir": str(d), "changes": [
        {"ok": True, "state": "ok", "action": "update", "name": "Jei", "old_file": "Jei-old.jar",
         "new_file": "Jei.jar", "backup_file": "Jei-old.jar"}]}), encoding="utf-8")
    (update_copy / "Jei-old.jar").write_bytes(b"viejo")
    assert a.mods_set_enabled([0], False)["ok"] and files(d) == ["Jei.jar.disabled"]
    assert a.mods_set_enabled([0], True)["ok"] and files(d) == ["Jei.jar"]
    assert list_backups(d) == [update_copy] and (update_copy / "Jei-old.jar").exists()


def test_api_reports_rename_conflict(tmp_path):
    a, d = make_api(tmp_path, [("Jei.jar.disabled", "1", [])])
    make_jar(d / "Jei.jar", "jei_otro")
    res = a.mods_set_enabled([0], True)
    assert not res["ok"] and res["failed"][0]["name"] == "Jei"


def test_rows_include_off_and_file(tmp_path):
    from mod_updater.deps import DepPlan
    from mod_updater.gui.api import serialize
    off = fake("Apagado", "2", disabled=True)
    row = serialize([off], DepPlan(items=[]), allow_beta=False)["rows"][0]
    assert row["off"] is True and row["file"] == "Apagado.jar.disabled"


# ---------------------------------------------------------------- Análisis y exportar

def test_analysis_counts_disabled_apart():
    from mod_updater.analysis import analyze
    on, off = fake("Activo", "1"), fake("Apagado", "2", disabled=True)
    data = analyze([on, off])
    assert data["totals"]["mods"] == 1 and data["totals"]["disabled"] == 1
    assert [m for b in data["by_category"] for m in b["mods"]] == ["Activo"]


def test_mrpack_leaves_out_disabled():
    import io
    import json
    from types import SimpleNamespace
    from mod_updater.modlist import build_mrpack
    on, off = fake("Activo", "1"), fake("Apagado", "2", disabled=True)
    f = lambda n: SimpleNamespace(sha1=n, sha512="x", url=f"https://cdn.modrinth.com/{n}.jar", filename=f"{n}.jar", size=1)  # noqa: E731
    by_sha = {n: SimpleNamespace(files=[f(n)], primary_file=f(n)) for n in ("Activo", "Apagado")}
    blob, excluded = build_mrpack([on, off], by_sha, name="x", minecraft="1.21.1", loader="neoforge", loader_version=None)
    index = json.loads(zipfile.ZipFile(io.BytesIO(blob)).read("modrinth.index.json"))
    assert [x["path"] for x in index["files"]] == ["mods/Activo.jar"] and excluded == []


def test_modlist_marks_disabled():
    from mod_updater.modlist import build
    on, off = fake("Activo", "1"), fake("Apagado", "2", disabled=True)
    mods = {m["nombre"]: m for m in build([on, off], minecraft="1.21.1", loader="neoforge", app="t")["mods"]}
    assert mods["Apagado"]["activo"] is False and "activo" not in mods["Activo"]


# ---------------------------------------------------------------- revisión final

def test_disabled_old_copy_is_not_a_duplicate_on_modrinth():
    from test_resolver import FakeClient, mod, resolve, ver
    v_old, v_new = ver("1.0", "p1", "release", "2024-01-01"), ver("1.1", "p1", "release", "2024-02-01")
    client = FakeClient(current={"h1": v_new, "h0": v_old}, latest={"h1": v_new, "h0": v_new})
    r = resolve(client, [mod("jei-1.1.jar", "h1"), mod("jei-1.0.jar.disabled", "h0")])
    assert not r["jei-1.1.jar"].duplicate


def test_disabled_old_copy_is_not_a_duplicate_on_curseforge():
    from test_resolver import FakeClient, FakeCf, cf_file, cf_mod, run_all
    from mod_updater.curseforge import CfMatch
    cur, old, new = (cf_file(i, 1, "release", d) for i, d in ((10, "2024-01-01"), (9, "2023-01-01"), (11, "2024-02-01")))
    cf = FakeCf(matches={100: CfMatch(1, cur), 99: CfMatch(1, old)}, index={1: [11]}, files={11: new})
    r = run_all(cf, FakeClient(current={}, latest={}), [cf_mod("a.jar", "h1", 100), cf_mod("a-old.jar.disabled", "h0", 99)])
    assert not r["a.jar"].duplicate and r["a.jar"].status == ACTUALIZABLE


def test_toggle_renames_in_the_mods_own_folder(tmp_path):
    other = tmp_path / "otro" / "mods"
    other.mkdir(parents=True)
    make_jar(other / "x.jar", "x")
    d = mods_dir(tmp_path)  # carpeta del perfil activo: distinta
    _, out = run([res_for(other / "x.jar", DISABLE)], d)
    assert out[0].ok and files(other) == ["x.jar.disabled"] and files(d) == []


def test_updatable_takes_the_active_copy_and_skips_the_disabled_one():
    from mod_updater.downloader import updatable
    active, old = fake("Jei", "1"), fake("Jei", "1", disabled=True)
    old.mod.file_name = old.mod.path.name.replace("Jei", "Jei-old")
    for r in (active, old):
        r.status = ACTUALIZABLE
    ok, skipped = updatable([active, old])
    assert ok == [active] and skipped == [old]


def test_updatable_still_updates_a_lone_disabled_mod():
    from mod_updater.downloader import updatable
    off = fake("Solo", "2", disabled=True)
    off.status = ACTUALIZABLE
    assert updatable([off])[0] == [off]


def test_api_refuses_rows_from_another_folder(tmp_path):
    from mod_updater.settings import load_settings, save_settings
    a, d = make_api(tmp_path, [("Jei.jar", "1", [])])
    other = tmp_path / "otra" / "mods"
    other.mkdir(parents=True)
    s = load_settings(a._settings_file)
    s.mods_dir = str(other)  # se cambió de perfil y la revisión es de la carpeta anterior
    save_settings(s, a._settings_file)
    res = a.mods_set_enabled([0], False)
    assert not res["ok"] and files(d) == ["Jei.jar"]


# ---------------------------------------------------------------- importar con "activo": false

def test_resolve_exact_marks_inactive_installs():
    from types import SimpleNamespace
    from mod_updater.modlist import resolve_exact
    f = SimpleNamespace(url="https://cdn.modrinth.com/a.jar", filename="a-1.0.jar", sha1="s", sha512="x", size=1)
    mr = SimpleNamespace(version=lambda vid: SimpleNamespace(primary_file=f, project_id="pa", version_number="1.0"))
    m = {"nombre": "A", "fuente": "modrinth", "proyecto": "pa", "archivo": "va"}
    out, _ = resolve_exact({"add": [m | {"activo": False}, m | {"nombre": "B", "proyecto": "pa"}], "update": []},
                           [], curseforge=None, modrinth=mr)
    assert [r.install_disabled for r in out] == [True, False]


def test_install_disabled_lands_as_jar_disabled(tmp_path, monkeypatch):
    from mod_updater import downloader
    from mod_updater.resolver import INSTALL
    d = mods_dir(tmp_path)
    r = Resolution(mod=None, kind=INSTALL, status=ACTUALIZABLE, source=CF, project_id="1", project_name="A",
                   new_file_name="a-1.0.jar", download_url="https://cdn.modrinth.com/a.jar", install_disabled=True)
    monkeypatch.setattr(downloader, "download_verified", lambda res, dest, sf: make_jar(dest, "a"))
    _, out = run([r], d)
    assert out[0].ok and files(d) == ["a-1.0.jar.disabled"]


def test_modlist_import_shows_inactive_mods(tmp_path, monkeypatch):
    from mod_updater import modlist as modlist_mod
    a, d = make_api(tmp_path, [("Jei.jar", "1", [])])
    monkeypatch.setattr(modlist_mod, "parse", lambda text: {})
    monkeypatch.setattr(modlist_mod, "compare", lambda data, results, **k: {
        "mismatch": None, "add": [{"nombre": "Nuevo", "version": "1", "activo": False}], "update": [], "same": [],
        "unavailable": [], "remove": []})
    path = tmp_path / "x.modlist.json"
    path.write_text("{}", encoding="utf-8")
    a._file_dialog = lambda *x, **k: str(path)
    assert a.modlist_import()["add"] == [{"name": "Nuevo", "version": "1", "have": None, "off": True}]
