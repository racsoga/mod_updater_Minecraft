"""API de la app de escritorio: la key nunca sale de Python, validaciones y serialización."""

import io
import json
import zipfile
from pathlib import Path

import pytest

from mod_updater import credentials
from mod_updater.curseforge import CurseForgeAuthError
from mod_updater.deps import DepPlan
from mod_updater.gui import api as api_mod
from mod_updater.gui.api import Api, serialize
from mod_updater.net import ApiError
from mod_updater.resolver import ACTUALIZABLE, AL_DIA, DESCARGA_MANUAL, INSTALL, NO_ENCONTRADO, Resolution
from mod_updater.scanner import ModFile, detect_environment, read_metadata
from mod_updater.settings import Settings, load_settings, save_settings

SECRET = "super-secret-key-ABCD1234"


class FakeWindow:
    def __init__(self):
        self.calls = []

    def evaluate_js(self, code):
        self.calls.append(code)

    def events(self):
        out = []
        for c in self.calls:
            inner = c[len("window.onBackend("):-1]
            event, _, payload = inner.partition(", ")
            out.append((json.loads(event), json.loads(payload)))
        return out


class OkClient:
    def __init__(self, key):
        self.key = key

    def check(self):
        pass


class BadKeyClient(OkClient):
    def check(self):
        raise CurseForgeAuthError("rechazada")


class OfflineClient(OkClient):
    def check(self):
        raise ApiError("sin red")


@pytest.fixture
def mods_dir(tmp_path):
    d = tmp_path / ".minecraft" / "mods"
    d.mkdir(parents=True)
    return d


@pytest.fixture
def make_api(tmp_path, monkeypatch):
    saved = {}
    monkeypatch.setattr(credentials, "set_key", lambda k: saved.__setitem__("key", k))
    monkeypatch.setattr(credentials, "delete_key", lambda: saved.pop("key", None))

    def factory(key=SECRET, cf=OkClient):
        a = Api(tmp_path / "settings.json", get_key=lambda: (key, "keyring" if key else None),
                cf_factory=cf, run_async=lambda fn: fn())
        a._saved = saved
        return a
    return factory


# --------------------------------------------------------------------------- la key no sale de Python

def test_state_never_contains_key(make_api):
    state = make_api().get_state()
    assert SECRET not in json.dumps(state, ensure_ascii=False)
    assert state["key_hint"] == "••••1234"
    assert state["has_key"] is True


def test_test_key_messages(make_api):
    assert make_api(cf=OkClient).test_key("x" * 30)["ok"] is True
    bad = make_api(cf=BadKeyClient).test_key("x" * 30)
    assert bad["ok"] is False and "no acepta" in bad["message"]
    off = make_api(cf=OfflineClient).test_key("x" * 30)
    assert off["ok"] is False and "conectar" in off["message"]
    assert make_api(key=None).test_key("")["message"].startswith("Pega")
    assert SECRET not in json.dumps(make_api().test_key(""))


def test_hint_only_last_four():
    assert credentials.hint("abcdef123456") == "••••3456"
    assert credentials.hint(None) is None


# --------------------------------------------------------------------------- guardar configuración

def test_save_setup_validates_folder(make_api, tmp_path):
    res = make_api().save_setup({"mods_dir": str(tmp_path / "no-existe"), "loader": "neoforge", "minecraft_version": "1.21.1"})
    assert res["ok"] is False and res["field"] == "mods_dir"


def test_save_setup_validates_loader_and_version(make_api, mods_dir):
    a = make_api()
    assert a.save_setup({"mods_dir": str(mods_dir), "loader": "rift", "minecraft_version": "1.21.1"})["field"] == "loader"
    assert a.save_setup({"mods_dir": str(mods_dir), "loader": "neoforge", "minecraft_version": "abc"})["field"] == "minecraft_version"


