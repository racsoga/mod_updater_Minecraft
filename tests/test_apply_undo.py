"""Paso 5: estados por mod, Deshacer, backups y la API de la app (sin red ni ventana)."""

import hashlib
import json
from pathlib import Path

import pytest

from mod_updater.deps import DepPlan
from mod_updater.downloader import (
    Outcome,
    apply_updates,
    backup_info,
    clear_backups,
    list_backups,
    undo_backup,
)
from mod_updater.gui import api as api_mod
from mod_updater.gui.api import Api
from mod_updater.resolver import ACTUALIZABLE, AL_DIA, INSTALL, Resolution
from mod_updater.scanner import ModFile
from test_downloader import NEW_CONTENT, FakeResp, FakeSession, make_res, mods_dir  # noqa: F401 (fixture)


def make_install(name="mezz-0.7.1.jar", url="https://cdn.modrinth.com/mezz.jar"):
    return Resolution(mod=None, kind=INSTALL, status=ACTUALIZABLE, source="modrinth", project_id="m",
                      project_name="MezzConfig", new_version="0.7.1", new_file_name=name, download_url=url,
                      new_sha1=hashlib.sha1(NEW_CONTENT).hexdigest(), required_by=["JEI"])


def do_apply(mods_dir, items, routes, on_state=None):
    return apply_updates(items, mods_dir, modrinth_session=FakeSession("mr", routes), curseforge_session=None, on_state=on_state)


# --------------------------------------------------------------------------- estados por mod

def test_states_sequence(mods_dir):
    upd = make_res(mods_dir)
    bad = make_res(mods_dir, old_name="b-1.jar", new_name="b-2.jar", url="https://cdn.modrinth.com/b.jar")
    seen = []
    do_apply(mods_dir, [upd, bad], {upd.download_url: FakeResp(body=NEW_CONTENT), bad.download_url: FakeResp(status=404)},
             on_state=lambda r, s: seen.append((r.mod.file_name, s if isinstance(s, str) else ("ok" if s.ok else "error"))))
    assert seen == [("old-1.0.jar", "downloading"), ("old-1.0.jar", "verified"), ("old-1.0.jar", "ok"),
                    ("b-1.jar", "downloading"), ("b-1.jar", "error")]


# --------------------------------------------------------------------------- deshacer

def test_undo_restores_old_and_sets_new_aside(mods_dir):
    upd, inst = make_res(mods_dir), make_install()
    backup, outcomes = do_apply(mods_dir, [upd, inst], {upd.download_url: FakeResp(body=NEW_CONTENT),
                                                        inst.download_url: FakeResp(body=NEW_CONTENT)})
    assert all(o.ok for o in outcomes)
    assert backup_info(backup)["undoable"] and backup_info(backup)["changes"] == 2

    r = undo_backup(backup)
    assert (r.restored, r.removed, r.errors) == (1, 2, [])
    assert sorted(p.name for p in mods_dir.iterdir()) == ["old-1.0.jar"]
    assert (mods_dir / "old-1.0.jar").read_bytes() == b"viejo jar"
    assert sorted(p.name for p in (backup / "undo").iterdir()) == ["mezz-0.7.1.jar", "old-1.1.jar"]  # nada se borra
    assert json.loads((backup / "cambios.json").read_text(encoding="utf-8"))["undone"]
    assert "[DESHECHO]" in (backup / "cambios.txt").read_text(encoding="utf-8")
    assert backup_info(backup)["undoable"] is False


def test_undo_twice_is_refused(mods_dir):
    upd = make_res(mods_dir)
    backup, _ = do_apply(mods_dir, [upd], {upd.download_url: FakeResp(body=NEW_CONTENT)})
    undo_backup(backup)
    again = undo_backup(backup)
    assert again.errors and "ya se deshizo" in again.errors[0]
    assert (mods_dir / "old-1.0.jar").exists()


def test_undo_skips_conflicts_but_continues(mods_dir):
    a = make_res(mods_dir, old_name="a-1.jar", new_name="a-2.jar", url="https://cdn.modrinth.com/a.jar")
    b = make_res(mods_dir, old_name="b-1.jar", new_name="b-2.jar", url="https://cdn.modrinth.com/b.jar")
    backup, _ = do_apply(mods_dir, [a, b], {a.download_url: FakeResp(body=NEW_CONTENT), b.download_url: FakeResp(body=NEW_CONTENT)})
    (mods_dir / "a-1.jar").write_bytes(b"otro que puso el usuario")  # conflicto con el nombre viejo de A
    (backup / "b-1.jar").unlink()  # falta el viejo de B en la copia
    r = undo_backup(backup)
    assert r.restored == 0 and len(r.errors) == 2
    assert (mods_dir / "a-1.jar").read_bytes() == b"otro que puso el usuario"  # no se pisa


