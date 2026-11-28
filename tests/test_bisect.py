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
