"""Sugerencias según el tipo de partida: reglas de la base de conocimiento, sin IA externa."""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from mod_updater.knowledge import load_knowledge
from mod_updater.resolver import ACTUALIZABLE, AL_DIA, CF, INSTALL, MR, Dep, Resolution
from mod_updater.scanner import ModFile
from mod_updater.suggest import suggest

NOW = datetime(2026, 11, 21, tzinfo=timezone.utc).timestamp()
KB = load_knowledge()


def inst(name, pid, *, source=CF, cats=("tecnologia",), size=1_000_000, updated="2026-10-01T00:00:00Z",
         deps=(), side=None, mod_id=None, requires=()):
    mod = ModFile(path=Path(f"{name}.jar"), file_name=f"{name}.jar", size=size, sha1=name, sha512="",
                  cf_fingerprint=0, mod_id=mod_id or name.lower().replace(" ", "_"), requires=list(requires))
    return Resolution(mod=mod, status=AL_DIA, source=source, project_id=str(pid), project_name=name,
                      categories=list(cats), project_updated=updated, version_updated=updated,
                      current_deps=list(deps), known_ids={(source, str(pid))}, side=side)


class Finder:
    """Todo existe para la versión salvo lo que se marque como no disponible."""

    def __init__(self, missing=()):
        self.missing, self.calls = set(missing), []

    def find(self, dep):
        self.calls.append(dep.key)
        if dep.key in self.missing or dep.id in self.missing:
            return None
        return Resolution(mod=None, kind=INSTALL, status=ACTUALIZABLE, source=dep.source, project_id=dep.id,
                          project_name=f"#{dep.id}", new_version="1.0", download_url="https://cdn.modrinth.com/x.jar")


def answers(**kw):
    base = {"players": "solo", "styles": [], "difficulty": "normal", "pc": "potente", "max": 0}
    return base | kw


def names(items):
    return sorted(i["name"] for i in items)


def run(installed, finder=None, **kw):
    return suggest(answers(**kw), installed, finder or Finder(), knowledge=KB, now=NOW)


def test_knowledge_files_are_valid():
    assert KB["solapamientos"] and KB["esenciales"]["base"] and KB["duros"]
    for group in KB["solapamientos"]:
        assert len(group["mods"]) >= 2
        for m in group["mods"]:
            assert m.get("curseforge") or m.get("modrinth")


def test_overlap_suggests_removing_the_second_minimap():
    r = run([inst("Xaero's Minimap", 263420, cats=["mapas"]), inst("JourneyMap", 32274, cats=["mapas"])])
    rm = {i["name"]: i for i in r["remove"]}
    assert "JourneyMap" in rm and "Xaero's Minimap" not in rm
    assert "Xaero's Minimap" in rm["JourneyMap"]["reason"]


def test_overlap_keeps_the_one_another_mod_needs():
    # Un addon necesita JourneyMap: se sugiere quitar Xaero's, no JourneyMap
    addon = inst("JourneyMap Addon", 999, cats=["mapas"], deps=[Dep(CF, "32274")])
    r = run([inst("Xaero's Minimap", 263420, cats=["mapas"]), inst("JourneyMap", 32274, cats=["mapas"]), addon])
    assert "Xaero's Minimap" in names(r["remove"]) and "JourneyMap" not in names(r["remove"])


def test_known_incompatibility():
    r = run([inst("Sodium", 394468, cats=["rendimiento"]), inst("Embeddium", 908741, cats=["rendimiento"])])
    assert "Embeddium" in names(r["remove"])


def test_abandoned_and_orphan_library():
    old = inst("Viejo", 1, updated="2024-02-01T00:00:00Z")
    lib = inst("Lib Sola", 2, cats=["librerias"])
    r = run([old, lib, inst("Otro", 3)])
    rm = {i["name"]: i for i in r["remove"]}
    assert "2024" in rm["Viejo"]["reason"] and "Lib Sola" in rm


def test_relaxed_difficulty_removes_hard_mods_and_never_adds_them():
    born = inst("Born in Chaos", 686437, cats=["mobs"])
    r = run([born], styles=["combate"], difficulty="relajada")
    assert "Born in Chaos" in names(r["remove"])
    assert not any(a["id"] == "686437" or a["name"] == "Born in Chaos" for a in r["add"])
    r = run([], styles=["combate"], difficulty="reto")
    assert any(a["name"] == "Born in Chaos" for a in r["add"])


