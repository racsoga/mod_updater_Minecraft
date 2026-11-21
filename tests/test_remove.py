"""Quitar un mod: se mueve a la copia de seguridad (nunca se borra) y Deshacer lo devuelve."""

import json

from mod_updater.downloader import apply_updates, undo_backup
from mod_updater.resolver import AL_DIA, REMOVE, Resolution
from mod_updater.scanner import ModFile
from test_downloader import FakeSession, mods_dir  # noqa: F401 (fixture)


def removal(mods_dir, name="viejo-1.0.jar"):
    p = mods_dir / name
    p.write_bytes(b"contenido")
    mod = ModFile(path=p, file_name=name, size=9, sha1="", sha512="", cf_fingerprint=0)
    return Resolution(mod=mod, kind=REMOVE, status=AL_DIA, source="curseforge", project_id="1", project_name="Viejo",
                      current_version="1.0")


def test_remove_moves_to_backup_and_undo_restores(mods_dir):
    res = removal(mods_dir)
    backup, outcomes = apply_updates([res], mods_dir, modrinth_session=FakeSession("mr", {}), curseforge_session=None)
    assert outcomes[0].ok and not (mods_dir / "viejo-1.0.jar").exists()
    assert (backup / "viejo-1.0.jar").read_bytes() == b"contenido"
    log = json.loads((backup / "cambios.json").read_text(encoding="utf-8"))
    assert log["changes"][0]["action"] == "remove" and log["changes"][0]["new_file"] is None
    assert "[QUITADO] Viejo" in (backup / "cambios.txt").read_text(encoding="utf-8")
    r = undo_backup(backup)
    assert r.errors == [] and r.restored == 1 and (mods_dir / "viejo-1.0.jar").read_bytes() == b"contenido"


def test_remove_missing_file_fails_cleanly(mods_dir):
    res = removal(mods_dir)
    res.mod.path.unlink()
    _, outcomes = apply_updates([res], mods_dir, modrinth_session=FakeSession("mr", {}), curseforge_session=None)
    assert not outcomes[0].ok
