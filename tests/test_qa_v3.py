"""Regresiones de la pasada de QA del plan v3 (informe en qa-bug-hunt/, no versionado)."""

import json
import time
from dataclasses import replace
from pathlib import Path

import pytest

from mod_updater import profiles
from mod_updater.changelog import sanitize_html
from mod_updater.curseforge import CfFile
from mod_updater.deps import plan_with_dependencies
from mod_updater.gui.api import Api
from mod_updater.knowledge import load_knowledge
from mod_updater.launchers import detect_instances
from mod_updater.modlist import ModlistError, build, dumps, parse, resolve_exact
from mod_updater.resolver import ACTUALIZABLE, AL_DIA, CF, INSTALL, REMOVE, Dep, Resolution
from mod_updater.scanner import ModFile
from mod_updater.settings import Settings, load_settings, save_settings
from mod_updater.suggest import suggest


def inst(name, folder, pid="1", source=CF, file_id="100", updated="2026-10-01T00:00:00Z", cats=("tecnologia",)):
    p = Path(folder) / f"{name}.jar"
    p.write_bytes(name.encode())
    mod = ModFile(path=p, file_name=p.name, size=1, sha1=f"sha-{name}", sha512="", cf_fingerprint=0, mod_id=name.lower())
    return Resolution(mod=mod, status=AL_DIA, source=source, project_id=pid, project_name=name, current_version="1.0",
                      current_file_id=file_id, project_updated=updated, version_updated=updated, categories=list(cats),
                      known_ids={(source, pid)} if source else set())


def make_api(tmp_path, mods):
    f = tmp_path / "s.json"
    save_settings(Settings(mods_dir=str(mods), setup_done=True), f)
    return Api(f, get_key=lambda: (None, None), run_async=lambda fn: fn(), cache_dir=tmp_path / "c", running=lambda d: [])


# ---------------------------------------------------------------- lista de mods (PL-1, PL-2)


def test_import_rejects_file_from_another_project(tmp_path):
    create = inst("Create", tmp_path, pid="328085", file_id="5001")
    other = CfFile(id="7777", mod_id=999999, display_name="Otro 1.0", file_name="otromod-1.0.jar", date_published="2026",
                   version_type="release", download_url="https://edge.forgecdn.net/o.jar", sha1="s", fingerprint=None)

    class Cf:
        def files(self, ids): return {"7777": other}
        def mods(self, ids): return {}
    changes = {"add": [], "update": [{"nombre": "Create", "fuente": CF, "proyecto": 328085, "archivo": 7777, "version": "6.0"}]}
    chosen, manual = resolve_exact(changes, [create], curseforge=Cf(), modrinth=None)
    assert chosen == [] and manual[0]["name"] == "Create"


@pytest.mark.parametrize("mod", [{"nombre": "X", "fuente": "curseforge", "archivo": 1},
                                 {"nombre": "X", "fuente": "curseforge", "proyecto": 9, "archivo": "abc"},
                                 {"nombre": "X", "fuente": "modrinth", "proyecto": "", "archivo": "v"}])
def test_malformed_entries_rejected_on_parse(mod):
    with pytest.raises(ModlistError):
        parse(json.dumps({"formato": 1, "minecraft": "1.21.1", "cargador": "neoforge", "mods": [mod]}))


def test_import_start_removes_first(tmp_path, monkeypatch):
    from mod_updater.gui import api as api_mod
    mods = tmp_path / "mods"
    mods.mkdir()
    a = make_api(tmp_path, mods)
    a._results = [inst("jei", mods, source=None)]
    lista = tmp_path / "l.modlist.json"
    lista.write_text(dumps(build([inst("JEI", tmp_path, pid="238222", file_id="1")], minecraft="1.21.1",
                                 loader="neoforge", app="x")), encoding="utf-8")
    a._file_dialog = lambda *x, **k: str(lista)
    assert a.modlist_import()["ok"]
    new = Resolution(mod=None, kind=INSTALL, status=ACTUALIZABLE, source=CF, project_id="238222", project_name="JEI",
                     new_file_name="jei.jar", download_url="https://edge.forgecdn.net/j.jar")
    monkeypatch.setattr(api_mod.modlist_mod, "resolve_exact", lambda *x, **k: ([new], []))
    order = []
    a._apply = lambda chosen, s, index: order.extend(r.kind for r in chosen)
    assert a.modlist_import_start(remove=True)["ok"] and order == [REMOVE, INSTALL]


def test_list_needs_a_new_scan_after_applying(tmp_path):
    mods = tmp_path / "mods"
    mods.mkdir()
    a = make_api(tmp_path, mods)
    a._emit = lambda *x: None
    a._results = [inst("Create", mods), inst("Viejo", mods, pid="2")]
    rm = replace(a._results[1], kind=REMOVE)
    assert a._busy.acquire(blocking=False)
    a._apply([rm], a._settings(), {id(rm): 0})
    assert a.modlist_export("modlist")["ok"] is False and a.copy_list()["ok"] is False


# ---------------------------------------------------------------- perfiles (PL-3, PL-5, PL-9)


