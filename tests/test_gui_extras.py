"""Versiones de Minecraft, mods rotos en "Requieren atención", "Detalles" y motivo de las betas."""

import json
from pathlib import Path

from mod_updater.deps import Broken, DepPlan
from mod_updater.gui.api import Api, serialize
from mod_updater.net import ApiError
from mod_updater.resolver import ACTUALIZABLE, AL_DIA, INSTALL, Resolution
from mod_updater.scanner import ModFile
from mod_updater.versions import FALLBACK, minecraft_versions


class FakeMr:
    def __init__(self, data=None, fail=False):
        self.data, self.fail, self.calls = data or [], fail, 0

    def _call(self, method, path, **kw):
        self.calls += 1
        if self.fail:
            raise ApiError("sin red")
        return self.data


TAGS = [
    {"version": "1.21.1", "version_type": "release", "date": "2024-08-08"},
    {"version": "1.21.2-pre1", "version_type": "snapshot", "date": "2024-09-01"},
    {"version": "26.1", "version_type": "release", "date": "2026-03-01"},
    {"version": "1.20.1", "version_type": "release", "date": "2023-06-12"},
]


def test_versions_only_releases_newest_first_and_cached(tmp_path):
    cache = tmp_path / "v.json"
    mr = FakeMr(TAGS)
    assert minecraft_versions(mr, cache, now=1000) == ["26.1", "1.21.1", "1.20.1"]
    assert minecraft_versions(FakeMr(fail=True), cache, now=2000) == ["26.1", "1.21.1", "1.20.1"]  # de la caché
    assert mr.calls == 1


def test_versions_fallback_offline_and_include(tmp_path):
    versions = minecraft_versions(FakeMr(fail=True), tmp_path / "v.json", include=["1.7.10"])
    assert set(FALLBACK) <= set(versions) and "1.7.10" in versions
    assert versions.index("1.21.1") < versions.index("1.20.1") < versions.index("1.7.10")


def test_expired_cache_is_refreshed(tmp_path):
    cache = tmp_path / "v.json"
    cache.write_text(json.dumps({"time": 0, "versions": ["1.0"]}), encoding="utf-8")
    assert minecraft_versions(FakeMr(TAGS), cache, now=10 * 24 * 3600) == ["26.1", "1.21.1", "1.20.1"]


def _mod(name):
    return ModFile(path=Path(f"{name}.jar"), file_name=f"{name}.jar", size=1, sha1="", sha512="", cf_fingerprint=0)


def test_broken_installed_mod_goes_to_attention_with_link():
    jei = Resolution(mod=_mod("jei"), status=AL_DIA, project_name="JEI", current_version="19.71", project_url="https://jei")
    plan = DepPlan(items=[], broken=[Broken(jei, "le falta MezzConfig y no se puede descargar automáticamente", "https://mezz")],
                   ignored=["Create: Escalated menciona Create Fabric…"])
    data = serialize([jei], plan)
    row = data["rows"][0]
    assert row["s"] == "manual" and row["url"] == "https://mezz"
    assert row["sub"].startswith("Le falta MezzConfig")
    assert row["to"] is None
    assert data["details"] == ["Create: Escalated menciona Create Fabric…"]


def test_beta_notes():
    dep = Resolution(mod=None, kind=INSTALL, status=ACTUALIZABLE, project_name="MezzConfig", new_version="0.7.1",
                     new_channel="beta", only_prerelease=True, required_by=["Just Enough Items (JEI)"])
    up_beta = Resolution(mod=_mod("a"), status=ACTUALIZABLE, project_name="A", current_channel="beta", new_channel="beta")
    up_allowed = Resolution(mod=_mod("b"), status=ACTUALIZABLE, project_name="B", current_channel="release", new_channel="beta")
    stable = Resolution(mod=_mod("c"), status=ACTUALIZABLE, project_name="C", current_channel="release", new_channel="release")
    rows = {r["name"]: r for r in serialize([up_beta, up_allowed, stable], DepPlan(items=[dep, up_beta, up_allowed, stable]))["rows"]}
    assert rows["MezzConfig"]["betaNote"] == "Única versión publicada; la requiere Just Enough Items (JEI)"
    assert "ya usas la beta" in rows["A"]["betaNote"]
    assert "activadas" in rows["B"]["betaNote"]
    assert rows["C"]["beta"] is False and rows["C"]["betaNote"] is None


def test_state_has_strings_and_language_choice(tmp_path, mods_dir_factory=None):
    mods = tmp_path / ".minecraft" / "mods"
    mods.mkdir(parents=True)
    a = Api(tmp_path / "s.json", get_key=lambda: (None, None), run_async=lambda fn: fn())
    res = a.save_setup({"mods_dir": str(mods), "loader": "neoforge", "minecraft_version": "1.21.1", "language": "en"})
    assert res["ok"]
    state = res["state"]
    assert state["lang"] == "en" and state["settings"]["language"] == "en"
    assert state["strings"]["ui.all_up_to_date"] == "Everything up to date"
    assert [l["value"] for l in state["languages"]] == ["auto", "es", "en"]
    assert a.get_strings("es")["strings"]["ui.all_up_to_date"] == "Todo al día"
