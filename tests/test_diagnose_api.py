"""Hito 4 (v4): diagnóstico a través de la API (pestaña Diagnóstico)."""

import os
import shutil
from pathlib import Path

from mod_updater import i18n
from mod_updater.resolver import ACTUALIZABLE, INSTALL, MR, Resolution
from test_diagnose_actions import EMBEDDIUM_MR, SODIUM_MR, candidate
from test_toggle import files, make_jar, res_for

FIX = Path(__file__).parent / "fixtures" / "crash"


def setup_module():
    i18n.set_language("es")


def make_api(tmp_path, monkeypatch, *, reports=("fml_sodium.txt",), mods=(), scanned=True):
    from mod_updater.gui import api as api_mod
    from mod_updater.gui.api import Api
    from mod_updater.settings import Settings, save_settings
    game = tmp_path / ".minecraft"
    d = game / "mods"
    d.mkdir(parents=True)
    (game / "crash-reports").mkdir()
    for i, name in enumerate(reports):
        dst = game / "crash-reports" / f"crash-2026-11-2{i}_18.08.26-{'fml' if 'fml' in name else 'client'}.txt"
        shutil.copy(FIX / name, dst)
        os.utime(dst, None)
    f = tmp_path / "s.json"
    save_settings(Settings(mods_dir=str(d), setup_done=True), f)
    a = Api(f, get_key=lambda: (None, None), run_async=lambda fn: fn(), cache_dir=tmp_path / "c", running=lambda g: [])
    results = []
    for file_name, mod_id, name, pid in mods:
        make_jar(d / file_name, mod_id)
        r = res_for(d / file_name)
        r.project_name, r.project_id, r.source, r.known_ids = name, pid, MR, {(MR, pid)}
        results.append(r)
    if scanned:
        a._results, a._rows, a._row_s = results, list(results), ["ok"] * len(results)

    class Finder:
        def __init__(self, *x, **k):
            pass

        def find(self, dep):
            return candidate("Sodium", SODIUM_MR) if dep.id in ("sodium", SODIUM_MR) else None

        def version_date(self, dep):
            return None

        def describe(self, dep):
            return dep.id

    monkeypatch.setattr(api_mod, "DependencyFinder", Finder)
    return a, d


SODIUM_MODS = [("iris-flywheel-compat-2.4.0.jar", "irisflw", "Iris Flywheel Compat", "p1"),
               ("createbetterfps-1.1.5.jar", "createbetterfps", "Create Better FPS", "p2"),
               ("iris-1.8.14.jar", "iris", "Iris", "p3"),
               ("embeddium-1.0.15.jar", "embeddium", "Embeddium", EMBEDDIUM_MR)]


def test_reports_list_and_new_report_notice(tmp_path, monkeypatch):
    a, d = make_api(tmp_path, monkeypatch)
    assert a.diag_new()["new"] is True  # informe de hoy sin ver
    out = a.diag_reports()
    assert out["ok"] and [r["kind"] for r in out["reports"]] == ["fml"]
    assert a.diag_new()["new"] is False  # abrir la pestaña lo marca como visto
    newer = d.parent / "crash-reports" / "crash-2026-11-28_19.00.00-client.txt"
    shutil.copy(FIX / "client_mixin.txt", newer)
    os.utime(newer, (os.path.getmtime(newer) + 60, os.path.getmtime(newer) + 60))
    assert a.diag_new()["new"] is True


def test_run_real_case_gives_one_swap_card(tmp_path, monkeypatch):
    a, d = make_api(tmp_path, monkeypatch, mods=SODIUM_MODS)
    rid = a.diag_reports()["reports"][0]["id"]
    out = a.diag_run(rid)
    assert out["ok"] and out["head"] == "1 problema al cargar los mods"
    assert out["deck"] == "NeoForge no llegó a abrir el juego. Estos son los problemas que ha encontrado."
    card = out["cards"][0]
    assert [(x["label"], x["primary"]) for x in card["actions"]][0] == ("Cambiar Embeddium por Sodium", True)
    assert all("PC-OSCAR" not in e and "/Users/Ana/" not in e for e in card["evidence"])


def test_swap_action_disables_and_installs(tmp_path, monkeypatch):
    from mod_updater import downloader
    a, d = make_api(tmp_path, monkeypatch, mods=SODIUM_MODS)
    out = a.diag_run(a.diag_reports()["reports"][0]["id"])
    monkeypatch.setattr(downloader, "download_verified", lambda res, dest, sf: make_jar(dest, "sodium"))
    done = a.diag_do(out["cards"][0]["actions"][0]["id"])
    assert done["ok"] and done["rows"]
    assert "embeddium-1.0.15.jar.disabled" in files(d) and "Sodium-0.8.13.jar" in files(d)


def test_disable_action_names_and_disables_both(tmp_path, monkeypatch):
    a, d = make_api(tmp_path, monkeypatch, mods=SODIUM_MODS)
    out = a.diag_run(a.diag_reports()["reports"][0]["id"])
    act = next(x for x in out["cards"][0]["actions"] if x["label"] == "Desactivar Iris Flywheel Compat y Create Better FPS")
    assert a.diag_do(act["id"])["ok"]
    assert {"iris-flywheel-compat-2.4.0.jar.disabled", "createbetterfps-1.1.5.jar.disabled"} <= set(files(d))


def test_without_scan_no_actions(tmp_path, monkeypatch):
    a, d = make_api(tmp_path, monkeypatch, mods=SODIUM_MODS, scanned=False)
    out = a.diag_run(a.diag_reports()["reports"][0]["id"])
    assert out["ok"] and out["scanned"] is False and all(c["actions"] == [] for c in out["cards"])


