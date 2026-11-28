"""Hito 6 (v4): ¿puedo pasar a otra versión de Minecraft?"""

from pathlib import Path

import pytest

from mod_updater import i18n
from mod_updater.curseforge import CfFile
from mod_updater.migrate import check, compare_with_last
from mod_updater.modrinth import MrFile, MrVersion
from mod_updater.resolver import AL_DIA, CF, MR, Resolution
from mod_updater.scanner import ModFile

TARGET, LOADER = "1.21.4", "neoforge"
JEI_CF, EMI_CF, EMI_MR = 238222, 580555, "fRiHVvU7"  # IDs reales (solapamientos.json: grupo recetas)


def setup_module():
    i18n.set_language("es")


def inst(name, *, cf=None, mr=None, source=None, cats=("tecnologia",), updated="2026-01-01T00:00:00Z", disabled=False):
    fn = f"{name}.jar" + (".disabled" if disabled else "")
    mod = ModFile(path=Path(fn), file_name=fn, size=1, sha1=f"sha-{name}", sha512="", cf_fingerprint=0, mod_id=name.lower())
    ids = ({(CF, str(cf))} if cf else set()) | ({(MR, mr)} if mr else set())
    src = source or (CF if cf else MR if mr else None)
    pid = str(cf) if src == CF else mr
    return Resolution(mod=mod, status=AL_DIA, source=src, project_id=pid, project_name=name, categories=list(cats),
                      project_updated=updated, known_ids=ids)


def cf_file(fid, mod_id, name):
    return CfFile(id=str(fid), mod_id=mod_id, display_name=name, file_name=f"{name}.jar", date_published="2026-06-01",
                  version_type="release", download_url=f"https://edge.forgecdn.net/{fid}.jar", sha1="s", fingerprint=None,
                  size=10)


class FakeCf:
    def __init__(self, ready):  # ready: {mod_id: file_id} con versión para TARGET
        self.ready = ready

    def mods(self, ids):
        return {i: {"id": i, "name": f"Mod{i}", "latestFilesIndexes": (
            [{"gameVersion": TARGET, "modLoader": 6, "fileId": self.ready[i], "releaseType": 1}] if i in self.ready else
            [{"gameVersion": "1.21.1", "modLoader": 6, "fileId": 1, "releaseType": 1}])} for i in ids}

    def files(self, ids):
        return {str(i): cf_file(i, next(m for m, f in self.ready.items() if f == i), f"f{i}") for i in ids}


def mr_version(project, number):
    return MrVersion(id=f"v-{project}", project_id=project, name=number, version_number=number, version_type="release",
                     date_published="2026-06-01", files=[MrFile(url=f"https://cdn.modrinth.com/{project}.jar",
                                                                filename=f"{project}-{number}.jar", sha1="m", sha512="x",
                                                                size=5, primary=True)])


class FakeMr:
    def __init__(self, by_sha=(), projects=()):
        self.by_sha, self.projects_ok = dict(by_sha), set(projects)

    def latest_from_hashes(self, sha1s, loader, game_version):
        assert game_version == TARGET and loader == LOADER
        return {h: mr_version(p, "9.9") for h, p in self.by_sha.items() if h in sha1s}

    def project_versions(self, project_id, loader, game_version):
        return [mr_version(project_id, "1.0")] if project_id in self.projects_ok else []


def names(items):
    return sorted(i["name"] for i in items)


def test_groups_ready_missing_and_alternatives():
    mods = [
        inst("Listo", cf=1),                                     # CurseForge tiene versión para el destino
        inst("SoloModrinth", cf=2, mr="pm2"),                    # su fuente (CurseForge) no, Modrinth sí
        inst("Falta", cf=3, updated="2025-03-10T00:00:00Z"),     # ninguna web
        inst("JEI", cf=JEI_CF),                                  # no está, pero EMI (mismo grupo) sí
        inst("Balm", cf=5, cats=("librerias",)),                 # librería: aparte
        inst("Apagado", cf=6, disabled=True),                    # desactivado: no cuenta
    ]
    out = check(mods, target=TARGET, loader=LOADER, curseforge=FakeCf({1: 101, EMI_CF: 900}),
                modrinth=FakeMr(by_sha={"sha-SoloModrinth": "pm2"}), finder=DepFinder({}))
    assert names(out["ready"]) == ["Listo"]
    assert names(out["alternative"]) == ["JEI", "SoloModrinth"]
    alt = {a["name"]: a for a in out["alternative"]}
    assert alt["SoloModrinth"]["via"] == "Modrinth" and alt["JEI"]["instead"] == "EMI"
    assert out["missing"] == [{"name": "Falta", "key": "curseforge:3", "date": "2025-03-10T00:00:00Z", "why": ""}]
    assert out["total"] == 4 and out["ready_count"] == 1


