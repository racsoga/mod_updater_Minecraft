"""Instalación de dependencias nuevas, cambios.json y poda de backups."""

import hashlib
import json

from mod_updater.downloader import list_backups, prune_backups
from mod_updater.resolver import ACTUALIZABLE, INSTALL, Resolution
from test_downloader import NEW_CONTENT, FakeResp, make_res, mods_dir, run  # noqa: F401 (fixture)


def make_install(name="mezzconfig-0.7.1.jar", url="https://cdn.modrinth.com/m.jar"):
    return Resolution(
        mod=None, kind=INSTALL, status=ACTUALIZABLE, source="modrinth", project_id="7tEfOcA7",
        project_name="MezzConfig", new_version="0.7.1", new_file_name=name, download_url=url,
        new_sha1=hashlib.sha1(NEW_CONTENT).hexdigest(), required_by=["JEI"],
    )


def test_install_places_new_jar_without_backup(mods_dir):
    res = make_install()
    backup, outcomes, *_ = run(mods_dir, [res], {res.download_url: FakeResp(body=NEW_CONTENT)})
    assert outcomes[0].ok and outcomes[0].message == "instalado"
    assert (mods_dir / "mezzconfig-0.7.1.jar").read_bytes() == NEW_CONTENT
    assert list(backup.glob("*.jar")) == []
    txt = (backup / "cambios.txt").read_text(encoding="utf-8")
    assert "[NUEVO] MezzConfig" in txt and "requerida por JEI" in txt


def test_install_never_overwrites_existing_file(mods_dir):
    (mods_dir / "mezzconfig-0.7.1.jar").write_bytes(b"ya estaba")
    res = make_install()
    _, outcomes, mr, _ = run(mods_dir, [res], {res.download_url: FakeResp(body=NEW_CONTENT)})
    assert not outcomes[0].ok
    assert (mods_dir / "mezzconfig-0.7.1.jar").read_bytes() == b"ya estaba"
    assert mr.calls == []


def test_install_bad_hash_leaves_nothing(mods_dir):
    res = make_install()
    backup, outcomes, *_ = run(mods_dir, [res], {res.download_url: FakeResp(body=b"corrupto")})
    assert not outcomes[0].ok
    assert not (mods_dir / "mezzconfig-0.7.1.jar").exists()
    assert list(backup.glob("*.part")) == []


def test_changelog_json(mods_dir):
    upd = make_res(mods_dir)
    inst = make_install()
    bad = make_res(mods_dir, old_name="bad-1.0.jar", new_name="bad-1.1.jar", url="https://cdn.modrinth.com/bad.jar")
    backup, _, *_ = run(mods_dir, [upd, inst, bad], {
        upd.download_url: FakeResp(body=NEW_CONTENT),
        inst.download_url: FakeResp(body=NEW_CONTENT),
        bad.download_url: FakeResp(status=404),
    })
    data = json.loads((backup / "cambios.json").read_text(encoding="utf-8"))
    assert data["version"] == 1 and data["mods_dir"] == str(mods_dir)
    by_file = {c["new_file"] or c["old_file"]: c for c in data["changes"]}
    u = by_file["old-1.1.jar"]
    assert (u["ok"], u["action"], u["old_file"], u["backup_file"]) == (True, "update", "old-1.0.jar", "old-1.0.jar")
    i = by_file["mezzconfig-0.7.1.jar"]
    assert (i["ok"], i["action"], i["backup_file"], i["required_by"]) == (True, "install", None, ["JEI"])
    assert by_file["bad-1.0.jar"]["ok"] is False


def _fake_backup(mods_dir, name, marker="cambios.json"):
    p = mods_dir.parent / "mods_backup" / name
    p.mkdir(parents=True)
    if marker:
        (p / marker).write_text("{}", encoding="utf-8")
    return p


def test_prune_keeps_newest(mods_dir):
    for n in ["2026-11-01_1000", "2026-11-20_1830", "2026-11-20_1830_2", "2026-11-05_0900"]:
        _fake_backup(mods_dir, n)
    assert [p.name for p in list_backups(mods_dir)] == [
        "2026-11-01_1000", "2026-11-05_0900", "2026-11-20_1830", "2026-11-20_1830_2"]
    removed = prune_backups(mods_dir, keep=1)
    assert [p.name for p in removed] == ["2026-11-01_1000", "2026-11-05_0900", "2026-11-20_1830"]
    assert [p.name for p in list_backups(mods_dir)] == ["2026-11-20_1830_2"]


def test_prune_respects_keep_n_and_never_deletes_all(mods_dir):
    for n in ["2026-11-01_1000", "2026-11-02_1000", "2026-11-03_1000"]:
        _fake_backup(mods_dir, n)
    prune_backups(mods_dir, keep=2)
    assert [p.name for p in list_backups(mods_dir)] == ["2026-11-02_1000", "2026-11-03_1000"]
    prune_backups(mods_dir, keep=0)
    assert [p.name for p in list_backups(mods_dir)] == ["2026-11-03_1000"]


def test_prune_ignores_foreign_folders(mods_dir):
    _fake_backup(mods_dir, "2026-11-01_1000")
    _fake_backup(mods_dir, "2026-11-02_1000")
    foreign1 = _fake_backup(mods_dir, "mis-cosas")
    foreign2 = _fake_backup(mods_dir, "2025-01-01_0000", marker=None)  # formato de fecha pero sin cambios.*
    prune_backups(mods_dir, keep=1)
    assert foreign1.exists() and foreign2.exists()
    assert [p.name for p in list_backups(mods_dir)] == ["2026-11-02_1000"]