def test_weak_pc_flags_heavy_mods_and_suggests_performance():
    heavy = inst("Enorme", 5, size=90_000_000)
    r = run([heavy], pc="justo")
    assert "Enorme" in names(r["remove"])
    assert {"Sodium", "ModernFix"} <= {a["name"] for a in r["add"]}


def test_server_flags_client_only_mods():
    r = run([inst("Shaders", 7, cats=["rendimiento"], side="client")], players="servidor")
    assert "Shaders" in names(r["remove"])


def test_adds_only_what_exists_for_the_version_and_not_installed():
    finder = Finder(missing={(CF, "231951")})  # Immersive Engineering sin versión
    r = run([inst("Create", 328085)], finder=finder, styles=["tecnologia"])
    added = {a["name"] for a in r["add"]}
    assert "Mekanism" in added and "Create" not in added and "Immersive Engineering" not in added
    assert "Create" in names(r["keep"])


def test_does_not_add_one_from_a_group_already_covered():
    r = run([inst("EMI", 580555, cats=["mapas"])])  # ya tiene visor de recetas
    assert "Just Enough Items (JEI)" not in {a["name"] for a in r["add"]}


def test_max_mods_limit():
    many = [inst(f"M{i}", 1000 + i) for i in range(48)]
    r = run(many, styles=["tecnologia", "magia", "exploracion"], max=50)
    assert len(r["add"]) <= 2
    r = run(many, max=40)
    assert r["over_limit"] == 8


def test_every_reason_is_a_sentence():
    r = run([inst("Xaero's Minimap", 263420), inst("JourneyMap", 32274)], styles=["magia"])
    for col in ("remove", "keep", "add"):
        for item in r[col]:
            assert item["reason"] and not item["reason"].startswith("sug.")


def test_every_group_and_style_has_texts():
    from mod_updater import i18n
    for code in i18n.SUPPORTED:
        table = i18n._load(code)
        for g in KB["solapamientos"]:
            assert table.get(f"sug.group.{g['grupo']}"), (code, g["grupo"])
        for style in KB["esenciales"]:
            assert table.get(f"sug.reason.style_{style}"), (code, style)
        for style in list(KB["esenciales"]):
            if style not in ("amigos", "servidor", "rendimiento"):
                assert table.get(f"sug.style.{style}"), (code, style)


def test_api_suggest_saves_answers_and_plans_removals(tmp_path, monkeypatch):
    from mod_updater.gui import api as api_mod
    from mod_updater.gui.api import Api
    from mod_updater.settings import Settings, load_settings, save_settings
    mods = tmp_path / "mods"
    mods.mkdir()
    f = tmp_path / "s.json"
    save_settings(Settings(mods_dir=str(mods), setup_done=True), f)
    a = Api(f, get_key=lambda: (None, None), run_async=lambda fn: fn(), cache_dir=tmp_path / "c", running=lambda d: [])
    assert a.suggest_run({})["ok"] is False  # sin revisión
    a._results = [inst("Xaero's Minimap", 263420, cats=["mapas"]), inst("JourneyMap", 32274, cats=["mapas"])]
    monkeypatch.setattr(api_mod, "DependencyFinder", lambda *x, **k: Finder())
    res = a.suggest_run({"players": "solo", "styles": ["magia", "inventado"], "difficulty": "normal", "pc": "potente", "max": 50})
    assert res["ok"] and res["answers"]["styles"] == ["magia"] and "JourneyMap" in names(res["remove"])
    assert load_settings(f).answers["max"] == 50 and load_settings(f).profiles[0]["answers"]["styles"] == ["magia"]
    plan = a.suggest_plan({"remove": ["JourneyMap.jar"], "add": []})
    assert plan["ok"] and [r["s"] for r in plan["rows"]] == ["rm"] and plan["removals"] == ["JourneyMap"]
    started = []
    a._apply = lambda chosen, s, index: started.append([(r.name, r.kind) for r in chosen])
    assert a.install_start()["ok"] and started == [[("JourneyMap", "remove")]]