def test_install_items_for_the_new_profile():
    mods = [inst("Listo", cf=1), inst("SoloModrinth", cf=2, mr="pm2")]
    out = check(mods, target=TARGET, loader=LOADER, curseforge=FakeCf({1: 101}), modrinth=FakeMr(by_sha={"sha-SoloModrinth": "pm2"}),
                finder=DepFinder({}))
    files = sorted(r.new_file_name for r in out["install"])
    assert files == ["f101.jar", "pm2-9.9.jar"]
    assert all(r.mod is None and r.download_url for r in out["install"])


def test_without_curseforge_key_only_modrinth():
    mods = [inst("A", cf=1, mr="pa"), inst("B", cf=2)]
    out = check(mods, target=TARGET, loader=LOADER, curseforge=None, modrinth=FakeMr(by_sha={"sha-A": "pa"}), finder=DepFinder({}))
    assert names(out["alternative"]) == ["A"] and names(out["missing"]) == ["B"] and out["no_curseforge"] is True


def test_compare_with_last_result():
    now = {"target": TARGET, "ready": ["curseforge:1", "curseforge:2", "modrinth:x"]}
    assert compare_with_last(now, {"target": TARGET, "ready": ["curseforge:1"]}) == 2
    assert compare_with_last(now, {"target": "1.21.3", "ready": []}) is None
    assert compare_with_last(now, None) is None


# ---------------------------------------------------------------- punto de control C

class DepFinder:
    """Para las dependencias de las versiones nuevas: `catalog` {(fuente, id): Resolution o None}."""

    def __init__(self, catalog):
        self.catalog = catalog

    def find(self, dep):
        return self.catalog.get(dep.key)

    def version_date(self, dep):
        return None

    def describe(self, dep):
        return dep.id


def lib_candidate(name, pid, url=True):
    from mod_updater.resolver import ACTUALIZABLE, DESCARGA_MANUAL, INSTALL
    return Resolution(mod=None, kind=INSTALL, status=ACTUALIZABLE if url else DESCARGA_MANUAL, source=MR, project_id=pid,
                      project_name=name, new_version="1.0", new_file_name=f"{pid}.jar",
                      download_url="https://cdn.modrinth.com/l.jar" if url else None, known_ids={(MR, pid)})


class DepsMr(FakeMr):
    """La versión nueva de cada mod pide las dependencias de `deps` {proyecto: [ids de Modrinth]}."""

    def __init__(self, by_sha, deps, projects=()):
        super().__init__(by_sha=by_sha, projects=projects)
        self.deps = deps

    def latest_from_hashes(self, sha1s, loader, game_version):
        out = super().latest_from_hashes(sha1s, loader, game_version)
        for v in out.values():
            v.dependencies = [{"project_id": d, "dependency_type": "required"} for d in self.deps.get(v.project_id, [])]
        return out


def test_needed_libraries_are_included_and_counted():
    mods = [inst("A", mr="pa"), inst("B", mr="pb"), inst("Vieja", mr="pv", cats=("librerias",))]
    out = check(mods, target=TARGET, loader=LOADER, curseforge=None,
                modrinth=DepsMr({"sha-A": "pa", "sha-B": "pb", "sha-Vieja": "pv"}, {"pa": ["lib1"], "pb": ["lib1"]}),
                finder=DepFinder({(MR, "lib1"): lib_candidate("Lib1", "lib1")}))
    assert names(out["ready"]) == ["A", "B"]
    assert sorted(r.new_file_name for r in out["install"]) == ["lib1.jar", "pa-9.9.jar", "pb-9.9.jar"]
    assert out["install_mods"] == 2 and out["install_libs"] == 1  # "Vieja" no la necesita nadie: no va


def test_a_mod_whose_library_is_missing_is_not_ready():
    mods = [inst("A", mr="pa"), inst("B", mr="pb")]
    out = check(mods, target=TARGET, loader=LOADER, curseforge=None,
                modrinth=DepsMr({"sha-A": "pa", "sha-B": "pb"}, {"pa": ["nolib"]}),
                finder=DepFinder({(MR, "nolib"): lib_candidate("NoLib", "nolib", url=False)}))
    assert names(out["ready"]) == ["B"] and names(out["missing"]) == ["A"]
    assert "NoLib" in out["missing"][0]["why"]
    assert [r.new_file_name for r in out["install"]] == ["pb-9.9.jar"]


