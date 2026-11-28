"""Hito 7 (v4): preparar el servidor (copiar del perfil de cliente lo que hace falta y comparar)."""

import os
import zipfile
from pathlib import Path

import pytest

from mod_updater import i18n
from mod_updater.downloader import last_undoable, undo_backup
from mod_updater.resolver import AL_DIA, CF, Resolution
from mod_updater.scanner import scan_folder
from mod_updater.server import copy_into, plan_copy, server_running


def setup_module():
    i18n.set_language("es")


def jar(path: Path, mod_id: str, version: str = "1.0", extra: bytes = b"") -> Path:
    toml = f'modLoader="javafml"\nloaderVersion="[1,)"\n[[mods]]\nmodId="{mod_id}"\nversion="{version}"\n'
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("META-INF/neoforge.mods.toml", toml)
        z.writestr("x.bin", extra or version.encode())
    return path


def client(tmp_path, specs):
    """specs: [(archivo, modId, versión, lado)] → resultados de revisión del cliente."""
    d = tmp_path / "cliente" / "mods"
    d.mkdir(parents=True)
    for fn, mid, ver, side in specs:
        jar(d / fn, mid, ver)
    out = []
    for m in scan_folder(d):
        spec = next(s for s in specs if s[0] == m.file_name)
        out.append(Resolution(mod=m, status=AL_DIA, source=CF, project_id=m.mod_id, project_name=m.mod_id.capitalize(),
                              current_version=spec[2], side=spec[3], known_ids={(CF, m.mod_id)}))
    return d, out


def server_dir(tmp_path, specs=()):
    d = tmp_path / "servidor" / "mods"
    d.mkdir(parents=True)
    for fn, mid, ver in specs:
        jar(d / fn, mid, ver)
    return d


def names(items):
    return sorted(i["name"] for i in items)


def test_plan_copy_by_side_and_versions(tmp_path):
    cd, results = client(tmp_path, [
        ("create-6.0.4.jar", "create", "6.0.4", "both"),
        ("jei.jar", "jei", "19.0", "both"),
        ("sodium.jar", "sodium", "0.8", "client"),       # solo cliente: no va
        ("lag.jar", "lagfix", "1.0", "server"),          # de servidor: va
        ("raro.jar", "raro", "1.0", None),               # lado desconocido: se pregunta
    ])
    sd = server_dir(tmp_path, [("create-6.0.1.jar", "create", "6.0.1"), ("jei.jar", "jei", "19.0"),
                               ("sodium.jar", "sodium", "0.8"), ("viejo.jar", "viejo", "1.0")])
    # jei es el mismo archivo en los dos lados
    (sd / "jei.jar").write_bytes((cd / "jei.jar").read_bytes())
    plan = plan_copy(results, scan_folder(sd))
    assert names(plan["copy"]) == ["Lagfix"]
    assert [(u["name"], u["server_version"], u["client_version"]) for u in plan["update"]] == [("Create", "6.0.1", "6.0.4")]
    assert names(plan["client_only"]) == ["Sodium"] and names(plan["unknown"]) == ["Raro"]
    assert plan["same"] == 1
    assert plan["extra"] == ["viejo.jar"]  # sobra en el servidor (se queda salvo que se marque)
    assert [c["name"] for c in plan["client_only_on_server"]] == ["Sodium"]  # solo cliente, ya en el servidor


def test_copy_into_with_backup_and_undo(tmp_path):
    cd, results = client(tmp_path, [("create-6.0.4.jar", "create", "6.0.4", "both"), ("lag.jar", "lagfix", "1.0", "server")])
    sd = server_dir(tmp_path, [("create-6.0.1.jar", "create", "6.0.1")])
    plan = plan_copy(results, scan_folder(sd))
    backup, outcomes = copy_into(plan, [], sd)
    assert all(o.ok for o in outcomes)
    assert sorted(p.name for p in sd.iterdir()) == ["create-6.0.4.jar", "lag.jar"]
    assert sorted(p.name for p in cd.iterdir()) == ["create-6.0.4.jar", "lag.jar"]  # el cliente no se toca
    r = undo_backup(last_undoable(sd))
    assert not r.errors and sorted(p.name for p in sd.iterdir()) == ["create-6.0.1.jar"]