def test_save_setup_persists_and_stores_key_in_keyring(make_api, mods_dir, tmp_path):
    a = make_api()
    res = a.save_setup({"mods_dir": str(mods_dir), "loader": "fabric", "minecraft_version": "1.20.1",
                        "key": "  nueva-key  ", "use_curseforge": True, "allow_beta": True, "backups_to_keep": 3})
    assert res["ok"] is True
    assert a._saved["key"] == "nueva-key"
    s = load_settings(tmp_path / "settings.json")
    assert (s.mods_dir, s.loader, s.minecraft_version, s.allow_beta, s.backups_to_keep, s.setup_done) == (
        str(mods_dir), "fabric", "1.20.1", True, 3, True)
    assert "nueva-key" not in (tmp_path / "settings.json").read_text(encoding="utf-8")


def test_save_without_key_keeps_existing(make_api, mods_dir):
    a = make_api()
    a.save_setup({"mods_dir": str(mods_dir), "loader": "neoforge", "minecraft_version": "1.21.1", "key": ""})
    assert "key" not in a._saved


def test_settings_roundtrip_and_bad_file(tmp_path):
    p = tmp_path / "s.json"
    p.write_text("{no es json", encoding="utf-8")
    assert load_settings(p).setup_done is False
    save_settings(Settings(mods_dir="X", backups_to_keep=0, setup_done=True), p)
    s = load_settings(p)
    assert s.mods_dir == "X" and s.setup_done and s.backups_to_keep == 1


def test_open_url_only_http(make_api, monkeypatch):
    opened = []
    monkeypatch.setattr(api_mod.webbrowser, "open", opened.append)
    a = make_api()
    assert a.open_url("https://www.curseforge.com/x") is True
    assert a.open_url("file:///C:/Windows/system32/calc.exe") is False
    assert a.open_url("javascript:alert(1)") is False
    assert opened == ["https://www.curseforge.com/x"]


# --------------------------------------------------------------------------- serialización

def _mod(name, file_name=None):
    return ModFile(path=Path(file_name or f"{name}.jar"), file_name=file_name or f"{name}.jar", size=1, sha1="", sha512="", cf_fingerprint=0)


def test_serialize_statuses_and_selection():
    up = Resolution(mod=_mod("a"), status=ACTUALIZABLE, project_name="A", current_version="1", new_version="2", new_channel="beta")
    ok = Resolution(mod=_mod("b"), status=AL_DIA, project_name="B", current_version="1")
    manual = Resolution(mod=_mod("c"), status=DESCARGA_MANUAL, project_name="C", note="sin archivo", project_url="https://x")
    missing = Resolution(mod=_mod("d", "d-1.0.jar"), status=NO_ENCONTRADO)
    dup = Resolution(mod=_mod("e"), status=ACTUALIZABLE, project_name="E", duplicate=True)
    dep = Resolution(mod=None, kind=INSTALL, status=ACTUALIZABLE, project_name="MezzConfig", new_version="0.7.1", required_by=["JEI"])
    data = serialize([up, ok, manual, missing, dup], DepPlan(items=[up, dep]))
    rows = {r["name"]: r for r in data["rows"]}
    assert rows["MezzConfig"]["s"] == "dep" and rows["MezzConfig"]["neededBy"] == ["JEI"] and rows["MezzConfig"]["checked"]
    assert rows["MezzConfig"]["from"] is None
    assert rows["A"]["s"] == "up" and rows["A"]["checked"] and rows["A"]["beta"]
    assert rows["B"]["s"] == "ok" and not rows["B"]["checked"]
    assert rows["C"]["s"] == "manual" and rows["C"]["sub"] == "sin archivo"
    assert rows["E"]["s"] == "manual" and "duplicado" in rows["E"]["sub"]
    missing_row = next(r for r in data["rows"] if r["s"] == "missing")
    assert missing_row["sub"] == "No aparece en CurseForge ni en Modrinth"  # el nombre ya es el archivo
    assert [r["id"] for r in data["rows"]] == list(range(len(data["rows"])))


# --------------------------------------------------------------------------- revisión completa (sin red)

