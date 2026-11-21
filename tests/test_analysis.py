"""Análisis de la colección: datos nuevos del escáner y del resolver, y cálculo de cifras."""

import io
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from mod_updater.analysis import analyze
from mod_updater.resolver import ACTUALIZABLE, AL_DIA, CF, DESCARGA_MANUAL, MR, NO_ENCONTRADO, Dep, Resolution
from mod_updater.scanner import ModFile, read_metadata

NOW = datetime(2026, 11, 21, tzinfo=timezone.utc).timestamp()


def jar(files: dict) -> zipfile.ZipFile:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, text in files.items():
            z.writestr(name, text)
    buf.seek(0)
    return zipfile.ZipFile(buf)


# --------------------------------------------------------------------------- escáner


def test_neoforge_required_dependencies():
    toml = '''
[[mods]]
modId = "jei"
version = "19.0"
[[dependencies.jei]]
modId = "neoforge"
type = "required"
[[dependencies.jei]]
modId = "minecraft"
type = "required"
[[dependencies.jei]]
modId = "mezzconfig"
type = "required"
[[dependencies.jei]]
modId = "emi"
type = "optional"
'''
    meta = read_metadata(jar({"META-INF/neoforge.mods.toml": toml}))
    assert meta["requires"] == ["mezzconfig"]


def test_forge_mandatory_dependencies():
    toml = '''
[[mods]]
modId = "create"
[[dependencies.create]]
modId = "flywheel"
mandatory = true
[[dependencies.create]]
modId = "forge"
mandatory = true
[[dependencies.create]]
modId = "jei"
mandatory = false
'''
    assert read_metadata(jar({"META-INF/mods.toml": toml}))["requires"] == ["flywheel"]


def test_fabric_dependencies_and_environment():
    data = {"id": "sodium", "name": "Sodium", "version": "0.6", "environment": "client",
            "depends": {"minecraft": "1.21.1", "fabricloader": ">=0.16", "fabric-api": "*", "java": ">=21"}}
    meta = read_metadata(jar({"fabric.mod.json": json.dumps(data)}))
    assert meta["requires"] == ["fabric-api"] and meta["side"] == "client"
    data["environment"] = "*"
    assert read_metadata(jar({"fabric.mod.json": json.dumps(data)}))["side"] == "both"


# --------------------------------------------------------------------------- análisis


def mod(name, *, cats=(), status=AL_DIA, source=CF, pid=None, size=1_000_000, updated="2026-06-01T00:00:00Z",
        deps=(), requires=(), mod_id=None, side=None):
    m = ModFile(path=Path(f"{name}.jar"), file_name=f"{name}.jar", size=size, sha1=name, sha512="",
                cf_fingerprint=0, mod_id=mod_id or name.lower(), requires=list(requires))
    pid = pid or name
    return Resolution(mod=m, status=status, source=source, project_id=pid, project_name=name,
                      categories=list(cats), project_updated=updated, current_deps=list(deps),
                      known_ids={(source, pid)} if source else set(), side=side)


def test_counts_by_category_without_libraries():
    data = analyze([
        mod("Create", cats=["tecnologia"]), mod("Mekanism", cats=["tecnologia", "almacenamiento"]),
        mod("Waystones", cats=["calidad_vida"]), mod("Balm", cats=["librerias"]),
        mod("Raro", cats=[], source=None, status=NO_ENCONTRADO),
    ], now=NOW)
    bars = {b["cat"]: b for b in data["by_category"]}
    assert bars["tecnologia"]["count"] == 2 and bars["tecnologia"]["mods"] == ["Create", "Mekanism"]
    assert bars["otras"]["count"] == 1  # sin datos: cuenta en Otras
    assert "librerias" not in bars
    assert [b["cat"] for b in data["by_category"]][0] == "tecnologia"  # de más a menos
    assert data["totals"]["mods"] == 5 and data["totals"]["libraries"] == 1


def test_libraries_included_on_request():
    data = analyze([mod("Create", cats=["tecnologia"]), mod("Balm", cats=["librerias"])],
                   include_libraries=True, now=NOW)
    assert {b["cat"] for b in data["by_category"]} == {"tecnologia", "librerias"}