def test_other_mod_alternatives_are_optional():
    mods = [inst("JEI", cf=JEI_CF), inst("Listo", cf=1)]
    out = check(mods, target=TARGET, loader=LOADER, curseforge=FakeCf({1: 101, EMI_CF: 900}), modrinth=FakeMr(),
                finder=DepFinder({}))
    alt = out["alternative"][0]
    assert alt["instead"] == "EMI" and alt["optional"] == f"curseforge:{EMI_CF}"
    assert [r.new_file_name for r in out["install"]] == ["f101.jar"]  # EMI no entra por defecto
    assert [r.new_file_name for r in out["optional"][f"curseforge:{EMI_CF}"]] == ["f900.jar"]


def test_wont_have_lists_everything_left_out():
    mods = [inst("Falta", cf=3), inst("JEI", cf=JEI_CF), inst("SinFuente"), inst("Listo", cf=1)]
    out = check(mods, target=TARGET, loader=LOADER, curseforge=FakeCf({1: 101, EMI_CF: 900}), modrinth=FakeMr(),
                finder=DepFinder({}))
    assert out["wont_have"] == ["Falta", "JEI", "SinFuente"]


# ---------------------------------------------------------------- API

def make_api(tmp_path, monkeypatch, fake_result):
    from mod_updater import migrate as migrate_mod
    from mod_updater.gui.api import Api
    from mod_updater.settings import Settings, save_settings
    from test_toggle import make_jar, res_for
    d = tmp_path / "juego" / "mods"
    d.mkdir(parents=True)
    make_jar(d / "listo.jar", "listo")
    f = tmp_path / "s.json"
    save_settings(Settings(mods_dir=str(d), setup_done=True, minecraft_version="1.21.1"), f)
    a = Api(f, get_key=lambda: (None, None), run_async=lambda fn: fn(), cache_dir=tmp_path / "c", running=lambda g: [])
    r = res_for(d / "listo.jar")
    r.source, r.project_id, r.project_name = CF, "1", "Listo"
    a._results, a._rows, a._row_s = [r], [r], ["ok"]
    calls = []
    monkeypatch.setattr(migrate_mod, "check", lambda results, **k: (calls.append(k["target"]), fake_result(k["target"]))[1])
    return a, d, calls


def fake(target, ready=("curseforge:1",)):
    from mod_updater.resolver import ACTUALIZABLE, INSTALL
    inst_ = Resolution(mod=None, kind=INSTALL, status=ACTUALIZABLE, source=CF, project_id="1", project_name="Listo",
                       new_version="2.0", new_file_name="listo-2.0.jar", download_url="https://edge.forgecdn.net/l.jar",
                       new_sha1="s")
    return {"target": target, "ready": [{"name": "Listo", "key": k} for k in ready], "alternative": [], "missing": [],
            "libs": [], "total": len(ready), "ready_count": len(ready), "no_curseforge": False, "install": [inst_]}


def test_api_check_saves_the_result_and_compares_next_time(tmp_path, monkeypatch):
    from mod_updater.settings import load_settings
    results = iter([fake(TARGET, ready=("curseforge:1",)), fake(TARGET, ready=("curseforge:1", "curseforge:2", "modrinth:z"))])
    a, d, calls = make_api(tmp_path, monkeypatch, lambda target: next(results))
    first = a.migrate_check(TARGET)
    assert first["ok"] and first["ready_count"] == 1 and first["delta"] is None and "install" not in first
    assert load_settings(a._settings_file).migration_last["ready"] == ["curseforge:1"]
    assert a.migrate_check(TARGET)["delta"] == 2


def test_api_check_rejects_the_current_version_and_needs_a_scan(tmp_path, monkeypatch):
    a, d, calls = make_api(tmp_path, monkeypatch, fake)
    assert not a.migrate_check("1.21.1")["ok"]
    a._results = []
    assert not a.migrate_check(TARGET)["ok"] and calls == []


