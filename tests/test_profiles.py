"""Perfiles (varias carpetas o instancias): migración, cambio, guardado y detección de launchers."""

import json
from pathlib import Path

import pytest

from mod_updater import profiles
from mod_updater.launchers import detect_instances
from mod_updater.settings import Settings, load_settings, save_settings


def write(path: Path, data) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data) if not isinstance(data, str) else data, encoding="utf-8")
    return path


# --------------------------------------------------------------------------- migración y guardado


def test_old_settings_become_main_profile_without_losing_anything(tmp_path):
    f = write(tmp_path / "settings.json", {"mods_dir": "C:/juego/mods", "minecraft_version": "1.20.1", "loader": "forge",
                                           "allow_beta": True, "backups_to_keep": 3, "setup_done": True, "language": "es"})
    s = load_settings(f)
    assert len(s.profiles) == 1 and s.active_profile == s.profiles[0]["id"]
    p = s.profiles[0]
    assert p["name"] == "Principal"
    assert (p["mods_dir"], p["minecraft_version"], p["loader"], p["allow_beta"], p["backups_to_keep"]) == (
        "C:/juego/mods", "1.20.1", "forge", True, 3)
    assert (s.mods_dir, s.loader, s.language) == ("C:/juego/mods", "forge", "es")


def test_first_run_has_no_profiles_until_setup(tmp_path):
    assert load_settings(tmp_path / "no-existe.json").profiles == []


def test_saving_updates_the_active_profile(tmp_path):
    f = tmp_path / "settings.json"
    s = Settings(mods_dir="C:/a/mods", setup_done=True)
    save_settings(s, f)
    s = load_settings(f)
    s.minecraft_version = "1.21.4"
    save_settings(s, f)
    again = load_settings(f)
    assert again.profiles[0]["minecraft_version"] == "1.21.4" and again.minecraft_version == "1.21.4"


def test_add_switch_rename_remove(tmp_path):
    f = tmp_path / "settings.json"
    s = Settings(mods_dir="C:/a/mods", setup_done=True)
    save_settings(s, f)
    s = load_settings(f)
    pid = profiles.add(s, name="Servidor", mods_dir="C:/srv/mods", minecraft_version="1.21.1", loader="neoforge")
    profiles.switch(s, pid)
    save_settings(s, f)
    s = load_settings(f)
    assert s.active_profile == pid and s.mods_dir == "C:/srv/mods" and len(s.profiles) == 2
    profiles.rename(s, pid, "Servidor de Ana")
    assert profiles.get(s, pid)["name"] == "Servidor de Ana"
    profiles.remove(s, pid)
    assert len(s.profiles) == 1 and s.mods_dir == "C:/a/mods"  # vuelve al que queda
    with pytest.raises(ValueError):
        profiles.remove(s, s.active_profile)  # nunca se borra el último


def test_profile_ids_unique():
    s = Settings(mods_dir="C:/a/mods", setup_done=True)
    profiles.ensure(s)
    a = profiles.add(s, name="Prueba", mods_dir="C:/b/mods", minecraft_version="1.21.1", loader="neoforge")
    b = profiles.add(s, name="Prueba", mods_dir="C:/c/mods", minecraft_version="1.21.1", loader="neoforge")
    assert a != b


def test_two_profiles_same_folder_warned(tmp_path):
    s = Settings(mods_dir=str(tmp_path / "mods"), setup_done=True)
    profiles.ensure(s)
    profiles.add(s, name="Copia", mods_dir=str(tmp_path / "mods") + "/", minecraft_version="1.21.1", loader="neoforge")
    assert len(profiles.same_folder(s)) == 1


def test_missing_folder_is_flagged(tmp_path):
    (tmp_path / "mods").mkdir()
    s = Settings(mods_dir=str(tmp_path / "mods"), setup_done=True)
    profiles.ensure(s)
    profiles.add(s, name="Borrada", mods_dir=str(tmp_path / "ya-no-existe"), minecraft_version="1.21.1", loader="fabric")
    listing = {p["name"]: p for p in profiles.listing(s)}
    assert listing["Principal"]["exists"] and not listing["Borrada"]["exists"]


# --------------------------------------------------------------------------- launchers (ejemplos ficticios)


def test_detect_official_launcher(tmp_path):
    mc = tmp_path / ".minecraft"
    (mc / "mods").mkdir(parents=True)
    (tmp_path / "juego2" / "mods").mkdir(parents=True)
    write(mc / "launcher_profiles.json", {"profiles": {
        "a": {"name": "NeoForge", "lastVersionId": "neoforge-21.1.77", "type": "custom"},
        "b": {"name": "Fabric aparte", "gameDir": str(tmp_path / "juego2"), "lastVersionId": "fabric-loader-0.16.9-1.20.1"},
        "c": {"name": "", "type": "latest-release", "lastVersionId": "latest-release"},
    }})
    found = {i["name"]: i for i in detect_instances(appdata=tmp_path, home=tmp_path / "home")}
    assert found["NeoForge"]["mods_dir"] == str(mc / "mods") and found["NeoForge"]["launcher"] == "official"
    assert (found["NeoForge"]["loader"], found["NeoForge"]["minecraft_version"]) == ("neoforge", "1.21.1")
    assert (found["Fabric aparte"]["loader"], found["Fabric aparte"]["minecraft_version"]) == ("fabric", "1.20.1")