def test_failed_changes_are_not_undone(mods_dir):
    ok = make_res(mods_dir)
    bad = make_res(mods_dir, old_name="b-1.jar", new_name="b-2.jar", url="https://cdn.modrinth.com/b.jar")
    backup, _ = do_apply(mods_dir, [ok, bad], {ok.download_url: FakeResp(body=NEW_CONTENT), bad.download_url: FakeResp(status=404)})
    r = undo_backup(backup)
    assert (r.restored, r.errors) == (1, [])
    assert (mods_dir / "b-1.jar").read_bytes() == b"viejo jar"


def test_clear_backups_only_ours(mods_dir):
    upd = make_res(mods_dir)
    do_apply(mods_dir, [upd], {upd.download_url: FakeResp(body=NEW_CONTENT)})
    foreign = mods_dir.parent / "mods_backup" / "mis-cosas"
    foreign.mkdir()
    assert clear_backups(mods_dir) == 1
    assert list_backups(mods_dir) == [] and foreign.exists()


# --------------------------------------------------------------------------- API de la app

class FakeWindow:
    def __init__(self):
        self.events = []

    def evaluate_js(self, code):
        inner = code[len("window.onBackend("):-1]
        event, _, payload = inner.partition(", ")
        self.events.append((json.loads(event), json.loads(payload)))


class FakeMrClient:
    routes = {}

    def __init__(self, ua):
        self.session = FakeSession("mr", self.routes)


@pytest.fixture
def app(tmp_path, mods_dir):
    upd = make_res(mods_dir)
    inst = make_install()
    ok_mod = ModFile(path=mods_dir / "ok.jar", file_name="ok.jar", size=1, sha1="", sha512="", cf_fingerprint=0)
    ok = Resolution(mod=ok_mod, status=AL_DIA, project_name="OK")
    FakeMrClient.routes = {upd.download_url: FakeResp(body=NEW_CONTENT), inst.download_url: FakeResp(body=NEW_CONTENT)}
    running = {"pids": []}
    a = Api(tmp_path / "s.json", get_key=lambda: (None, None), mr_factory=FakeMrClient,
            run_async=lambda fn: fn(), running=lambda d: running["pids"], cache_dir=tmp_path / "cache")
    a.save_setup({"mods_dir": str(mods_dir), "loader": "neoforge", "minecraft_version": "1.21.1"})
    win = FakeWindow()
    a._attach(win)
    # Estado como si se hubiera revisado: filas = instalaciones + resultados.
    plan = DepPlan(items=[upd, inst])
    a._plan, a._rows = plan, [inst, upd, ok]
    a._row_s = ["dep", "up", "ok"]
    return a, win, running


def test_apply_refused_when_minecraft_open(app, mods_dir):
    a, win, running = app
    running["pids"] = [999]
    res = a.apply([0, 1])
    assert res["ok"] is False and res["reason"] == "minecraft"
    assert (mods_dir / "old-1.0.jar").exists() and win.events == []


def test_apply_without_scan_or_selection(app):
    a, win, _ = app
    assert a.apply([2])["ok"] is False  # una fila "ok" no se puede aplicar
    assert a.apply([99])["ok"] is False
    a._plan = None
    assert "revisar" in a.apply([0])["message"].lower()


def test_apply_end_to_end_then_undo(app, mods_dir):
    a, win, _ = app
    assert a.apply([0, 1, 2, 99]) == {"ok": True, "total": 2}
    progress = [p for e, p in win.events if e == "apply_progress"]
    assert [p["state"] for p in progress if p["id"] == 0] == ["downloading", "verified", "installed"]
    assert [p["state"] for p in progress if p["id"] == 1] == ["downloading", "verified", "done"]
    assert progress[-1]["done"] == 2 and progress[-1]["total"] == 2
    event, done = win.events[-1]
    assert event == "apply_done"
    assert (done["updated"], done["installed"], done["failed"]) == (1, 1, [])
    assert done["backup"]["undoable"] is True
    assert sorted(p.name for p in mods_dir.iterdir()) == ["mezz-0.7.1.jar", "old-1.1.jar"]
    assert a._plan is None  # hay que volver a revisar antes de otra actualización

    info = a.backups_info()
    assert info["count"] == 1 and info["last"]["undoable"]
    undo = a.undo_last()
    assert undo["ok"] and undo["restored"] == 1 and undo["removed"] == 2
    assert sorted(p.name for p in mods_dir.iterdir()) == ["old-1.0.jar"]
    assert a.undo_last()["ok"] is False  # ya no queda nada que deshacer

    cleared = a.clear_backups()
    assert cleared["count"] == 1 and a.backups_info()["count"] == 0


def test_undo_refused_when_minecraft_open(app, mods_dir):
    a, win, running = app
    a.apply([0, 1])
    running["pids"] = [1]
    res = a.undo_last()
    assert res["ok"] is False and res["reason"] == "minecraft"
    assert (mods_dir / "old-1.1.jar").exists()
