"""Arreglos del barrido de calidad: cierre a mitad, Deshacer, fuentes caídas, jars ilegibles,
credenciales, tamaño de ventana, mods retirados de CurseForge, incompatibilidades, red y errores."""

import errno
import json
from pathlib import Path

import pytest
import requests

from mod_updater import credentials, net
from mod_updater.curseforge import CfMatch, CurseForgeAuthError, CurseForgeClient
from mod_updater.deps import plan_with_dependencies
from mod_updater.downloader import (
    Changelog,
    DownloadError,
    backup_info,
    friendly_error,
    last_undoable,
    make_backup_dir,
    undo_backup,
)
from mod_updater.gui import api as api_mod
from mod_updater.gui.app import DEFAULT_SIZE, MIN_SIZE, initial_size
from mod_updater.i18n import t
from mod_updater.net import ApiError
from mod_updater.resolver import ACTUALIZABLE, AL_DIA, CF, MR, NO_ENCONTRADO, Dep, Resolution, resolve_all
from mod_updater.scanner import scan_folder
from test_deps import FakeFinder, installed
from test_downloader import NEW_CONTENT, FakeResp, make_res, mods_dir, run  # noqa: F401 (fixture)
from test_gui_api import FakeWindow, make_api  # noqa: F401 (fixture)
from test_resolver import FakeCf, FakeClient, cf_file, cf_mod, ver

# --------------------------------------------------------------------------- cerrar a mitad


def test_changelog_exists_from_the_start_and_marks_pending(mods_dir):
    backup = make_backup_dir(mods_dir)
    log = Changelog(backup, mods_dir)
    data = json.loads((backup / "cambios.json").read_text(encoding="utf-8"))
    assert data["complete"] is False and data["changes"] == []

    res = make_res(mods_dir)
    log.begin(res, {"new_file": "old-1.1.jar", "backup_file": "old-1.0.jar"})
    data = json.loads((backup / "cambios.json").read_text(encoding="utf-8"))
    assert data["changes"][0]["state"] == "pending"
    info = backup_info(backup)
    assert info["complete"] is False and info["undoable"] is True


def test_undo_interrupted_update_restores_old_jar(mods_dir):
    """Simula que el proceso murió entre mover el viejo al backup y colocar el nuevo."""
    backup = make_backup_dir(mods_dir)
    res = make_res(mods_dir)
    log = Changelog(backup, mods_dir)
    log.begin(res, {"new_file": "old-1.1.jar", "backup_file": "old-1.0.jar"})
    (mods_dir / "old-1.0.jar").replace(backup / "old-1.0.jar")  # paso 1 hecho, paso 2 no

    result = undo_backup(backup)
    assert result.errors == [] and result.restored == 1
    assert (mods_dir / "old-1.0.jar").read_bytes() == b"viejo jar"


def test_undo_interrupted_after_new_jar_placed(mods_dir):
    backup = make_backup_dir(mods_dir)
    res = make_res(mods_dir)
    log = Changelog(backup, mods_dir)
    log.begin(res, {"new_file": "old-1.1.jar", "backup_file": "old-1.0.jar"})
    (mods_dir / "old-1.0.jar").replace(backup / "old-1.0.jar")
    (mods_dir / "old-1.1.jar").write_bytes(NEW_CONTENT)

    result = undo_backup(backup)
    assert result.errors == [] and (result.restored, result.removed) == (1, 1)
    assert sorted(p.name for p in mods_dir.iterdir()) == ["old-1.0.jar"]


# --------------------------------------------------------------------------- Deshacer busca el último deshacible


def test_last_undoable_skips_failed_later_attempt(mods_dir):
    good = make_res(mods_dir)
    first, outcomes, *_ = run(mods_dir, [good], {good.download_url: FakeResp(body=NEW_CONTENT)})
    assert outcomes[0].ok
    bad = make_res(mods_dir, old_name="b-1.jar", new_name="b-2.jar", url="https://cdn.modrinth.com/b.jar")
    second, outcomes, *_ = run(mods_dir, [bad], {bad.download_url: FakeResp(status=404)})
    assert not outcomes[0].ok and second != first
    assert last_undoable(mods_dir) == first


def test_last_undoable_none_when_everything_undone(mods_dir):
    good = make_res(mods_dir)
    backup, *_ = run(mods_dir, [good], {good.download_url: FakeResp(body=NEW_CONTENT)})
    undo_backup(backup)
    assert last_undoable(mods_dir) is None


# --------------------------------------------------------------------------- una fuente caída


class DownCf(FakeCf):
    def match_fingerprints(self, fps):
        raise ApiError("HTTP 503")


class DownMr(FakeClient):
    def versions_from_hashes(self, sha1s):
        raise ApiError("HTTP 503")


def _resolve(cf, mr, mods, failed):
    return {r.mod.file_name: r for r in resolve_all(
        mods, curseforge=cf, modrinth=mr, loader="neoforge", game_version="1.21.1", failed=failed)}


