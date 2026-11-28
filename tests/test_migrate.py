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