def test_unknown_side_only_if_chosen(tmp_path):
    cd, results = client(tmp_path, [("raro.jar", "raro", "1.0", None), ("otro.jar", "otro", "1.0", None)])
    sd = server_dir(tmp_path)
    plan = plan_copy(results, scan_folder(sd))
    copy_into(plan, ["raro.jar"], sd)
    assert sorted(p.name for p in sd.iterdir()) == ["raro.jar"]


def test_server_running_by_command_line_and_world_lock(tmp_path):
    msvcrt = pytest.importorskip("msvcrt")  # el bloqueo de session.lock solo se comprueba en Windows
    game = tmp_path / "servidor"
    (game / "world").mkdir(parents=True)
    lock = game / "world" / "session.lock"
    lock.write_bytes(b"x")
    assert server_running(game, lister=lambda: []) is False
    assert server_running(game, lister=lambda: [(1, f'java -jar server.jar --universe "{game}"')]) is True
    with open(lock, "r+b") as f:  # el servidor de Minecraft bloquea session.lock mientras está abierto
        msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        try:
            assert server_running(game, lister=lambda: []) is True
        finally:
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)


# ---------------------------------------------------------------- cambios de Oscar antes de fusionar

def jar_needing(path: Path, mod_id: str, neoforge_range: str) -> Path:
    toml = (f'modLoader="javafml"\nloaderVersion="[1,)"\n[[mods]]\nmodId="{mod_id}"\nversion="1.0"\n'
            f'[[dependencies.{mod_id}]]\nmodId="neoforge"\ntype="required"\nversionRange="{neoforge_range}"\n')
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("META-INF/neoforge.mods.toml", toml)
    return path


def test_update_never_leaves_two_versions_of_the_same_mod(tmp_path):
    cd, results = client(tmp_path, [("create-6.0.10.jar", "create", "6.0.10", "both")])
    sd = server_dir(tmp_path, [("create-6.0.1.jar", "create", "6.0.1"), ("create-6.0.4.jar", "create", "6.0.4")])
    copy_into(plan_copy(results, scan_folder(sd)), [], sd)
    assert sorted(p.name for p in sd.iterdir()) == ["create-6.0.10.jar"]
    r = undo_backup(last_undoable(sd))
    assert not r.errors and sorted(p.name for p in sd.iterdir()) == ["create-6.0.1.jar", "create-6.0.4.jar"]


def test_warns_when_a_copied_mod_needs_a_newer_neoforge(tmp_path):
    from mod_updater.server import server_loader_version
    cd, results = client(tmp_path, [("nuevo.jar", "nuevo", "1.0", "both"), ("viejo.jar", "viejo", "1.0", "both")])
    jar_needing(cd / "nuevo.jar", "nuevo", "[21.1.200,)")
    jar_needing(cd / "viejo.jar", "viejo", "[21.1.80,)")
    sd = server_dir(tmp_path)
    (sd.parent / "libraries" / "net" / "neoforged" / "neoforge" / "21.1.172").mkdir(parents=True)
    (sd.parent / "libraries" / "net" / "neoforged" / "neoforge" / "21.1.95").mkdir(parents=True)
    assert server_loader_version(sd.parent) == "21.1.172"
    plan = plan_copy(scan_results_again(results), scan_folder(sd), server_loader="21.1.172")
    assert plan["loader_too_old"] == [{"name": "Nuevo", "needs": "21.1.200", "server": "21.1.172"}]


def scan_results_again(results):
    for r in results:  # el jar se reescribió: hash nuevo
        r.mod = next(m for m in scan_folder(r.mod.path.parent) if m.file_name == r.mod.file_name)
    return results


