"""Hito 3 (v4): fijar versión ("No actualizar este") y volver a una versión anterior."""

from pathlib import Path

import pytest

from mod_updater import i18n
from mod_updater.deps import DepPlan, plan_with_dependencies
from mod_updater.downloader import updatable
from mod_updater.modrinth import MrFile, MrVersion
from mod_updater.pins import apply_pins, pin_key, pins_for_folder
from mod_updater.resolver import ACTUALIZABLE, AL_DIA, CF, MR, Dep, Resolution
from mod_updater.scanner import ModFile
from test_toggle import files, make_jar, mods_dir


def setup_module():
    i18n.set_language("es")


def res(name, pid, *, source=MR, status=AL_DIA, path=None, deps=(), new_deps=(), mr_id=None, **kw):
    path = path or Path(f"{name}.jar")
    mod = ModFile(path=path, file_name=path.name, size=1, sha1=f"sha-{name}", sha512="", cf_fingerprint=0,
                  mod_id=name.lower())
    ids = {(source, pid)} | ({(MR, mr_id)} if mr_id else set())
    return Resolution(mod=mod, status=status, source=source, project_id=pid, project_name=name,
                      current_version="1.0", current_date="2026-01-01", current_file_id="v1",
                      current_deps=list(deps), new_deps=list(new_deps), known_ids=ids, **kw)


# ---------------------------------------------------------------- modelo

def test_pin_key_and_apply_pins_by_any_known_id():
    a = res("Create", "328085", source=CF, mr_id="LNytGWDc")
    b = res("Jei", "u6dRKJwZ")
    assert pin_key(a) == "curseforge:328085"
    apply_pins([a, b], {"modrinth:LNytGWDc": {"name": "Create", "version": "6.0.4", "reason": "el server va en 6.0.4"}})
    assert a.pinned and a.pin_reason == "el server va en 6.0.4" and not b.pinned


def test_pinned_mod_is_not_updated():
    a = res("Create", "1", status=ACTUALIZABLE, new_version="2.0")
    b = res("Jei", "2", status=ACTUALIZABLE, new_version="2.0")
    a.pinned = True
    ok, skipped = updatable([a, b])
    assert ok == [b] and a not in skipped  # fijado: ni se actualiza ni sale como "duplicado"


def test_pinned_dependency_blocks_the_mod_that_needs_it_newer():
    class Finder:
        def find(self, dep):
            return None

        def version_date(self, dep):
            return "2026-06-01"  # la versión que exige es más nueva que la instalada

    lib = res("Balm", "balm", status=ACTUALIZABLE, new_version="2.0")
    lib.pinned = True
    user = res("Waystones", "ways", status=ACTUALIZABLE, new_version="2.0",
               new_deps=[Dep(MR, "balm", version_id="vreq")])
    plan = plan_with_dependencies([lib, user], [user], Finder())
    assert plan.items == [] and plan.blocked == [user]
    assert "Balm" in user.note and "fijad" in user.note


def test_row_of_a_pinned_mod():
    from mod_updater.gui.api import serialize
    a = res("Create", "1", status=ACTUALIZABLE, new_version="6.0.8")
    a.pinned, a.pin_reason = True, "el server va en 6.0.4"
    row = serialize([a], DepPlan(items=[]), allow_beta=False)["rows"][0]
    assert row["s"] == "pin" and row["sub"] == "el server va en 6.0.4" and row["to"] == "6.0.8" and not row["checked"]
    a.pin_reason = ""
    assert serialize([a], DepPlan(items=[]), allow_beta=False)["rows"][0]["sub"] == "Fijado en 1.0 · hay 6.0.8"


def test_pins_for_folder_reads_the_matching_profile(tmp_path):
    from mod_updater.settings import Settings, save_settings
    f = tmp_path / "s.json"
    s = Settings(mods_dir=str(tmp_path / "a" / "mods"), setup_done=True)
    save_settings(s, f)
    from mod_updater.settings import load_settings
    s = load_settings(f)
    s.pins = {"modrinth:x": {"name": "X", "version": "1.0", "reason": ""}}
    save_settings(s, f)
    assert pins_for_folder(tmp_path / "a" / "mods", f) == {"modrinth:x": {"name": "X", "version": "1.0", "reason": ""}}
    assert pins_for_folder(tmp_path / "otra", f) == {}