def test_totals_sources_and_status():
    data = analyze([
        mod("A", cats=["magia"], status=ACTUALIZABLE, size=2_000_000),
        mod("B", cats=["magia"], status=DESCARGA_MANUAL, source=MR, size=3_000_000),
        mod("C", cats=[], status=NO_ENCONTRADO, source=None, size=500_000),
    ], now=NOW)
    t = data["totals"]
    assert (t["size"], t["up_to_date"], t["updates"]) == (5_500_000, 0, 2)
    assert t["sources"] == {"curseforge": 1, "modrinth": 1, "none": 1}


def test_heaviest_top_five():
    data = analyze([mod(f"M{i}", cats=["magia"], size=i * 1_000_000) for i in range(1, 8)], now=NOW)
    assert [h["name"] for h in data["heaviest"]] == ["M7", "M6", "M5", "M4", "M3"]
    assert data["heaviest"][0]["size"] == 7_000_000


def test_stale_more_than_a_year_and_without_date():
    data = analyze([
        mod("Viejo", cats=["magia"], updated="2024-03-01T10:00:00Z"),
        mod("Reciente", cats=["magia"], updated="2026-10-01T10:00:00Z"),
        mod("SinFecha", cats=["magia"], updated=None),
    ], now=NOW)
    assert [s["name"] for s in data["stale"]] == ["Viejo"]
    assert data["stale"][0]["date"].startswith("2024-03-01")


def test_orphan_libraries_by_api_and_by_jar():
    balm = mod("Balm", cats=["librerias"], pid="531761", mod_id="balm")
    geckolib = mod("GeckoLib", cats=["librerias"], pid="388172", mod_id="geckolib")
    cloth = mod("Cloth Config", cats=["librerias"], pid="348521", mod_id="cloth_config")
    waystones = mod("Waystones", cats=["calidad_vida"], deps=[Dep(CF, "531761")])  # necesita Balm (API)
    mowzie = mod("Mowzie's Mobs", cats=["mobs"], requires=["geckolib"])  # necesita GeckoLib (jar)
    data = analyze([balm, geckolib, cloth, waystones, mowzie], now=NOW)
    assert [o["name"] for o in data["orphans"]] == ["Cloth Config"]


def test_library_needed_only_by_another_library_is_not_orphan():
    core = mod("Core", cats=["librerias"], pid="1", mod_id="core")
    lib = mod("Lib", cats=["librerias"], pid="2", mod_id="lib", requires=["core"])
    user = mod("User", cats=["magia"], requires=["lib"])
    assert analyze([core, lib, user], now=NOW)["orphans"] == []


def test_sides():
    data = analyze([mod("Sodium", cats=["rendimiento"], side="client"), mod("X", cats=["magia"], side="both"),
                    mod("Y", cats=["magia"])], now=NOW)
    assert data["sides"] == {"client": 1, "server": 0, "both": 1, "unknown": 1}


def test_empty_collection():
    data = analyze([], now=NOW)
    assert data["by_category"] == [] and data["totals"]["mods"] == 0 and data["heaviest"] == []


def test_side_from_modrinth_for_curseforge_mods():
    from mod_updater.curseforge import CfMatch
    from mod_updater.resolver import resolve_all
    from test_resolver import FakeCf, FakeClient, cf_file, cf_mod, ver

    class Mr(FakeClient):
        def projects(self, ids):
            return {i: {"id": i, "title": i, "slug": i, "client_side": "required", "server_side": "unsupported"}
                    for i in ids}

    cf = FakeCf(matches={100: CfMatch(1, cf_file(10, 1, "release", "2024-01-01"))}, index={}, files={})
    mr = Mr(current={"h1": ver("1.0", "p1", "release", "2024-01-01")}, latest={})
    (r,) = resolve_all([cf_mod("a.jar", "h1", 100)], curseforge=cf, modrinth=mr, loader="neoforge",
                       game_version="1.21.1")
    assert r.source == CF and r.side == "client"


def test_api_analysis_before_and_after_scan(tmp_path):
    from mod_updater.gui.api import Api
    a = Api(tmp_path / "settings.json", get_key=lambda: (None, None), run_async=lambda fn: fn(),
            cache_dir=tmp_path / "cache")
    assert a.analysis() == {"ready": False}
    a._results = [mod("Create", cats=["tecnologia"]), mod("Balm", cats=["librerias"])]
    data = a.analysis(False)
    assert data["ready"] and [b["cat"] for b in data["by_category"]] == ["tecnologia"]
    assert {b["cat"] for b in a.analysis(True)["by_category"]} == {"tecnologia", "librerias"}
