import hashlib
import os
from datetime import datetime
from pathlib import Path

import pytest

from mod_updater import downloader
from mod_updater.downloader import apply_updates, make_backup_dir, updatable
from mod_updater.resolver import ACTUALIZABLE, AL_DIA, Resolution
from mod_updater.scanner import ModFile

NEW_CONTENT = b"nuevo jar"


class FakeResp:
    def __init__(self, status=200, body=b"", location=None):
        self.status_code = status
        self.ok = 200 <= status < 400
        self.is_redirect = location is not None
        self.headers = {"Location": location} if location else {}
        self._body = body

    def iter_content(self, n):
        for i in range(0, len(self._body), n):
            yield self._body[i : i + n]

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass


class FakeSession:
    def __init__(self, name, routes):
        self.name, self.routes, self.calls = name, routes, []

    def request(self, method, url, **kw):
        self.calls.append(url)
        return self.routes[url]


@pytest.fixture
def mods_dir(tmp_path):
    d = tmp_path / ".minecraft" / "mods"
    d.mkdir(parents=True)
    return d


def make_res(mods_dir, old_name="old-1.0.jar", new_name="old-1.1.jar",
             url="https://cdn.modrinth.com/x.jar", content=NEW_CONTENT, project="p1", note=""):
    old = mods_dir / old_name
    old.write_bytes(b"viejo jar")
    mod = ModFile(path=old, file_name=old_name, size=9, sha1="", sha512="", cf_fingerprint=0)
    return Resolution(
        mod=mod, status=ACTUALIZABLE, source="modrinth", project_id=project, project_name=project,
        current_version="1.0", new_version="1.1", new_file_name=new_name, download_url=url,
        new_sha1=hashlib.sha1(content).hexdigest(), note=note,
    )


def run(mods_dir, results, mr_routes, cf_routes=None):
    mr = FakeSession("mr", mr_routes)
    cf = FakeSession("cf", cf_routes or {}) if cf_routes is not None else None
    backup, outcomes = apply_updates(results, mods_dir, modrinth_session=mr, curseforge_session=cf)
    return backup, outcomes, mr, cf


def test_success_moves_old_to_backup(mods_dir):
    res = make_res(mods_dir)
    backup, outcomes, *_ = run(mods_dir, [res], {res.download_url: FakeResp(body=NEW_CONTENT)})
    assert outcomes[0].ok
    assert (mods_dir / "old-1.1.jar").read_bytes() == NEW_CONTENT
    assert not (mods_dir / "old-1.0.jar").exists()
    assert (backup / "old-1.0.jar").read_bytes() == b"viejo jar"
    assert backup.parent == mods_dir.parent / "mods_backup"
    assert "[OK]" in (backup / "cambios.txt").read_text(encoding="utf-8")
    assert not list(backup.glob("*.part"))


def test_same_file_name_is_replaced(mods_dir):
    res = make_res(mods_dir, old_name="mod.jar", new_name="mod.jar")
    backup, outcomes, *_ = run(mods_dir, [res], {res.download_url: FakeResp(body=NEW_CONTENT)})
    assert outcomes[0].ok
    assert (mods_dir / "mod.jar").read_bytes() == NEW_CONTENT
    assert (backup / "mod.jar").read_bytes() == b"viejo jar"


def test_hash_mismatch_keeps_old(mods_dir):
    res = make_res(mods_dir)
    backup, outcomes, *_ = run(mods_dir, [res], {res.download_url: FakeResp(body=b"corrupto")})
    assert not outcomes[0].ok
    assert "no coincide" in outcomes[0].message
    assert (mods_dir / "old-1.0.jar").read_bytes() == b"viejo jar"
    assert not (mods_dir / "old-1.1.jar").exists()
    assert not list(backup.glob("*.part"))
    assert "[FALLO]" in (backup / "cambios.txt").read_text(encoding="utf-8")


def test_http_error_keeps_old(mods_dir):
    res = make_res(mods_dir)
    _, outcomes, *_ = run(mods_dir, [res], {res.download_url: FakeResp(status=404)})
    assert not outcomes[0].ok
    assert (mods_dir / "old-1.0.jar").exists()