def test_detect_curseforge_instance(tmp_path):
    inst = tmp_path / "home" / "curseforge" / "minecraft" / "Instances" / "Mi pack"
    (inst / "mods").mkdir(parents=True)
    write(inst / "minecraftinstance.json", {"name": "Mi pack", "gameVersion": "1.21.1",
                                            "baseModLoader": {"name": "neoforge-21.1.80"}})
    (i,) = detect_instances(appdata=tmp_path / "vacio", home=tmp_path / "home")
    assert (i["launcher"], i["name"], i["loader"], i["minecraft_version"], i["mods_dir"]) == (
        "curseforge", "Mi pack", "neoforge", "1.21.1", str(inst / "mods"))


def test_detect_prism_instance(tmp_path):
    inst = tmp_path / "PrismLauncher" / "instances" / "Survival"
    (inst / "minecraft" / "mods").mkdir(parents=True)
    write(inst / "instance.cfg", "[General]\nname=Survival con amigos\n")
    write(inst / "mmc-pack.json", {"components": [{"uid": "net.minecraft", "version": "1.20.1"},
                                                  {"uid": "net.fabricmc.fabric-loader", "version": "0.16.9"}]})
    (i,) = detect_instances(appdata=tmp_path, home=tmp_path / "home")
    assert (i["launcher"], i["name"], i["loader"], i["minecraft_version"]) == ("prism", "Survival con amigos", "fabric", "1.20.1")
    assert i["mods_dir"] == str(inst / "minecraft" / "mods")


def test_detect_modrinth_app_profile(tmp_path):
    prof = tmp_path / "ModrinthApp" / "profiles" / "Tecnología"
    (prof / "mods").mkdir(parents=True)
    write(prof / "profile.json", {"metadata": {"name": "Tecnología", "game_version": "1.21.1", "loader": "neoforge"}})
    (i,) = detect_instances(appdata=tmp_path, home=tmp_path / "home")
    assert (i["launcher"], i["name"], i["loader"], i["minecraft_version"]) == ("modrinth", "Tecnología", "neoforge", "1.21.1")


def test_detection_survives_broken_files(tmp_path):
    inst = tmp_path / "home" / "curseforge" / "minecraft" / "Instances" / "Roto"
    (inst / "mods").mkdir(parents=True)
    write(inst / "minecraftinstance.json", "{no es json")
    write(tmp_path / ".minecraft" / "launcher_profiles.json", "basura")
    found = detect_instances(appdata=tmp_path, home=tmp_path / "home")
    assert [i["name"] for i in found] == ["Roto"]  # nombre de la carpeta, sin versión


# --------------------------------------------------------------------------- API


def test_api_profiles_add_switch_remove(tmp_path, monkeypatch):
    from mod_updater.gui import api as api_mod
    from mod_updater.gui.api import Api
    a_mods = tmp_path / "a" / ".minecraft" / "mods"
    b_mods = tmp_path / "srv" / "mods"
    a_mods.mkdir(parents=True)
    b_mods.mkdir(parents=True)
    f = tmp_path / "settings.json"
    save_settings(Settings(mods_dir=str(a_mods), setup_done=True), f)
    api = Api(f, get_key=lambda: (None, None), run_async=lambda fn: fn(), cache_dir=tmp_path / "c")
    state = api.get_state()
    assert [p["name"] for p in state["profiles"]] == ["Principal"]

    assert api.profile_add({"mods_dir": str(tmp_path / "no-existe")})["ok"] is False
    res = api.profile_add({"mods_dir": str(b_mods), "name": "Servidor"})
    assert res["ok"] and [p["name"] for p in res["state"]["profiles"]] == ["Principal", "Servidor"]

    api._results = ["algo revisado"]
    res = api.profile_switch(res["id"])
    assert res["ok"] and res["state"]["settings"]["mods_dir"] == str(b_mods) and api._results == []
    assert api.profile_rename(res["state"]["settings"]["active_profile"], "Server")["ok"]

    monkeypatch.setattr(api_mod, "detect_instances", lambda: [
        {"launcher": "curseforge", "name": "Pack", "mods_dir": str(b_mods), "loader": "neoforge",
         "minecraft_version": "1.21.1", "exists": True},
        {"launcher": "prism", "name": "Otro", "mods_dir": str(tmp_path / "otro"), "loader": "fabric",
         "minecraft_version": "1.20.1", "exists": True}])
    assert [i["name"] for i in api.profile_detect()] == ["Otro"]  # el ya añadido no se repite

    active = api.get_state()["settings"]["active_profile"]
    res = api.profile_remove(active)
    assert res["ok"] and res["switched"] and res["state"]["settings"]["mods_dir"] == str(a_mods)
    assert api.profile_remove(res["state"]["settings"]["active_profile"])["ok"] is False  # el último no


@pytest.mark.real_language
def test_migrated_profile_name_uses_settings_language(tmp_path):
    from mod_updater import i18n
    i18n.set_language("en")  # la interfaz aún en inglés al cargar
    f = write(tmp_path / "settings.json", {"mods_dir": "C:/x/mods", "setup_done": True, "language": "es"})
    assert load_settings(f).profiles[0]["name"] == "Principal"
    assert i18n.get_language() == "en"  # no cambia el idioma de la interfaz
