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
                modrinth=FakeMr(by_sha={"sha-SoloModrinth": "pm2"}))
    assert names(out["ready"]) == ["Listo"]
    assert names(out["alternative"]) == ["JEI", "SoloModrinth"]
    alt = {a["name"]: a for a in out["alternative"]}
    assert alt["SoloModrinth"]["via"] == "Modrinth" and alt["JEI"]["instead"] == "EMI"
    assert out["missing"] == [{"name": "Falta", "key": "curseforge:3", "date": "2025-03-10T00:00:00Z", "lib": False}]
    assert [lib["name"] for lib in out["libs"]] == ["Balm"] and out["libs"][0]["ok"] is False
    assert out["total"] == 4 and out["ready_count"] == 1


def test_install_items_for_the_new_profile():
    mods = [inst("Listo", cf=1), inst("SoloModrinth", cf=2, mr="pm2")]
    out = check(mods, target=TARGET, loader=LOADER, curseforge=FakeCf({1: 101}), modrinth=FakeMr(by_sha={"sha-SoloModrinth": "pm2"}))
    files = sorted(r.new_file_name for r in out["install"])
    assert files == ["f101.jar", "pm2-9.9.jar"]
    assert all(r.mod is None and r.download_url for r in out["install"])


def test_without_curseforge_key_only_modrinth():
    mods = [inst("A", cf=1, mr="pa"), inst("B", cf=2)]
    out = check(mods, target=TARGET, loader=LOADER, curseforge=None, modrinth=FakeMr(by_sha={"sha-A": "pa"}))
    assert names(out["alternative"]) == ["A"] and names(out["missing"]) == ["B"] and out["no_curseforge"] is True


def test_compare_with_last_result():
    now = {"target": TARGET, "ready": ["curseforge:1", "curseforge:2", "modrinth:x"]}
    assert compare_with_last(now, {"target": TARGET, "ready": ["curseforge:1"]}) == 2
    assert compare_with_last(now, {"target": "1.21.3", "ready": []}) is None
    assert compare_with_last(now, None) is None


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