def test_profile_remove_and_settings_refused_while_busy(tmp_path):
    a_mods, b_mods = tmp_path / "a", tmp_path / "b"
    a_mods.mkdir()
    b_mods.mkdir()
    a = make_api(tmp_path, a_mods)
    pid = a.profile_add({"mods_dir": str(b_mods)})["id"]
    assert a._busy.acquire(blocking=False)
    assert a.profile_remove(pid)["ok"] is False
    assert a.save_setup({"mods_dir": str(b_mods), "loader": "neoforge", "minecraft_version": "1.21.1"})["ok"] is False
    a._busy.release()
    assert a.profile_remove(pid)["ok"] is True


def test_new_profile_starts_with_its_own_answers():
    s = Settings(mods_dir="C:/a", setup_done=True, answers={"styles": ["magia"]})
    profiles.ensure(s)
    pid = profiles.add(s, name="B", mods_dir="C:/b", minecraft_version="1.21.1", loader="neoforge")
    profiles.switch(s, pid)
    assert s.answers == {}


def test_settings_with_broken_profiles_still_load(tmp_path):
    f = tmp_path / "s.json"
    f.write_text(json.dumps({"mods_dir": "C:/a/mods", "setup_done": True,
                             "profiles": [{"name": "sin id"}, "basura", {"id": "ok", "name": "Bueno", "mods_dir": "C:/a/mods"}]}),
                 encoding="utf-8")
    s = load_settings(f)
    assert [p["id"] for p in s.profiles] == ["ok"]


# ---------------------------------------------------------------- launchers y aviso de versión (PL-7, PL-8)


def test_detection_survives_unexpected_json_shapes(tmp_path):
    (tmp_path / ".minecraft").mkdir()
    (tmp_path / ".minecraft" / "launcher_profiles.json").write_text('{"profiles": [1, 2]}', encoding="utf-8")
    inst_dir = tmp_path / "PrismLauncher" / "instances" / "X"
    (inst_dir / "minecraft" / "mods").mkdir(parents=True)
    (inst_dir / "instance.cfg").write_text("name=X\n", encoding="utf-8")
    (inst_dir / "mmc-pack.json").write_text('{"components": ["net.minecraft", 5]}', encoding="utf-8")
    assert [i["name"] for i in detect_instances(appdata=tmp_path, home=tmp_path / "h")] == ["X"]


def test_update_cache_from_the_future_or_wrong_type_is_ignored(tmp_path):
    from mod_updater.app_update import check_latest
    calls = []

    class S:
        def get(self, url, **kw):
            calls.append(url)
            raise OSError("sin red")
    cache = tmp_path / "u.json"
    cache.write_text(json.dumps({"checked": time.time() + 10 * 86400, "latest": {"version": "9.0.0"}}), encoding="utf-8")
    check_latest("0.3.0", cache_path=cache, session=S())
    assert calls  # una fecha futura no bloquea las comprobaciones
    cache.write_text(json.dumps({"checked": time.time(), "latest": ["x"]}), encoding="utf-8")
    assert check_latest("0.3.0", cache_path=cache, session=type("S2", (), {"get": lambda *a, **k: (_ for _ in ()).throw(ValueError())})()) is None


# ---------------------------------------------------------------- motor (M1, M2, M3)


def test_dependency_chosen_together_with_its_parent_appears_once():
    lib_key = (CF, "50")

    def cand(name, pid, deps=()):
        return Resolution(mod=None, kind=INSTALL, status=ACTUALIZABLE, source=CF, project_id=pid, project_name=name,
                          new_file_name=f"{name}.jar", download_url="https://edge.forgecdn.net/x.jar",
                          new_deps=list(deps), known_ids={(CF, pid)})

    class Finder:  # como el real: un objeto nuevo en cada búsqueda
        def find(self, dep):
            return cand("LibX", "50") if dep.key == lib_key else None

        def version_date(self, dep):
            return None
    addon, lib = cand("AddonY", "40", deps=[Dep(CF, "50")]), cand("LibX", "50")
    plan = plan_with_dependencies([], [addon, lib], Finder())
    assert sorted(r.name for r in plan.items) == ["AddonY", "LibX"]


def test_abandoned_without_alternative_goes_to_review_not_remove(tmp_path):
    kb = load_knowledge()
    old_map = inst("JourneyMap", tmp_path, pid="32274", updated="2024-01-01T00:00:00Z", cats=("mapas",))

    class F:
        def find(self, dep): return None
    r = suggest({"styles": [], "difficulty": "normal", "pc": "potente"}, [old_map], F(), knowledge=kb)
    assert [x["name"] for x in r["review"]] == ["JourneyMap"] and r["remove"] == []
    xaero = inst("Xaero's Minimap", tmp_path, pid="263420", updated="2024-01-01T00:00:00Z", cats=("mapas",))
    jm = inst("JourneyMap", tmp_path, pid="32274", cats=("mapas",))
    r = suggest({"styles": [], "difficulty": "normal", "pc": "potente"}, [xaero, jm], F(), knowledge=kb)
    assert len(r["remove"]) == 1  # nunca los dos minimapas


@pytest.mark.parametrize("url", ["https://evil.example\\@cdn.modrinth.com/p.png", "https://x@cdn.modrinth.com/p.png",
                                 "https://cdn.modrinth.com/a b.png"])
def test_image_urls_with_tricks_are_dropped(url):
    assert "img" not in sanitize_html(f'<p>x</p><img src="{url}">')