def test_missing_hash_refuses(mods_dir):
    res = make_res(mods_dir)
    res.new_sha1 = None
    _, outcomes, *_ = run(mods_dir, [res], {res.download_url: FakeResp(body=NEW_CONTENT)})
    assert not outcomes[0].ok
    assert (mods_dir / "old-1.0.jar").exists()


def test_failure_placing_new_restores_old(mods_dir, monkeypatch):
    res = make_res(mods_dir)
    real_replace = os.replace
    calls = []

    def flaky_replace(src, dst):
        calls.append((src, dst))
        if len(calls) == 2:  # 2º paso: colocar el nuevo
            raise PermissionError("archivo en uso")
        return real_replace(src, dst)

    monkeypatch.setattr(downloader.os, "replace", flaky_replace)
    backup, outcomes, *_ = run(mods_dir, [res], {res.download_url: FakeResp(body=NEW_CONTENT)})
    assert not outcomes[0].ok
    assert "restaurado" in outcomes[0].message
    assert (mods_dir / "old-1.0.jar").read_bytes() == b"viejo jar"
    assert not (mods_dir / "old-1.1.jar").exists()
    assert not (backup / "old-1.0.jar").exists()


def test_existing_other_file_with_new_name_is_not_overwritten(mods_dir):
    res = make_res(mods_dir)
    (mods_dir / "old-1.1.jar").write_bytes(b"otro")
    _, outcomes, mr, _ = run(mods_dir, [res], {res.download_url: FakeResp(body=NEW_CONTENT)})
    assert not outcomes[0].ok
    assert (mods_dir / "old-1.1.jar").read_bytes() == b"otro"
    assert (mods_dir / "old-1.0.jar").exists()
    assert mr.calls == []


@pytest.mark.parametrize("bad", ["../escape.jar", "sub/x.jar", "x.exe"])
def test_suspicious_file_names_rejected(mods_dir, bad):
    res = make_res(mods_dir, new_name=bad)
    _, outcomes, mr, _ = run(mods_dir, [res], {})
    assert not outcomes[0].ok
    assert mr.calls == []


def test_http_url_rejected(mods_dir):
    res = make_res(mods_dir, url="http://insecure/x.jar")
    _, outcomes, *_ = run(mods_dir, [res], {})
    assert not outcomes[0].ok
    assert (mods_dir / "old-1.0.jar").exists()


def test_api_key_session_only_for_curseforge_hosts(mods_dir):
    cf_url = "https://edge.forgecdn.net/files/1/2/x.jar"
    res = make_res(mods_dir, url=cf_url)
    cf_routes = {cf_url: FakeResp(status=302, location="https://mediafilez.forgecdn.net/x.jar"),
                 "https://mediafilez.forgecdn.net/x.jar": FakeResp(status=302, location="https://otro-cdn.example/x.jar")}
    mr_routes = {"https://otro-cdn.example/x.jar": FakeResp(body=NEW_CONTENT)}
    _, outcomes, mr, cf = run(mods_dir, [res], mr_routes, cf_routes)
    assert outcomes[0].ok
    assert cf.calls == [cf_url, "https://mediafilez.forgecdn.net/x.jar"]
    assert mr.calls == ["https://otro-cdn.example/x.jar"]  # la sesión sin key


def test_lookalike_host_does_not_get_key(mods_dir):
    url = "https://evilforgecdn.net/x.jar"
    res = make_res(mods_dir, url=url)
    _, outcomes, mr, cf = run(mods_dir, [res], {url: FakeResp(body=NEW_CONTENT)}, {})
    assert outcomes[0].ok
    assert cf.calls == []


def test_backup_dir_gets_suffix_if_exists(mods_dir):
    now = datetime(2026, 11, 20, 18, 30)
    a = make_backup_dir(mods_dir, now)
    b = make_backup_dir(mods_dir, now)
    assert a.name == "2026-11-20_1830"
    assert b.name == "2026-11-20_1830_2"


def test_updatable_skips_duplicates_and_non_updatable(mods_dir):
    r1 = make_res(mods_dir, old_name="a.jar", project="p1")
    r2 = make_res(mods_dir, old_name="b.jar", project="p2", note="¡duplicado en la carpeta!")
    r3 = make_res(mods_dir, old_name="c.jar", project="p3")
    r3.status = AL_DIA
    ok, skipped = updatable([r1, r2, r3])
    assert ok == [r1]
    assert skipped == [r2]
