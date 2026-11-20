"""Confirmación [S/n], aviso de Minecraft abierto y flujo de --apply."""

import hashlib
from pathlib import Path

import pytest
from rich.console import Console

from mod_updater.deps import DepPlan
from mod_updater.main import is_yes, run_apply
from mod_updater.procs import minecraft_running
from mod_updater.resolver import ACTUALIZABLE, Resolution
from mod_updater.scanner import ModFile


@pytest.mark.parametrize("answer", ["", "s", "S", "si", "SI", "sí", "Sí", "y", "Y", "yes", "YES", "  s  "])
def test_yes_answers(answer):
    assert is_yes(answer)


@pytest.mark.parametrize("answer", ["n", "no", "N", "nope", "x", "0"])
def test_no_answers(answer):
    assert not is_yes(answer)


def test_plan_summary_wording():
    from mod_updater.main import plan_summary

    assert plan_summary(0, 1) == "Se instalará 1 dependencia nueva"
    assert plan_summary(1, 0) == "Se actualizará 1 mod"
    assert plan_summary(55, 2) == "Se actualizarán 55 mods y se instalarán 2 dependencias nuevas"


# --------------------------------------------------------------------------- Minecraft abierto

def test_minecraft_running_matches_game_dir():
    game = Path(r"C:\Users\Ana\AppData\Roaming\.minecraft")
    procs = [
        (100, r'"C:\java\javaw.exe" -Xmx4G --gameDir C:\Users\Ana\AppData\Roaming\.minecraft --version neoforge'),
        (200, r'"C:\java\javaw.exe" -jar otro-programa.jar'),
        (300, '"javaw.exe" --gameDir c:/users/ana/appdata/roaming/.MINECRAFT'),
    ]
    assert minecraft_running(game, lister=lambda: procs) == [100, 300]


def test_minecraft_not_running():
    assert minecraft_running(Path(r"C:\x\.minecraft"), lister=lambda: []) == []


# --------------------------------------------------------------------------- run_apply

class Resp:
    status_code, ok, is_redirect, headers = 200, True, False, {}

    def __init__(self, body):
        self.body = body

    def iter_content(self, n):
        yield self.body

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass


class Session:
    def __init__(self, body):
        self.body, self.calls = body, 0

    def request(self, *a, **k):
        self.calls += 1
        return Resp(self.body)


class Client:
    def __init__(self, session):
        self.session = session


@pytest.fixture
def setup(tmp_path):
    mods = tmp_path / ".minecraft" / "mods"
    mods.mkdir(parents=True)
    old = mods / "a-1.0.jar"
    old.write_bytes(b"viejo")
    body = b"nuevo"
    res = Resolution(
        mod=ModFile(path=old, file_name=old.name, size=5, sha1="", sha512="", cf_fingerprint=0),
        status=ACTUALIZABLE, source="modrinth", project_id="p", project_name="A",
        new_file_name="a-1.1.jar", download_url="https://cdn.modrinth.com/a.jar",
        new_sha1=hashlib.sha1(body).hexdigest(),
    )
    return mods, DepPlan(items=[res]), Session(body)


def apply(setup, **kw):
    mods, plan, session = setup
    opts = dict(assume_yes=False, keep_backups=1, running=lambda d: [], ask=lambda q: "")
    opts.update(kw)
    return run_apply(plan, mods, Client(session), None, Console(quiet=True), **opts)


def test_enter_confirms(setup):
    mods, *_ = setup
    assert apply(setup) == 0
    assert (mods / "a-1.1.jar").exists() and not (mods / "a-1.0.jar").exists()


def test_no_cancels_without_touching(setup):
    mods, _, session = setup
    assert apply(setup, ask=lambda q: "n") == 0
    assert (mods / "a-1.0.jar").exists() and session.calls == 0
    assert not (mods.parent / "mods_backup").exists()


def test_question_shows_default_yes(setup):
    seen = []
    apply(setup, ask=lambda q: seen.append(q) or "n")
    assert "[S/n]" in seen[0]


def test_minecraft_open_aborts_even_with_yes(setup):
    mods, _, session = setup
    assert apply(setup, assume_yes=True, running=lambda d: [1234]) == 1
    assert (mods / "a-1.0.jar").exists() and session.calls == 0


def test_running_check_uses_game_dir(setup):
    mods, *_ = setup
    seen = []
    apply(setup, running=lambda d: seen.append(d) or [], ask=lambda q: "n")
    assert seen == [mods.parent]


def test_successful_apply_prunes_old_backups(setup):
    mods, *_ = setup
    old_backup = mods.parent / "mods_backup" / "2020-01-01_0000"
    old_backup.mkdir(parents=True)
    (old_backup / "cambios.json").write_text("{}", encoding="utf-8")
    assert apply(setup) == 0
    remaining = list((mods.parent / "mods_backup").iterdir())
    assert len(remaining) == 1 and remaining[0].name != "2020-01-01_0000"