def test_empty_state(tmp_path, monkeypatch):
    a, d = make_api(tmp_path, monkeypatch, reports=())
    assert a.diag_reports()["reports"] == [] and a.diag_new()["new"] is False


def test_copy_summary_is_anonymized(tmp_path, monkeypatch):
    a, d = make_api(tmp_path, monkeypatch, mods=SODIUM_MODS)
    copied = []
    a._clipboard = copied.append
    rid = a.diag_reports()["reports"][0]["id"]
    a.diag_run(rid)
    assert a.diag_copy(rid)["ok"]
    text = copied[0]
    assert "Falta Sodium" in text and "Mod irisflw requires sodium" in text
    assert "/Users/Ana/" not in text and "PC-OSCAR" not in text


def test_update_and_versions_actions(tmp_path, monkeypatch):
    a, d = make_api(tmp_path, monkeypatch, reports=("client_mixin.txt",),
                    mods=[("create-6.0.jar", "create", "Create", "pc"), ("irisflw-2.4.jar", "irisflw", "Iris Flywheel Compat", "pi")])
    a._results[0].mod.packages = ["com.simibubi.create"]
    out = a.diag_run(a.diag_reports()["reports"][0]["id"])
    card = out["cards"][0]
    assert out["head"] == "Sospechoso: Iris Flywheel Compat" and card["note"] == "No hay versión más nueva de Iris Flywheel Compat."
    versions = card["actions"][0]
    assert versions["label"] == "Volver a una versión anterior de Create"
    assert a.diag_do(versions["id"]) == {"ok": True, "open_versions": 0}


# ---------------------------------------------------------------- revisión final

def test_update_action_takes_its_new_dependencies(tmp_path, monkeypatch):
    from mod_updater.deps import DepPlan
    a, d = make_api(tmp_path, monkeypatch, reports=("inventado_sospechoso.txt",),
                    mods=[("storagedrawers-13.jar", "storagedrawers", "Storage Drawers", "sd")])
    r = a._results[0]
    r.status, r.new_version, r.new_file_name, r.download_url = ACTUALIZABLE, "14.0", "storagedrawers-14.jar", "https://cdn.modrinth.com/s.jar"
    lib = candidate("Nueva Lib", "lib")
    lib.required_by = ["Storage Drawers"]
    a._plan = DepPlan(items=[r, lib])
    a._rows, a._row_s = [lib, r], ["dep", "up"]
    started = []
    a._apply = lambda chosen, s, index=None, after=None: started.append(sorted(x.name for x in chosen))
    out = a.diag_run(a.diag_reports()["reports"][0]["id"])
    up = next(x for x in out["cards"][0]["actions"] if x["type"] == "update")
    assert a.diag_do(up["id"])["ok"] and started == [["Nueva Lib", "Storage Drawers"]]


def test_disable_recomputes_dependents_at_click_time(tmp_path, monkeypatch):
    from mod_updater.resolver import Dep
    a, d = make_api(tmp_path, monkeypatch, mods=SODIUM_MODS)
    out = a.diag_run(a.diag_reports()["reports"][0]["id"])
    act = next(x for x in out["cards"][0]["actions"] if x["label"] == "Desactivar Iris")
    later = a._results[3]  # Embeddium pasa a depender de Iris después del diagnóstico
    later.current_deps = [Dep(MR, "p3")]
    assert a.diag_do(act["id"])["ok"]
    assert {"iris-1.8.14.jar.disabled", "embeddium-1.0.15.jar.disabled"} <= set(files(d))


def test_action_on_a_file_that_no_longer_exists_is_an_error(tmp_path, monkeypatch):
    a, d = make_api(tmp_path, monkeypatch, mods=SODIUM_MODS)
    out = a.diag_run(a.diag_reports()["reports"][0]["id"])
    act = next(x for x in out["cards"][0]["actions"] if x["label"] == "Desactivar Iris")
    (d / "iris-1.8.14.jar").unlink()
    a._results = [r for r in a._results if r.mod.file_name != "iris-1.8.14.jar"]
    a._rows = list(a._results)
    res = a.diag_do(act["id"])
    assert res["ok"] is False and res["message"]


def test_swap_does_not_disable_if_the_install_cannot_be_prepared(tmp_path, monkeypatch):
    from mod_updater.net import ApiError
    a, d = make_api(tmp_path, monkeypatch, mods=SODIUM_MODS)
    out = a.diag_run(a.diag_reports()["reports"][0]["id"])

    def offline(items):
        raise ApiError("x", kind="offline")

    monkeypatch.setattr(a, "install_plan", lambda items: {"ok": False, "message": "sin red"})
    res = a.diag_do(out["cards"][0]["actions"][0]["id"])
    assert res["ok"] is False and "embeddium-1.0.15.jar" in files(d)


def test_toggle_failure_has_a_message(tmp_path, monkeypatch):
    a, d = make_api(tmp_path, monkeypatch, mods=SODIUM_MODS)
    out = a.diag_run(a.diag_reports()["reports"][0]["id"])
    act = next(x for x in out["cards"][0]["actions"] if x["label"] == "Desactivar Iris")
    make_jar(d / "iris-1.8.14.jar.disabled", "iris")  # el destino ya existe: el renombrado falla
    res = a.diag_do(act["id"])
    assert res["ok"] is False and "Iris" in res["message"]