def test_extras_stay_unless_chosen_and_client_only_on_server_can_be_removed(tmp_path):
    cd, results = client(tmp_path, [("create.jar", "create", "6.0", "both"), ("sodium.jar", "sodium", "0.8", "client")])
    sd = server_dir(tmp_path, [("solo-servidor.jar", "lagfix", "1.0"), ("sodium-server.jar", "sodium", "0.8")])
    plan = plan_copy(results, scan_folder(sd))
    assert plan["extra"] == ["solo-servidor.jar"]
    assert [(c["name"], c["server_file"]) for c in plan["client_only_on_server"]] == [("Sodium", "sodium-server.jar")]
    copy_into(plan, [], sd)  # por defecto no se quita nada
    assert sorted(p.name for p in sd.iterdir()) == ["create.jar", "sodium-server.jar", "solo-servidor.jar"]
    plan = plan_copy(results, scan_folder(sd))
    copy_into(plan, [], sd, remove=["sodium-server.jar", "solo-servidor.jar"])
    assert sorted(p.name for p in sd.iterdir()) == ["create.jar"]
    r = undo_backup(last_undoable(sd))
    assert not r.errors and sorted(p.name for p in sd.iterdir()) == ["create.jar", "sodium-server.jar", "solo-servidor.jar"]


# ---------------------------------------------------------------- revisión final

def test_failed_copy_with_the_same_name_keeps_the_original(tmp_path, monkeypatch):
    import shutil as sh
    from mod_updater import server as server_mod
    cd, results = client(tmp_path, [("create.jar", "create", "6.0.10", "both")])
    sd = server_dir(tmp_path, [("create.jar", "create", "6.0.4")])
    original = (sd / "create.jar").read_bytes()

    def broken(src, dst, *a, **k):
        Path(dst).write_bytes(b"medio")  # se corta a mitad (disco lleno, antivirus...)
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(server_mod.shutil, "copy2", broken)
    backup, outcomes = copy_into(plan_copy(results, scan_folder(sd)), [], sd)
    assert not outcomes[0].ok and sorted(p.name for p in sd.iterdir()) == ["create.jar"]
    assert (sd / "create.jar").read_bytes() == original
    monkeypatch.setattr(server_mod.shutil, "copy2", sh.copy2)


def test_extra_mod_ids_count_as_the_same_mod(tmp_path):
    cd, results = client(tmp_path, [("todo-en-uno.jar", "foo", "2.0", "both")])
    results[0].mod.extra_mod_ids = ["foo_core"]
    sd = server_dir(tmp_path, [("foo-1.0.jar", "foo", "1.0"), ("foo-core-1.0.jar", "foo_core", "1.0")])
    copy_into(plan_copy(results, scan_folder(sd)), [], sd)
    assert sorted(p.name for p in sd.iterdir()) == ["todo-en-uno.jar"]  # nunca dos jars con el mismo modId


def test_unknown_side_already_on_the_server_is_preselected(tmp_path):
    cd, results = client(tmp_path, [("raro-2.jar", "raro", "2.0", None), ("nuevo.jar", "nuevo", "1.0", None)])
    sd = server_dir(tmp_path, [("raro-1.jar", "raro", "1.0")])
    plan = plan_copy(results, scan_folder(sd))
    u = {i["name"]: i for i in plan["unknown"]}
    assert u["Raro"]["preselect"] is True and u["Raro"]["server_version"] == "1.0" and u["Nuevo"]["preselect"] is False


def test_nothing_to_do_creates_no_backup(tmp_path):
    from mod_updater.downloader import list_backups
    cd, results = client(tmp_path, [("a.jar", "a", "1.0", "both")])
    sd = server_dir(tmp_path)
    (sd / "a.jar").write_bytes((cd / "a.jar").read_bytes())
    backup, outcomes = copy_into(plan_copy(results, scan_folder(sd)), [], sd)
    assert outcomes == [] and list_backups(sd) == []


# ---------------------------------------------------------------- API

