"""Aviso de nuevas versiones de la app (GitHub Releases), como mucho una vez al día."""

import json
import time

import pytest
import requests

from mod_updater.app_update import RELEASES_URL, check_latest, is_newer, parse_version


class Resp:
    def __init__(self, status=200, data=None, text=None):
        self.status_code, self._data, self.text = status, data, text or ""
        self.ok = 200 <= status < 300

    def json(self):
        if self._data is None:
            raise ValueError("no es json")
        return self._data


class Session:
    def __init__(self, resp=None, exc=None):
        self.resp, self.exc, self.calls = resp, exc, []

    def get(self, url, **kw):
        self.calls.append((url, kw))
        if self.exc:
            raise self.exc
        return self.resp


RELEASE = {"tag_name": "v0.4.0", "name": "Mod Updater v0.4.0", "draft": False, "prerelease": False,
           "html_url": "https://github.com/racsoga/mod_updater_Minecraft/releases/tag/v0.4.0",
           "body": "## Novedades\n- Algo **nuevo**\n<script>x</script>"}


@pytest.mark.parametrize("text,expected", [("v0.3.0", (0, 3, 0)), ("0.10.2", (0, 10, 2)), ("v1.2", (1, 2, 0)),
                                           ("v0.4.0-beta.1", None), ("basura", None), ("", None)])
def test_parse_version(text, expected):
    assert parse_version(text) == expected


def test_is_newer():
    assert is_newer("v0.4.0", "0.3.0") and is_newer("0.10.0", "0.9.9")
    assert not is_newer("v0.3.0", "0.3.0") and not is_newer("v0.2.9", "0.3.0") and not is_newer("x", "0.3.0")


def test_newer_release_is_reported_with_clean_notes(tmp_path):
    s = Session(Resp(data=RELEASE))
    info = check_latest("0.3.0", cache_path=tmp_path / "update.json", session=s)
    assert info["version"] == "0.4.0" and info["url"].startswith("https://github.com/racsoga/")
    assert "<strong>nuevo</strong>" in info["notes_html"] and "<script>" not in info["notes_html"]
    assert s.calls[0][0] == RELEASES_URL and s.calls[0][1]["timeout"] <= 10


def test_same_version_or_older_is_nothing(tmp_path):
    assert check_latest("0.4.0", cache_path=tmp_path / "u.json", session=Session(Resp(data=RELEASE))) is None
    assert check_latest("0.5.0", cache_path=tmp_path / "u2.json", session=Session(Resp(data=RELEASE))) is None


def test_once_a_day(tmp_path):
    cache = tmp_path / "update.json"
    s = Session(Resp(data=RELEASE))
    check_latest("0.3.0", cache_path=cache, session=s)
    again = check_latest("0.3.0", cache_path=cache, session=s)
    assert len(s.calls) == 1 and again["version"] == "0.4.0"  # de la caché
    check_latest("0.3.0", cache_path=cache, session=s, now=time.time() + 25 * 3600)
    assert len(s.calls) == 2


def test_without_network_says_nothing(tmp_path):
    s = Session(exc=requests.ConnectionError("sin red"))
    assert check_latest("0.3.0", cache_path=tmp_path / "u.json", session=s) is None
    assert not (tmp_path / "u.json").exists()  # sin red no cuenta como "ya comprobado hoy"


@pytest.mark.parametrize("resp", [Resp(status=403, data={"message": "rate limit"}), Resp(data=None, text="<html>"),
                                  Resp(data=[1, 2]), Resp(data={"tag_name": 5}),
                                  Resp(data=RELEASE | {"html_url": "https://evil.example/x"}),
                                  Resp(data=RELEASE | {"draft": True})])
def test_unexpected_github_responses_are_ignored(tmp_path, resp):
    assert check_latest("0.3.0", cache_path=tmp_path / "u.json", session=Session(resp)) is None


def test_corrupt_cache_is_ignored(tmp_path):
    cache = tmp_path / "update.json"
    cache.write_text("{roto", encoding="utf-8")
    assert check_latest("0.3.0", cache_path=cache, session=Session(Resp(data=RELEASE)))["version"] == "0.4.0"
    assert json.loads(cache.read_text(encoding="utf-8"))["latest"]["version"] == "0.4.0"


def test_api_respects_setting(tmp_path, monkeypatch):
    from mod_updater.gui import api as api_mod
    from mod_updater.gui.api import Api
    from mod_updater.settings import Settings, save_settings
    f = tmp_path / "s.json"
    save_settings(Settings(mods_dir=str(tmp_path), setup_done=True), f)
    a = Api(f, get_key=lambda: (None, None), run_async=lambda fn: fn(), cache_dir=tmp_path / "c")
    monkeypatch.setattr(api_mod, "check_latest", lambda current, **k: {"version": "9.9.9", "url": "https://github.com/racsoga/x", "notes_html": ""})
    assert a.app_update()["version"] == "9.9.9"
    a.save_setup({"mods_dir": str(tmp_path), "loader": "neoforge", "minecraft_version": "1.21.1", "check_updates": False})
    assert a.app_update() is None