def test_curseforge_down_uses_modrinth_and_reports_it():
    mr = FakeClient(current={"h1": ver("1.0", "p1", "release", "2024-01-01")},
                    latest={"h1": ver("1.1", "p1", "release", "2024-02-01")})
    failed = []
    r = _resolve(DownCf({}, {}, {}), mr, [cf_mod("a.jar", "h1", 100)], failed)
    assert failed == [CF]
    assert (r["a.jar"].source, r["a.jar"].status) == ("modrinth", ACTUALIZABLE)


def test_modrinth_down_keeps_curseforge_results():
    cur = cf_file(10, 1, "release", "2024-01-01")
    new = cf_file(11, 1, "release", "2024-02-01")
    cf = FakeCf(matches={100: CfMatch(1, cur)}, index={1: [11]}, files={11: new})
    failed = []
    r = _resolve(cf, DownMr({}, {}), [cf_mod("a.jar", "h1", 100), cf_mod("b.jar", "h2", 200)], failed)
    assert failed == [MR]
    assert r["a.jar"].status == ACTUALIZABLE and r["b.jar"].status == NO_ENCONTRADO


def test_both_down_raises():
    with pytest.raises(ApiError):
        _resolve(DownCf({}, {}, {}), DownMr({}, {}), [cf_mod("a.jar", "h1", 100)], [])


def test_rejected_key_still_propagates():
    class BadKeyCf(FakeCf):
        def match_fingerprints(self, fps):
            raise CurseForgeAuthError("rechazada")
    with pytest.raises(CurseForgeAuthError):
        _resolve(BadKeyCf({}, {}, {}), FakeClient({}, {}), [cf_mod("a.jar", "h1", 100)], [])


def test_scan_notice_when_one_source_fails(make_api, monkeypatch, mods_dir):
    a = make_api()
    a.save_setup({"mods_dir": str(mods_dir), "loader": "neoforge", "minecraft_version": "1.21.1"})
    win = FakeWindow()
    a._attach(win)
    monkeypatch.setattr(api_mod, "scan_folder", lambda *x, **k: [])

    def half(mods, failed=None, **kw):
        failed.append(CF)
        return []
    monkeypatch.setattr(api_mod, "resolve_all", half)
    monkeypatch.setattr(api_mod, "DependencyFinder", lambda *x, **k: None)
    a.start_scan()
    event, payload = win.events()[-1]
    assert event == "results"
    assert t("notice.cf_down") in payload["notices"]


# --------------------------------------------------------------------------- mod retirado de CurseForge


class GoneCf(FakeCf):
    def mods(self, ids):
        return {}  # el proyecto ya no existe


def test_cf_gone_falls_back_to_modrinth_with_note():
    cur = cf_file(10, 1, "release", "2024-01-01")
    mr = FakeClient(current={"h1": ver("1.0", "p1", "release", "2024-01-01")},
                    latest={"h1": ver("1.1", "p1", "release", "2024-02-01")})
    r = _resolve(GoneCf(matches={100: CfMatch(1, cur)}, index={}, files={}), mr, [cf_mod("a.jar", "h1", 100)], [])
    assert r["a.jar"].source == "modrinth" and r["a.jar"].status == ACTUALIZABLE
    assert t("note.cf_gone_mr") in r["a.jar"].note
    assert (CF, "1") in r["a.jar"].known_ids


def test_cf_gone_and_not_on_modrinth_keeps_note():
    cur = cf_file(10, 1, "release", "2024-01-01")
    r = _resolve(GoneCf(matches={100: CfMatch(1, cur)}, index={}, files={}), FakeClient({}, {}),
                 [cf_mod("a.jar", "h1", 100)], [])
    assert r["a.jar"].cf_gone and t("note.cf_gone") in r["a.jar"].note


# --------------------------------------------------------------------------- jar ilegible


def test_unreadable_jar_is_skipped_not_fatal(mods_dir, monkeypatch):
    from mod_updater import scanner
    (mods_dir / "good.jar").write_bytes(b"PK")
    (mods_dir / "bad.jar").write_bytes(b"PK")
    real = scanner.scan_file

    def flaky(path):
        if path.name == "bad.jar":
            raise PermissionError(13, "Acceso denegado", str(path))
        return real(path)
    monkeypatch.setattr(scanner, "scan_file", flaky)

    bad = []
    mods = scan_folder(mods_dir, unreadable=bad)
    assert [m.file_name for m in mods] == ["good.jar"]
    assert [p.name for p, _ in bad] == ["bad.jar"]


def test_unreadable_row_requires_attention():
    from mod_updater.deps import DepPlan
    from test_gui_api import _mod
    r = Resolution(mod=_mod("x"), status=NO_ENCONTRADO, unreadable=True, note="no se pudo leer")
    rows = api_mod.serialize([r], DepPlan(items=[]))["rows"]
    assert rows[0]["s"] == "unreadable"


# --------------------------------------------------------------------------- Administrador de credenciales