# ---------------------------------------------------------------- API

def mr_version(vid, number, date, channel="release"):
    return MrVersion(id=vid, project_id="pj", name=number, version_number=number, version_type=channel,
                     date_published=date, files=[MrFile(url=f"https://cdn.modrinth.com/{vid}.jar",
                                                        filename=f"mod-{number}.jar", sha1=f"s{vid}", sha512="x",
                                                        size=10, primary=True)])


class FakeMr:
    session = None

    def __init__(self, *a, **k):
        self.versions = [mr_version("v3", "3.0", "2026-03-01"), mr_version("v2", "2.0", "2026-02-01"),
                         mr_version("v1", "1.0", "2026-01-01")]

    def project_versions(self, project_id, loader, game_version):
        return list(self.versions)


def make_api(tmp_path, *, running=()):
    from mod_updater.gui.api import Api
    from mod_updater.settings import Settings, save_settings
    d = mods_dir(tmp_path)
    f = tmp_path / "s.json"
    save_settings(Settings(mods_dir=str(d), setup_done=True), f)
    a = Api(f, get_key=lambda: (None, None), mr_factory=FakeMr, run_async=lambda fn: fn(),
            cache_dir=tmp_path / "c", running=lambda game_dir: list(running))
    make_jar(d / "mod-1.0.jar", "mod")
    r = res("Mod", "pj", path=d / "mod-1.0.jar", status=ACTUALIZABLE, new_version="3.0")
    a._results, a._rows, a._row_s = [r], [r], ["up"]
    return a, d, r


def test_pin_is_saved_per_profile(tmp_path):
    from mod_updater.settings import load_settings
    a, d, r = make_api(tmp_path)
    assert a.pin_set(0, True, "  el server va en 1.0  ")["ok"]
    s = load_settings(a._settings_file)
    assert s.pins == {"modrinth:pj": {"name": "Mod", "version": "1.0", "reason": "el server va en 1.0", "ids": ["modrinth:pj"]}}
    assert s.profiles[0]["pins"] == s.pins
    assert a.pin_set(0, False)["ok"] and load_settings(a._settings_file).pins == {}


def test_versions_list_marks_the_installed_one(tmp_path):
    a, d, r = make_api(tmp_path)
    out = a.versions_for(0)
    assert out["ok"] and [(v["version"], v["current"]) for v in out["versions"]] == [
        ("3.0", False), ("2.0", False), ("1.0", True)]
    assert out["pinned"] is False


def test_rollback_installs_that_exact_version_and_pins_it(tmp_path, monkeypatch):
    from mod_updater import downloader
    from mod_updater.downloader import last_undoable, undo_backup
    from mod_updater.settings import load_settings
    a, d, r = make_api(tmp_path)
    got = []
    monkeypatch.setattr(downloader, "download_verified", lambda res, dest, sf: (got.append(res.download_url), make_jar(dest, "mod")))
    out = a.rollback(0, "v2")
    assert out["ok"] and got == ["https://cdn.modrinth.com/v2.jar"] and files(d) == ["mod-2.0.jar"]
    assert load_settings(a._settings_file).pins["modrinth:pj"]["version"] == "2.0"
    assert undo_backup(last_undoable(d)).restored == 1 and files(d) == ["mod-1.0.jar"]


def test_rollback_failure_does_not_pin(tmp_path, monkeypatch):
    from mod_updater import downloader
    from mod_updater.net import ApiError
    from mod_updater.settings import load_settings

    def boom(res, dest, sf):
        raise ApiError("x", kind="offline")

    a, d, r = make_api(tmp_path)
    monkeypatch.setattr(downloader, "download_verified", boom)
    a.rollback(0, "v2")
    assert load_settings(a._settings_file).pins == {} and files(d) == ["mod-1.0.jar"]


