"""Hito 5 (v4): búsqueda por mitades del mod que rompe la partida."""

import math
import zipfile
from pathlib import Path

import pytest

from mod_updater import i18n
from mod_updater.bisect import Bisect, apply_round, restore


def setup_module():
    i18n.set_language("es")


def run_to_end(names, culprit, needs=None, excluded=()):
    """Simula a alguien que abre Minecraft cada vuelta: falla mientras el culpable siga activo
    (o le falte una dependencia, que también rompería)."""
    b = Bisect.start(names, needs or {}, excluded=excluded)
    rounds = 0
    while not b.done:
        rounds += 1
        assert rounds <= 20
        active = set(names) - set(b.testing)
        for n in active:  # nunca un mod activo sin su librería
            assert not (set((needs or {}).get(n, ())) & set(b.testing)), (n, b.testing)
        b.answer(fails=culprit in active)
    return b, rounds


@pytest.mark.parametrize("n", [1, 2, 7, 150])
def test_finds_the_culprit_within_the_promised_rounds(n):
    names = [f"mod{i:03}.jar" for i in range(n)]
    for culprit in {names[0], names[n // 2], names[-1]}:
        b, rounds = run_to_end(names, culprit)
        assert b.result == [culprit]
        assert rounds <= Bisect.start(names, {}).max_rounds
    # log2(n) vueltas y una más para confirmar el último si nunca se vio que dejara de fallar.
    assert Bisect.start(names, {}).max_rounds == (math.ceil(math.log2(n)) + 1 if n > 1 else 1)


def test_dependencies_move_together():
    names = ["lib.jar", "a.jar", "b.jar", "c.jar", "d.jar", "e.jar"]
    needs = {"a.jar": ["lib.jar"], "b.jar": ["lib.jar"]}
    b, _ = run_to_end(names, "e.jar", needs)
    assert b.result == ["e.jar"]
    b, _ = run_to_end(names, "lib.jar", needs)
    assert "lib.jar" in b.result  # puede quedar en grupo con quien la necesita si no se pueden separar


def test_group_that_cannot_be_split_is_the_answer():
    names = ["lib.jar", "a.jar"]
    b, _ = run_to_end(names, "a.jar", {"a.jar": ["lib.jar"]})
    assert b.done and set(b.result) <= {"lib.jar", "a.jar"} and "a.jar" in b.result


def test_excluded_mods_are_never_suspects():
    names = [f"m{i}.jar" for i in range(8)]
    b = Bisect.start(names, {}, excluded=["m0.jar", "m1.jar"])
    assert "m0.jar" not in b.suspects and b.max_rounds == 4  # 6 sospechosos
    b, _ = run_to_end(names, "m5.jar", excluded=["m0.jar"])
    assert b.result == ["m5.jar"]


def test_problem_not_in_any_suspect():
    names = [f"m{i}.jar" for i in range(4)]
    b = Bisect.start(names, {})
    while not b.done:
        b.answer(fails=True)  # sigue fallando aunque se desactive cualquier mitad
    assert b.result == []


def test_state_round_trip():
    b = Bisect.start([f"m{i}.jar" for i in range(10)], {"m1.jar": ["m0.jar"]}, names={"m0.jar": "Cero"})
    b.answer(fails=False)
    again = Bisect.from_dict(b.to_dict())
    assert again.to_dict() == b.to_dict() and again.display("m0.jar") == "Cero"


# ---------------------------------------------------------------- en disco

def jar(path: Path):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("a.txt", "x")


def files(d):
    return sorted(p.name for p in d.iterdir())


def test_apply_round_and_restore_on_disk(tmp_path):
    for n in ("a.jar", "b.jar", "c.jar", "d.jar"):
        jar(tmp_path / n)
    jar(tmp_path / "x.jar.disabled")  # ya estaba desactivado: no se toca
    b = Bisect.start(["a.jar", "b.jar", "c.jar", "d.jar"], {})
    apply_round(tmp_path, b)
    assert sorted(f for f in files(tmp_path) if f.endswith(".disabled")) == sorted(
        [f"{n}.disabled" for n in b.testing] + ["x.jar.disabled"])
    b.answer(fails=True)
    apply_round(tmp_path, b)
    restore(tmp_path, b)
    assert files(tmp_path) == ["a.jar", "b.jar", "c.jar", "d.jar", "x.jar.disabled"]


def test_restore_never_overwrites(tmp_path):
    jar(tmp_path / "a.jar")
    jar(tmp_path / "b.jar")
    b = Bisect.start(["a.jar", "b.jar"], {})
    apply_round(tmp_path, b)
    gone = b.testing[0]
    jar(tmp_path / gone)  # alguien puso otra copia con el mismo nombre
    problems = restore(tmp_path, b)
    assert problems == [gone] and (tmp_path / f"{gone}.disabled").exists()


# ---------------------------------------------------------------- API

def make_api(tmp_path, names, needs=None, running=()):
    from mod_updater.gui.api import Api
    from mod_updater.resolver import CF, Dep
    from mod_updater.settings import Settings, save_settings
    from test_toggle import make_jar, res_for
    d = tmp_path / ".minecraft" / "mods"
    d.mkdir(parents=True)
    f = tmp_path / "s.json"
    save_settings(Settings(mods_dir=str(d), setup_done=True), f)
    a = Api(f, get_key=lambda: (None, None), run_async=lambda fn: fn(), cache_dir=tmp_path / "c",
            running=lambda g: list(running))
    results = []
    for n in names:
        make_jar(d / n, n.split(".")[0])
        r = res_for(d / n)
        r.project_name, r.project_id, r.known_ids = n.split(".")[0].capitalize(), n, {(CF, n)}
        r.current_deps = [Dep(CF, x) for x in (needs or {}).get(n, [])]
        results.append(r)
    a._results, a._rows, a._row_s = results, list(results), ["ok"] * len(results)
    return a, d


NAMES = [f"m{i}.jar" for i in range(8)]


def test_api_full_search_restores_everything(tmp_path):
    a, d = make_api(tmp_path, NAMES)
    st = a.bisect_start([])
    assert st["ok"] and st["round"] == 1 and st["left"] == 4 and len(st["testing"]) == 4
    assert sum(f.endswith(".disabled") for f in files(d)) == 4
    culprit = "m6.jar"
    while not st["done"]:
        st = a.bisect_answer((d / culprit).exists())  # falla mientras el culpable siga activo
    assert st["result"] == ["M6"] and st["result_rows"] == [6]
    assert files(d) == NAMES and a.bisect_status() is None


def test_api_dependencies_stay_together(tmp_path):
    a, d = make_api(tmp_path, ["lib.jar", "a.jar", "b.jar", "c.jar"], needs={"a.jar": ["lib.jar"]})
    st = a.bisect_start([])
    off = {f[: -len(".disabled")] for f in files(d) if f.endswith(".disabled")}
    assert not ("lib.jar" in off and "a.jar" not in off)  # a.jar nunca queda activo sin lib.jar


def test_api_resume_after_closing_and_cancel(tmp_path):
    from mod_updater.gui.api import Api
    a, d = make_api(tmp_path, NAMES)
    a.bisect_start([0, 1])  # "seguro que no es este"
    again = Api(a._settings_file, get_key=lambda: (None, None), run_async=lambda fn: fn(),
                cache_dir=tmp_path / "c", running=lambda g: [])
    st = again.bisect_status()
    assert st["active"] and st["round"] == 1 and st["suspects"] == 6
    assert again.bisect_cancel()["ok"] and files(d) == NAMES and again.bisect_status() is None


def test_api_blocks_with_minecraft_open_and_other_changes_while_searching(tmp_path):
    a, d = make_api(tmp_path, NAMES, running=[1])
    assert a.bisect_start([])["reason"] == "minecraft" and files(d) == NAMES
    a, d = make_api(tmp_path / "b", NAMES)
    a.bisect_start([])
    res = a.mods_set_enabled([0], False)
    assert not res["ok"] and res["reason"] == "bisect"


def test_api_needs_a_scan(tmp_path):
    a, d = make_api(tmp_path, NAMES)
    a._results = []
    assert not a.bisect_start([])["ok"]


# ---------------------------------------------------------------- revisión final

def test_balanced_rounds_with_many_dependencies():
    import random
    rng = random.Random(7)
    libs = [f"lib{i:02}.jar" for i in range(15)]
    mods = [f"mod{i:03}.jar" for i in range(135)]
    names = libs + mods
    needs = {m: rng.sample(libs, 3) for m in mods if rng.random() < 0.6}
    worst = 0
    for culprit in rng.sample(names, 40):
        b, rounds = run_to_end(names, culprit, needs)
        assert culprit in b.result
        worst = max(worst, rounds)
    assert worst <= 12  # sin repartir bien las mitades llegaba a 19


def test_rounds_left_is_recomputed():
    b = Bisect.start([f"m{i}.jar" for i in range(16)], {})
    assert b.rounds_left == 5
    b.answer(fails=False)
    assert b.rounds_left == 3  # ya se vio que deja de fallar: no hace falta la vuelta de comprobación


def test_api_rows_follow_the_disk_after_resume_and_finish(tmp_path):
    from mod_updater.gui.api import Api
    a, d = make_api(tmp_path, NAMES)
    st = a.bisect_start([])
    off = [n for n in NAMES if not (d / n).exists()]
    # Se cierra la app y se vuelve a abrir: la revisión ve los de esta vuelta como desactivados.
    again = Api(a._settings_file, get_key=lambda: (None, None), run_async=lambda fn: fn(),
                cache_dir=tmp_path / "c", running=lambda g: [])
    again._results, again._rows, again._row_s = a._results, a._rows, a._row_s
    for r in again._results:
        if r.mod.file_name in off:
            r.mod.path, r.mod.file_name = r.mod.path.with_name(r.mod.file_name + ".disabled"), r.mod.file_name + ".disabled"
    culprit = off[0]
    st = again.bisect_status()
    while not st["done"]:
        st = again.bisect_answer((d / culprit).exists())
    assert files(d) == NAMES and all(not r.mod.disabled and r.mod.path.exists() for r in again._results)
    assert again.mods_set_enabled(st["result_rows"], False)["ok"] and not (d / culprit).exists()


def test_api_undo_and_import_are_blocked_during_a_search(tmp_path):
    a, d = make_api(tmp_path, NAMES)
    a.bisect_start([])
    assert a.undo_last()["reason"] == "bisect" and a.restore_interrupted()["reason"] == "bisect"
    a._import = {"add": [], "update": [], "same": [], "unavailable": [], "remove": [], "mismatch": None}
    assert a.modlist_import_start(False)["reason"] == "bisect"


def test_api_round_that_cannot_disable_is_cancelled(tmp_path):
    a, d = make_api(tmp_path, NAMES)
    from test_toggle import make_jar
    for n in NAMES[:4]:  # la primera mitad no se puede desactivar: ya hay un .disabled con ese nombre
        make_jar(d / f"{n}.disabled", "otro")
    st = a.bisect_start([])
    assert st["ok"] is False and "M0" in st["message"] and a.bisect_status() is None
    assert all((d / n).exists() for n in NAMES)


def test_api_folder_change_and_profile_removal_are_refused_during_a_search(tmp_path):
    a, d = make_api(tmp_path, NAMES)
    a.bisect_start([])
    s = a._settings()
    res = a.save_setup({"mods_dir": str(tmp_path / "otra"), "minecraft_version": s.minecraft_version, "loader": s.loader,
                        "use_curseforge": False, "allow_beta": False, "backups_to_keep": 1, "language": "es"})
    assert res["ok"] is False and res.get("reason") == "bisect"
    assert a.profile_remove(s.active_profile)["ok"] is False


def test_cli_refuses_to_apply_during_a_search(tmp_path, monkeypatch):
    from mod_updater.bisect import active_for_folder
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    from mod_updater.gui.api import Api
    from mod_updater.settings import Settings, save_settings
    from test_toggle import make_jar
    d = tmp_path / ".minecraft" / "mods"
    d.mkdir(parents=True)
    save_settings(Settings(mods_dir=str(d), setup_done=True))
    a = Api(None, get_key=lambda: (None, None), run_async=lambda fn: fn(), running=lambda g: [])
    assert active_for_folder(d) is False
    a._results, a._rows = [], []
    from test_toggle import res_for
    for n in NAMES[:4]:
        make_jar(d / n, n[:-4])
        a._results.append(res_for(d / n))
    a._rows = list(a._results)
    a.bisect_start([])
    assert active_for_folder(d) is True
