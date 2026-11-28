"""Issue #12 (S3): no quitar un mod que necesita algo que se queda o que se va a añadir."""

from pathlib import Path

from mod_updater import i18n
from mod_updater.deps import keep_needed
from mod_updater.resolver import ACTUALIZABLE, AL_DIA, CF, INSTALL, MR, Dep, Resolution
from mod_updater.scanner import ModFile

BALM, WAYSTONES = "531761", "245755"  # IDs reales de CurseForge


def setup_module():
    i18n.set_language("es")


def inst(name, pid, *, deps=(), requires=(), mod_id=None, source=CF):
    mod = ModFile(path=Path(f"{name}.jar"), file_name=f"{name}.jar", size=1, sha1=name, sha512="",
                  cf_fingerprint=0, mod_id=mod_id or name.lower(), requires=list(requires))
    return Resolution(mod=mod, status=AL_DIA, source=source, project_id=pid, project_name=name,
                      current_deps=list(deps), known_ids={(source, pid)})


def new(name, pid, *, deps=()):
    return Resolution(mod=None, kind=INSTALL, status=ACTUALIZABLE, source=CF, project_id=pid, project_name=name,
                      new_version="1.0", download_url="https://edge.forgecdn.net/x.jar", new_deps=list(deps),
                      known_ids={(CF, pid)})


def names(items):
    return sorted(r.name for r in items)


def test_s3_adding_a_mod_keeps_the_dependency_marked_for_removal():
    balm = inst("Balm", BALM)
    results = [balm, inst("JEI", "238222")]
    waystones = new("Waystones", WAYSTONES, deps=[Dep(CF, BALM)])
    removals, notes = keep_needed(results, [balm], [waystones])
    assert removals == []
    assert notes == ["No se quita Balm: lo necesita Waystones, que vas a añadir."]


def test_indirect_dependency_is_kept_too():
    c = inst("C", "3")
    b = inst("B", "2", deps=[Dep(CF, "3")])
    a = new("A", "1", deps=[Dep(CF, "2")])
    removals, notes = keep_needed([b, c], [b, c], [a])
    assert removals == []
    assert notes == ["No se quita B: lo necesita A, que vas a añadir.", "No se quita C: lo necesita B."]


def test_two_removed_mods_that_need_each_other_are_both_removed():
    b = inst("B", "2", deps=[Dep(CF, "3")])
    c = inst("C", "3", deps=[Dep(CF, "2")])
    other = inst("Otro", "9")
    removals, notes = keep_needed([b, c, other], [b, c])
    assert names(removals) == ["B", "C"] and notes == []


def test_installed_mod_that_stays_keeps_its_library():
    lib = inst("Lib", "5")
    user = inst("Usa", "6", deps=[Dep(CF, "5")])
    user2 = inst("Usa2", "7", deps=[Dep(CF, "5")])
    removals, notes = keep_needed([lib, user, user2], [lib])
    assert removals == [] and notes == ["No se quita Lib: lo necesitan Usa, Usa2."]


def test_mods_toml_requires_counts_as_a_dependency():
    lib = inst("Cloth Config", "8", mod_id="cloth_config")
    user = inst("Algo", "9", requires=["cloth_config"])
    removals, _ = keep_needed([lib, user], [lib])
    assert removals == []


def test_dependency_by_other_source_id():
    lib = inst("Balm", BALM)
    lib.known_ids.add((MR, "balm-mr"))
    adding = new("Nuevo", "10", deps=[Dep(MR, "balm-mr")])
    assert keep_needed([lib], [lib], [adding])[0] == []


def test_updated_mod_uses_its_new_dependencies():
    old_lib = inst("ViejaLib", "11")
    m = inst("Mod", "12", deps=[Dep(CF, "11")])
    m.status, m.new_deps = ACTUALIZABLE, []  # la versión nueva ya no la pide
    removals, _ = keep_needed([old_lib, m], [old_lib], [m])
    assert removals == [old_lib]


def test_nothing_changes_without_conflict():
    a, b = inst("A", "1"), inst("B", "2")
    removals, notes = keep_needed([a, b], [a], [new("C", "3")])
    assert removals == [a] and notes == []


# ---------------------------------------------------------------- a través de la API

class Finder:
    def __init__(self, catalog):
        self.catalog = catalog

    def find(self, dep):
        return self.catalog.get(dep.key)

    def version_date(self, dep):
        return None

    def describe(self, dep):
        return dep.id


def _api(tmp_path, monkeypatch, results, catalog):
    from mod_updater.gui import api as api_mod
    from mod_updater.gui.api import Api
    from mod_updater.settings import Settings, save_settings
    mods = tmp_path / "mods"
    mods.mkdir()
    f = tmp_path / "s.json"
    save_settings(Settings(mods_dir=str(mods), setup_done=True), f)
    a = Api(f, get_key=lambda: (None, None), run_async=lambda fn: fn(), cache_dir=tmp_path / "c", running=lambda d: [])
    a._results = results
    monkeypatch.setattr(api_mod, "DependencyFinder", lambda *x, **k: Finder(catalog))
    return a


def test_suggest_plan_s3(tmp_path, monkeypatch):
    balm = inst("Balm", BALM)
    waystones = new("Waystones", WAYSTONES, deps=[Dep(CF, BALM)])
    a = _api(tmp_path, monkeypatch, [balm, inst("JEI", "238222")], {(CF, WAYSTONES): waystones})
    plan = a.suggest_plan({"add": [{"source": CF, "id": WAYSTONES, "name": "Waystones"}], "remove": ["Balm.jar", "JEI.jar"]})
    assert plan["ok"]
    assert [(r["s"], r["name"]) for r in plan["rows"]] == [("dep", "Waystones"), ("rm", "JEI")]
    assert plan["removals"] == ["JEI"]
    assert plan["kept"] == ["No se quita Balm: lo necesita Waystones, que vas a añadir."]
    started = []
    a._apply = lambda chosen, s, index: started.append([(r.name, r.kind) for r in chosen])
    assert a.install_start()["ok"] and started == [[("Waystones", INSTALL), ("JEI", "remove")]]


def test_suggest_plan_without_conflict_has_no_kept(tmp_path, monkeypatch):
    a = _api(tmp_path, monkeypatch, [inst("JEI", "238222")], {})
    plan = a.suggest_plan({"add": [], "remove": ["JEI.jar"]})
    assert plan["removals"] == ["JEI"] and plan["kept"] == []


def test_modlist_import_does_not_offer_removing_a_needed_library(tmp_path, monkeypatch):
    from mod_updater import modlist as modlist_mod
    lib, user = inst("Balm", BALM), inst("Waystones", WAYSTONES, deps=[Dep(CF, BALM)])
    extra = inst("Sobra", "99")
    a = _api(tmp_path, monkeypatch, [lib, user, extra], {})
    monkeypatch.setattr(modlist_mod, "parse", lambda text: {})
    monkeypatch.setattr(modlist_mod, "compare", lambda data, results, **k: {
        "mismatch": None, "add": [], "update": [], "same": [user], "unavailable": [], "remove": [lib, extra]})
    path = tmp_path / "x.modlist.json"
    path.write_text("{}", encoding="utf-8")
    a._file_dialog = lambda *x, **k: str(path)
    res = a.modlist_import()
    assert res["ok"] and [r["name"] for r in res["remove"]] == ["Sobra"]
    assert res["kept"] == ["No se quita Balm: lo necesita Waystones."]
    assert a._import["remove"] == [extra]