def test_rollback_rejects_unknown_version_and_open_minecraft(tmp_path):
    a, d, r = make_api(tmp_path)
    assert not a.rollback(0, "no-existe")["ok"]
    a2, d2, r2 = make_api(tmp_path / "b", running=[1])
    out = a2.rollback(0, "v2")
    assert not out["ok"] and out["reason"] == "minecraft"


# ---------------------------------------------------------------- exportar e importar

def test_modlist_marks_pinned():
    from mod_updater.modlist import build
    a = res("Create", "1")
    a.pinned = True
    b = res("Jei", "2")
    mods = {m["nombre"]: m for m in build([a, b], minecraft="1.21.1", loader="neoforge", app="t")["mods"]}
    assert mods["Create"]["fijado"] is True and "fijado" not in mods["Jei"]


def test_modlist_import_keeps_pins(tmp_path, monkeypatch):
    from mod_updater import modlist as modlist_mod
    from mod_updater.settings import load_settings
    a, d, r = make_api(tmp_path)
    a._import = {"add": [], "update": [], "unavailable": [], "remove": [], "mismatch": None,
                 "same": [{"nombre": "Mod", "fuente": "modrinth", "proyecto": "pj", "version": "1.0", "fijado": True}]}
    monkeypatch.setattr(modlist_mod, "resolve_exact", lambda *x, **k: ([], []))
    a.modlist_import_start(False)
    assert load_settings(a._settings_file).pins["modrinth:pj"] == {"name": "Mod", "version": "1.0", "reason": ""}


def test_cli_respects_the_profile_pins(tmp_path, monkeypatch):
    """La CLI lee las fijaciones del perfil de la app con esa carpeta y no actualiza esos mods."""
    from mod_updater import main as cli
    from mod_updater.settings import Settings, load_settings, save_settings
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    d = mods_dir(tmp_path)
    save_settings(Settings(mods_dir=str(d), setup_done=True))
    s = load_settings()
    s.pins = {"modrinth:pj": {"name": "Mod", "version": "1.0", "reason": ""}}
    save_settings(s)
    a = res("Mod", "pj", status=ACTUALIZABLE, new_version="3.0")
    b = res("Otro", "po", status=ACTUALIZABLE, new_version="3.0")
    monkeypatch.setattr(cli, "scan_folder", lambda *x, **k: [a.mod, b.mod])
    monkeypatch.setattr(cli, "resolve_all", lambda *x, **k: [a, b])
    monkeypatch.setattr(cli, "print_report", lambda *x, **k: None)
    seen = []
    monkeypatch.setattr(cli, "plan_with_dependencies", lambda results, selected, finder: (seen.extend(selected), DepPlan(items=[]))[1])
    cli.main(["--mods-dir", str(d), "--lang", "es"])
    assert seen == [b] and a.pinned


def test_cli_report_shows_pinned():
    from mod_updater.report import status_label
    a = res("Mod", "pj", status=ACTUALIZABLE, new_version="3.0")
    a.pinned = True
    assert status_label(a) == "Fijado"


# ---------------------------------------------------------------- revisión final

def test_pin_survives_when_only_the_other_source_identifies_the_mod(tmp_path):
    from mod_updater.settings import load_settings
    a, d, r = make_api(tmp_path)
    r.source, r.project_id, r.known_ids = CF, "328085", {(CF, "328085"), (MR, "LNytGWDc")}
    a.pin_set(0, True)
    only_mr = res("Mod", "LNytGWDc")  # CurseForge caído: solo lo identifica Modrinth
    apply_pins([only_mr], load_settings(a._settings_file).pins)
    assert only_mr.pinned


def test_unpin_removes_every_matching_entry(tmp_path):
    from mod_updater.settings import load_settings, save_settings
    a, d, r = make_api(tmp_path)
    r.known_ids = {(MR, "pj"), (CF, "9")}
    s = load_settings(a._settings_file)
    s.pins = {"modrinth:pj": {"name": "Mod", "version": "1.0", "reason": ""},
              "curseforge:9": {"name": "Mod", "version": "1.0", "reason": ""}}
    save_settings(s, a._settings_file)
    a.pin_set(0, False)
    assert load_settings(a._settings_file).pins == {}