def _boom(*a):
    raise RuntimeError("WinVault no disponible")


def test_keyring_store_error_is_reported(make_api, mods_dir, monkeypatch):
    a = make_api()
    monkeypatch.setattr(credentials, "set_key", _boom)
    res = a.save_setup({"mods_dir": str(mods_dir), "loader": "neoforge", "minecraft_version": "1.21.1", "key": "k"})
    assert res["ok"] is False and res["field"] == "key" and res["message"] == t("key.store_failed")


def test_keyring_delete_error_is_reported(make_api, monkeypatch):
    a = make_api()
    monkeypatch.setattr(credentials, "delete_key", _boom)
    res = a.forget_key()
    assert res.get("error") == t("key.delete_failed")


# --------------------------------------------------------------------------- ventana


def test_initial_size_fits_small_screens():
    assert initial_size(None) == (DEFAULT_SIZE, MIN_SIZE)
    assert initial_size((2048, 1104))[0] == (DEFAULT_SIZE[0], min(DEFAULT_SIZE[1], int(1104 * 0.92)))
    size, minimum = initial_size((1280, 680))  # portátil 1366×768 al 125 %
    assert size[0] <= 1280 and size[1] <= 680
    assert minimum[0] <= size[0] and minimum[1] <= size[1]


# --------------------------------------------------------------------------- incompatibilidades declaradas


def test_declared_incompatibility_warns():
    a = installed("Alpha", pid="1", status=ACTUALIZABLE, new_deps=[])
    a.new_incompat = [Dep(CF, "2")]
    b = installed("Beta", pid="2")
    plan = plan_with_dependencies([a, b], [a], FakeFinder())
    assert len(plan.conflicts) == 1
    assert "Alpha" in plan.conflicts[0] and "Beta" in plan.conflicts[0]


def test_no_warning_when_incompatible_mod_not_installed():
    a = installed("Alpha", pid="1", status=AL_DIA)
    a.current_incompat = [Dep(CF, "999")]
    plan = plan_with_dependencies([a], [], FakeFinder())
    assert plan.conflicts == []


# --------------------------------------------------------------------------- red


class SeqSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.kwargs = []

    def request(self, method, url, **kw):
        self.kwargs.append(kw)
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def test_retry_listener_and_max_wait(monkeypatch):
    waits, seen = [], []
    monkeypatch.setattr(net.time, "sleep", waits.append)
    monkeypatch.setattr(net, "retry_listener", lambda host, reason, wait: seen.append((host, reason, wait)))
    session = SeqSession([
        requests.ConnectionError("sin red"),
        _resp(429, {"Retry-After": "600"}),
        _resp(200),
    ])
    resp = net.request_with_retry(session, "GET", "https://api.modrinth.com/v2/x")
    assert resp.status_code == 200
    assert seen[0][:2] == ("api.modrinth.com", "offline")
    assert seen[1] == ("api.modrinth.com", "busy", net.MAX_WAIT)
    assert max(waits) == net.MAX_WAIT


def test_offline_error_kind(monkeypatch):
    monkeypatch.setattr(net.time, "sleep", lambda s: None)
    session = SeqSession([requests.ConnectionError("x")] * 2)
    with pytest.raises(ApiError) as e:
        net.request_with_retry(session, "GET", "https://api.modrinth.com/v2/x", retries=1)
    assert e.value.kind == "offline"


def _resp(status, headers=None):
    r = FakeResp(status=status)
    r.headers = headers or {}
    r.text = ""
    r.json = lambda: {"data": {}}
    return r


def test_curseforge_does_not_follow_redirects(monkeypatch):
    monkeypatch.setattr(net.time, "sleep", lambda s: None)
    client = CurseForgeClient("clave-de-prueba")
    session = SeqSession([FakeResp(status=302, location="https://otro-sitio.example/x")])
    client.session = session
    with pytest.raises(ApiError) as e:
        client.check()
    assert session.kwargs[0]["allow_redirects"] is False
    assert "clave-de-prueba" not in str(e.value)


# --------------------------------------------------------------------------- errores claros


def test_friendly_errors_have_no_paths():
    path = r"C:\Users\alguien\AppData\Roaming\.minecraft\mods\x.jar"
    disk = OSError(errno.ENOSPC, "No space left on device", path)
    assert friendly_error(disk) == t("err.disk_full")
    assert friendly_error(PermissionError(13, "Acceso denegado", path)) == t("err.in_use")
    assert friendly_error(requests.ConnectionError(f"fallo {path}")) == t("err.network")
    assert friendly_error(DownloadError("mensaje propio")) == "mensaje propio"
    for exc in (disk, OSError(errno.EIO, "I/O error", path), ValueError(path)):
        assert path not in friendly_error(exc) and "alguien" not in friendly_error(exc)


def test_cli_argparse_is_translated(capsys):
    from mod_updater import main as cli
    with pytest.raises(SystemExit):
        cli.main(["--help"])
    out = capsys.readouterr().out
    assert "usage:" not in out and "options:" not in out
