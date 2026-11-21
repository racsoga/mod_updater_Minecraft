"""Actualizaciones interrumpidas: la poda no borra lo necesario, Deshacer no toca lo que no
cambió y la app ofrece restaurar al abrirse."""

import subprocess
import sys
from pathlib import Path

from mod_updater.downloader import (
    Changelog,
    interrupted_backup,
    list_backups,
    make_backup_dir,
    prune_backups,
    undo_backup,
)
from mod_updater.i18n import t
from test_downloader import NEW_CONTENT, FakeResp, make_res, mods_dir, run  # noqa: F401 (fixture)
from test_gui_api import make_api  # noqa: F401 (fixture)

ROOT = Path(__file__).resolve().parent.parent


def interrupt_after_step1(mods_dir, old="a-1.0.jar", new="a-1.1.jar", project="a"):
    """Deja el disco como si el proceso muriese tras apartar el jar viejo y antes de poner el nuevo."""
    backup = make_backup_dir(mods_dir)
    res = make_res(mods_dir, old_name=old, new_name=new, project=project)
    Changelog(backup, mods_dir).begin(res, {"new_file": new, "backup_file": old})
    (mods_dir / old).replace(backup / old)
    return backup


def update(mods_dir, old, new, project):
    res = make_res(mods_dir, old_name=old, new_name=new, url=f"https://cdn.modrinth.com/{new}", project=project)
    backup, outcomes, *_ = run(mods_dir, [res], {res.download_url: FakeResp(body=NEW_CONTENT)})
    assert outcomes[0].ok
    return backup


# --------------------------------------------------------------------------- poda


def test_prune_keeps_interrupted_backup(mods_dir):
    interrupted = interrupt_after_step1(mods_dir)
    update(mods_dir, "b-1.0.jar", "b-1.1.jar", "b")
    prune_backups(mods_dir, keep=1)
    assert interrupted in list_backups(mods_dir)
    assert (interrupted / "a-1.0.jar").exists()


def test_prune_keeps_backup_whose_mod_is_gone(mods_dir):
    first = update(mods_dir, "a-1.0.jar", "a-1.1.jar", "a")
    (mods_dir / "a-1.1.jar").unlink()  # el mod ya no está en la carpeta (ninguna versión)
    update(mods_dir, "b-1.0.jar", "b-1.1.jar", "b")
    prune_backups(mods_dir, keep=1)
    assert first in list_backups(mods_dir)


def test_prune_still_removes_normal_and_twice_updated_backups(mods_dir):
    first = update(mods_dir, "a-1.0.jar", "a-1.1.jar", "a")
    (mods_dir / "a-1.1.jar").unlink()
    second = update(mods_dir, "a-1.1.jar", "a-1.2.jar", "a")  # el mismo mod, actualizado otra vez
    update(mods_dir, "b-1.0.jar", "b-1.1.jar", "b")
    removed = prune_backups(mods_dir, keep=1)
    assert first in removed and second in removed


def test_prune_removes_restored_interrupted_backup(mods_dir):
    interrupted = interrupt_after_step1(mods_dir)
    undo_backup(interrupted)
    update(mods_dir, "b-1.0.jar", "b-1.1.jar", "b")
    assert interrupted in prune_backups(mods_dir, keep=1)


# --------------------------------------------------------------------------- Deshacer lo que no cambió


def test_undo_interrupted_before_step1_same_name_keeps_old_jar(mods_dir):
    backup = make_backup_dir(mods_dir)
    res = make_res(mods_dir, old_name="a.jar", new_name="a.jar")
    Changelog(backup, mods_dir).begin(res, {"new_file": "a.jar", "backup_file": "a.jar"})
    result = undo_backup(backup)
    assert (mods_dir / "a.jar").read_bytes() == b"viejo jar"
    assert result.errors == [] and (result.restored, result.removed) == (0, 0)


def test_undo_interrupted_before_step1_no_false_error(mods_dir):
    backup = make_backup_dir(mods_dir)
    res = make_res(mods_dir)
    Changelog(backup, mods_dir).begin(res, {"new_file": "old-1.1.jar", "backup_file": "old-1.0.jar"})
    assert undo_backup(backup).errors == []
    assert (mods_dir / "old-1.0.jar").exists()


# --------------------------------------------------------------------------- aviso al abrir


def test_interrupted_backup_detection(mods_dir):
    assert interrupted_backup(mods_dir) is None
    update(mods_dir, "b-1.0.jar", "b-1.1.jar", "b")
    assert interrupted_backup(mods_dir) is None  # una actualización completa no cuenta
    backup = interrupt_after_step1(mods_dir)
    assert interrupted_backup(mods_dir) == backup
    undo_backup(backup)
    assert interrupted_backup(mods_dir) is None


def test_api_offers_and_restores_interrupted(make_api, mods_dir):
    a = make_api()
    a.save_setup({"mods_dir": str(mods_dir), "loader": "neoforge", "minecraft_version": "1.21.1"})
    assert a.interrupted() is None
    backup = interrupt_after_step1(mods_dir)
    info = a.interrupted()
    assert info["path"] == str(backup) and info["complete"] is False and info["changes"] == 1
    res = a.restore_interrupted()
    assert res["ok"] is True and res["restored"] == 1
    assert (mods_dir / "a-1.0.jar").read_bytes() == b"viejo jar"
    assert a.interrupted() is None


# --------------------------------------------------------------------------- línea de comandos


def test_cli_argparse_errors_translated():
    out = subprocess.run([sys.executable, "-m", "mod_updater", "--lang", "es", "--opcion-que-no-existe"],
                         cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    assert out.returncode == 2
    assert "unrecognized arguments" not in out.stderr and "--opcion-que-no-existe" in out.stderr
    out = subprocess.run([sys.executable, "-m", "mod_updater", "--lang", "es", "--keep-backups", "x"],
                         cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    assert "invalid" not in out.stderr and "--keep-backups" in out.stderr


def test_cli_warns_about_interrupted_update(mods_dir, monkeypatch, capsys):
    from mod_updater import main as cli
    interrupt_after_step1(mods_dir)
    monkeypatch.setattr(cli, "scan_folder", lambda *a, **k: [])
    cli.main(["--lang", "es", "--mods-dir", str(mods_dir), "--config", str(mods_dir / "no-existe.toml")])
    out = capsys.readouterr().out.replace("\n", " ")
    assert t("cli.interrupted", date="", path="").split(":")[0] in out