def test_scan_emits_progress_and_results_without_key(make_api, monkeypatch, mods_dir):
    a = make_api()
    a.save_setup({"mods_dir": str(mods_dir), "loader": "neoforge", "minecraft_version": "1.21.1"})
    win = FakeWindow()
    a._attach(win)
    res = Resolution(mod=_mod("a"), status=AL_DIA, project_name="A", current_version="1")

    def fake_scan(path, cache_path=None, on_item=None, **kw):
        on_item(1, 1, path / "a.jar")
        return [res.mod]

    def fake_resolve(mods, curseforge, modrinth, on_phase, **kw):
        if curseforge is not None:
            raise CurseForgeAuthError("rechazada")
        on_phase("mr")
        return [res]

    monkeypatch.setattr(api_mod, "scan_folder", fake_scan)
    monkeypatch.setattr(api_mod, "resolve_all", fake_resolve)
    monkeypatch.setattr(api_mod, "plan_with_dependencies", lambda results, selected, finder: DepPlan(items=[]))
    monkeypatch.setattr(api_mod, "DependencyFinder", lambda *a, **k: None)

    assert a.start_scan() is True
    events = win.events()
    kinds = [e for e, _ in events]
    assert kinds[0] == "progress" and kinds[-1] == "results"
    assert any(p.get("label") == "Leyendo mods 1/1" for e, p in events if e == "progress")
    results = events[-1][1]
    assert any("no acepta tu key" in n for n in results["notices"])
    assert results["env"]["curseforge"] is False
    assert SECRET not in json.dumps(events, ensure_ascii=False)
    assert a.start_scan() is True  # el candado se libera al terminar


def test_scan_network_error_is_reported(make_api, monkeypatch, mods_dir):
    a = make_api()
    a.save_setup({"mods_dir": str(mods_dir), "loader": "neoforge", "minecraft_version": "1.21.1"})
    win = FakeWindow()
    a._attach(win)
    monkeypatch.setattr(api_mod, "scan_folder", lambda *a, **k: [])

    def offline(*a, **k):
        raise ApiError("sin red", kind="offline")
    monkeypatch.setattr(api_mod, "resolve_all", offline)
    a.start_scan()
    event, payload = win.events()[-1]
    assert event == "error" and "conexión" in payload["message"]

    def both_down(*a, **k):
        raise ApiError("HTTP 503")
    monkeypatch.setattr(api_mod, "resolve_all", both_down)
    a.start_scan()
    event, payload = win.events()[-1]
    assert event == "error" and "no responden" in payload["message"]


# --------------------------------------------------------------------------- deducir versión y loader

def _jar(files: dict) -> zipfile.ZipFile:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, content in files.items():
            z.writestr(name, content)
    return zipfile.ZipFile(io.BytesIO(buf.getvalue()))


NEO_TOML = '''
[[mods]]
modId = "examplemod"
version = "1.0"
displayName = "Example"
[[dependencies.examplemod]]
modId = "neoforge"
type = "required"
versionRange = "[21.1,)"
[[dependencies.examplemod]]
modId = "minecraft"
type = "required"
versionRange = "[1.21.1,1.21.2)"
'''


def test_read_metadata_neoforge_and_fabric():
    neo = read_metadata(_jar({"META-INF/neoforge.mods.toml": NEO_TOML}))
    assert (neo["loader"], neo["mod_id"], neo["mc_range"]) == ("neoforge", "examplemod", "[1.21.1,1.21.2)")
    fab = read_metadata(_jar({"fabric.mod.json": json.dumps({"id": "fab", "version": "2.0", "depends": {"minecraft": ">=1.20.1"}})}))
    assert (fab["loader"], fab["mod_id"], fab["mc_range"]) == ("fabric", "fab", ">=1.20.1")
    assert read_metadata(_jar({"README.txt": "nada"})) == {}


def test_detect_environment_majority():
    def m(loader, rng):
        return ModFile(path=Path("x"), file_name="x", size=0, sha1="", sha512="", cf_fingerprint=0, loader=loader, mc_range=rng)
    mods = [m("neoforge", "[1.21.1,1.21.2)"), m("neoforge", "[1.21,1.22)"), m("neoforge", "[1.21.1]"), m("forge", None)]
    assert detect_environment(mods) == ("1.21.1", "neoforge")
    assert detect_environment([]) == (None, None)