def test_versions_current_flag_follows_the_installed_file(tmp_path):
    a, d, r = make_api(tmp_path)
    assert [v["current"] for v in a.versions_for(0)["versions"]] == [False, False, True]
    r.current_file_id, r.mod.sha1 = "v2", "sv2"  # tras volver a 2.0 y revisar de nuevo
    assert [v["current"] for v in a.versions_for(0)["versions"]] == [False, True, False]
    assert a.rollback(0, "v1")["ok"]  # 1.0 vuelve a ser instalable


def test_undo_of_a_rollback_removes_the_pin_it_added(tmp_path, monkeypatch):
    from mod_updater import downloader
    from mod_updater.settings import load_settings
    a, d, r = make_api(tmp_path)
    monkeypatch.setattr(downloader, "download_verified", lambda res, dest, sf: make_jar(dest, "mod"))
    a.rollback(0, "v2")
    assert "modrinth:pj" in load_settings(a._settings_file).pins
    assert a.undo_last()["ok"] and files(d) == ["mod-1.0.jar"]
    assert load_settings(a._settings_file).pins == {}


def test_undo_of_a_rollback_restores_the_previous_pin(tmp_path, monkeypatch):
    from mod_updater import downloader
    from mod_updater.settings import load_settings
    a, d, r = make_api(tmp_path)
    a.pin_set(0, True, "motivo de antes")
    before = load_settings(a._settings_file).pins
    monkeypatch.setattr(downloader, "download_verified", lambda res, dest, sf: make_jar(dest, "mod"))
    a.rollback(0, "v2")
    a.undo_last()
    assert load_settings(a._settings_file).pins == before


def test_versions_for_offline_still_reports_the_pin(tmp_path):
    from mod_updater.net import ApiError
    a, d, r = make_api(tmp_path)
    a.pin_set(0, True, "x")

    class Offline(FakeMr):
        def project_versions(self, *x):
            raise ApiError("sin red", kind="offline")

    a._mr_factory = Offline
    out = a.versions_for(0)
    assert out["ok"] is False and out["pinned"] is True and out["reason"] == "x" and out["current"] == "1.0"


def test_broken_pinned_mod_still_needs_attention():
    from mod_updater.deps import Broken
    from mod_updater.gui.api import serialize
    a = res("Create", "1", status=ACTUALIZABLE, new_version="6.0.8")
    a.pinned = True
    row = serialize([a], DepPlan(items=[], broken=[Broken(a, "le falta Flywheel")]), allow_beta=False)["rows"][0]
    assert row["s"] == "manual"


def test_curseforge_versions_without_hash_are_not_installable(tmp_path):
    from mod_updater.curseforge import CfFile
    a, d, r = make_api(tmp_path)
    r.source, r.project_id, r.current_file_id = CF, "5", "1"
    f = lambda i, sha: CfFile(id=str(i), mod_id=5, display_name=f"v{i}", file_name=f"m{i}.jar", date_published=f"2026-0{i}-01",  # noqa: E731
                              version_type="release", download_url=f"https://edge.forgecdn.net/{i}.jar", sha1=sha, fingerprint=None)

    class Cf:
        def __init__(self, key):
            pass

        def mod_files(self, *x):
            return [f(1, "a"), f(2, None)]

    a._cf_factory, a._get_key = Cf, lambda: ("k", "keyring")
    vs = {v["version"]: v for v in a.versions_for(0)["versions"]}
    assert vs["v2"]["manual"] is True and vs["v1"]["current"] is True


def test_import_does_not_overwrite_an_existing_pin_reason(tmp_path, monkeypatch):
    from mod_updater import modlist as modlist_mod
    from mod_updater.settings import load_settings
    a, d, r = make_api(tmp_path)
    a.pin_set(0, True, "mi motivo")
    a._import = {"add": [], "update": [], "unavailable": [], "remove": [], "mismatch": None,
                 "same": [{"nombre": "Mod", "fuente": "modrinth", "proyecto": "pj", "version": "1.0", "fijado": True}]}
    monkeypatch.setattr(modlist_mod, "resolve_exact", lambda *x, **k: ([], []))
    a.modlist_import_start(False)
    assert load_settings(a._settings_file).pins["modrinth:pj"]["reason"] == "mi motivo"