def make_api(tmp_path, running=()):
    from mod_updater import profiles
    from mod_updater.gui.api import Api
    from mod_updater.settings import Settings, load_settings, save_settings
    cd, results = client(tmp_path, [("create-6.0.4.jar", "create", "6.0.4", "both"), ("sodium.jar", "sodium", "0.8", "client")])
    sd = server_dir(tmp_path, [("create-6.0.1.jar", "create", "6.0.1")])
    f = tmp_path / "s.json"
    save_settings(Settings(mods_dir=str(cd), setup_done=True), f)
    s = load_settings(f)
    sid = profiles.add(s, name="Servidor", mods_dir=str(sd), minecraft_version="1.21.1", loader="neoforge")
    save_settings(s, f)
    a = Api(f, get_key=lambda: (None, None), run_async=lambda fn: fn(), cache_dir=tmp_path / "c",
            running=lambda g: list(running))
    a._results, a._rows = results, list(results)
    return a, cd, sd, sid


def test_api_mark_profile_as_server(tmp_path):
    a, cd, sd, sid = make_api(tmp_path)
    st = a.profile_set_server(sid, True)
    assert next(p for p in st["profiles"] if p["id"] == sid)["server"] is True
    assert next(p for p in a.profile_set_server(sid, False)["profiles"] if p["id"] == sid)["server"] is False


def test_api_compare_and_copy_to_the_server(tmp_path, monkeypatch):
    from mod_updater import server as server_mod
    a, cd, sd, sid = make_api(tmp_path)
    monkeypatch.setattr(server_mod, "list_java_processes", lambda: [])
    cmp_ = a.server_compare(sid)
    assert cmp_["ok"] and [u["name"] for u in cmp_["update"]] == ["Create"] and [c["name"] for c in cmp_["client_only"]] == ["Sodium"]
    assert "src" not in cmp_["update"][0]  # sin rutas del PC en la interfaz
    res = a.server_copy(sid, [])
    assert res["ok"] and res["copied"] == 1 and sorted(p.name for p in sd.iterdir()) == ["create-6.0.4.jar"]
    assert sorted(p.name for p in cd.iterdir()) == ["create-6.0.4.jar", "sodium.jar"]


def test_api_copy_refuses_with_the_server_running(tmp_path, monkeypatch):
    from mod_updater import server as server_mod
    a, cd, sd, sid = make_api(tmp_path)
    monkeypatch.setattr(server_mod, "list_java_processes", lambda: [(9, f'java -jar server.jar nogui "{sd.parent}"')])
    a.server_compare(sid)
    res = a.server_copy(sid, [])
    assert not res["ok"] and res["reason"] == "server" and sorted(p.name for p in sd.iterdir()) == ["create-6.0.1.jar"]


def test_api_copy_needs_a_fresh_compare(tmp_path):
    a, cd, sd, sid = make_api(tmp_path)
    assert not a.server_copy(sid, [])["ok"]
    a._results = []
    assert not a.server_compare(sid)["ok"]


def test_api_copy_refuses_during_a_half_split_search(tmp_path, monkeypatch):
    from mod_updater import server as server_mod
    a, cd, sd, sid = make_api(tmp_path)
    monkeypatch.setattr(server_mod, "list_java_processes", lambda: [])
    a.server_compare(sid)
    a._bisect_file(a._settings(), sid).parent.mkdir(parents=True, exist_ok=True)
    a._bisect_file(a._settings(), sid).write_text("{}", encoding="utf-8")  # búsqueda a medias en el servidor
    res = a.server_copy(sid, [])
    assert not res["ok"] and res["reason"] == "bisect"


def test_api_compare_is_forgotten_when_the_client_changes(tmp_path, monkeypatch):
    from mod_updater import server as server_mod
    a, cd, sd, sid = make_api(tmp_path)
    monkeypatch.setattr(server_mod, "list_java_processes", lambda: [])
    a.server_compare(sid)
    a._forget_client_state()  # p. ej. tras actualizar o volver a revisar el perfil de cliente
    assert a.server_copy(sid, [])["ok"] is False