def test_api_create_profile_downloads_into_a_new_folder_without_touching_the_current(tmp_path, monkeypatch):
    from mod_updater import downloader
    from mod_updater.settings import load_settings
    from test_toggle import make_jar
    a, d, calls = make_api(tmp_path, monkeypatch, fake)
    a.migrate_check(TARGET)
    before = sorted(p.name for p in d.iterdir())
    new_game = tmp_path / "nueva"
    a._folder_dialog = lambda: str(new_game)
    monkeypatch.setattr(downloader, "download_verified", lambda res, dest, sf: make_jar(dest, "listo"))
    out = a.migrate_create()
    assert out["ok"] and out["rows"]
    assert sorted(p.name for p in (new_game / "mods").iterdir()) == ["listo-2.0.jar"]
    assert sorted(p.name for p in d.iterdir()) == before  # el perfil actual no se toca
    s = load_settings(a._settings_file)
    new = next(p for p in s.profiles if p["mods_dir"] == str(new_game / "mods"))
    assert new["minecraft_version"] == TARGET and s.mods_dir == str(d)  # sigue activo el de antes


def test_api_create_refuses_a_folder_with_mods(tmp_path, monkeypatch):
    from test_toggle import make_jar
    a, d, calls = make_api(tmp_path, monkeypatch, fake)
    a.migrate_check(TARGET)
    busy = tmp_path / "ocupada"
    (busy / "mods").mkdir(parents=True)
    make_jar(busy / "mods" / "x.jar", "x")
    a._folder_dialog = lambda: str(busy)
    assert not a.migrate_create()["ok"]
    a._folder_dialog = lambda: str(d)  # ni la carpeta del perfil actual
    assert not a.migrate_create()["ok"]


def test_api_create_does_not_offer_undo_nor_wipe_the_current_scan(tmp_path, monkeypatch):
    from mod_updater import downloader
    from test_toggle import make_jar
    a, d, calls = make_api(tmp_path, monkeypatch, fake)
    events = []
    a._emit = lambda e, p: events.append((e, p))
    a.migrate_check(TARGET)
    a._folder_dialog = lambda: str(tmp_path / "nueva")
    monkeypatch.setattr(downloader, "download_verified", lambda res, dest, sf: make_jar(dest, "listo"))
    out = a.migrate_create([])
    done = next(p for e, p in events if e == "apply_done")
    assert done["no_undo"] is True and done["created"]["folder"] == str(tmp_path / "nueva" / "mods")
    assert a._results  # la revisión del perfil actual sigue valiendo
    assert any(p["mods_dir"] == str(tmp_path / "nueva" / "mods") for p in out["state"]["profiles"])


def test_api_create_with_a_chosen_alternative(tmp_path, monkeypatch):
    from mod_updater import downloader
    from mod_updater.gui import api as api_mod
    from mod_updater.resolver import ACTUALIZABLE, INSTALL
    from test_toggle import make_jar

    def with_alt(target):
        r = fake(target)
        emi = Resolution(mod=None, kind=INSTALL, status=ACTUALIZABLE, source=CF, project_id=str(EMI_CF), project_name="EMI",
                         new_version="1", new_file_name="emi.jar", download_url="https://edge.forgecdn.net/e.jar", new_sha1="s")
        r["optional"] = {f"curseforge:{EMI_CF}": [emi]}
        return r

    a, d, calls = make_api(tmp_path, monkeypatch, with_alt)
    monkeypatch.setattr(api_mod, "DependencyFinder", lambda *x, **k: DepFinder({}))
    a.migrate_check(TARGET)
    a._folder_dialog = lambda: str(tmp_path / "nueva")
    monkeypatch.setattr(downloader, "download_verified", lambda res, dest, sf: make_jar(dest, "x"))
    assert a.migrate_create([f"curseforge:{EMI_CF}"])["ok"]
    assert sorted(p.name for p in (tmp_path / "nueva" / "mods").iterdir()) == ["emi.jar", "listo-2.0.jar"]


def test_api_create_releases_the_lock_on_errors(tmp_path, monkeypatch):
    from mod_updater import profiles
    a, d, calls = make_api(tmp_path, monkeypatch, fake)
    a.migrate_check(TARGET)
    a._folder_dialog = lambda: str(tmp_path / "nueva")
    monkeypatch.setattr(profiles, "add", lambda *x, **k: (_ for _ in ()).throw(OSError("disco lleno")))
    assert a.migrate_create([])["ok"] is False and not a._busy.locked()


def test_api_switching_profile_forgets_the_check(tmp_path, monkeypatch):
    a, d, calls = make_api(tmp_path, monkeypatch, fake)
    a.migrate_check(TARGET)
    a._reset_session()
    assert a.migrate_create([])["ok"] is False
