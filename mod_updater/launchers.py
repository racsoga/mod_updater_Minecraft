"""Detección de instancias de Minecraft de los launchers más usados (solo lectura).

- Launcher oficial: `%APPDATA%\\.minecraft\\launcher_profiles.json` (gameDir de cada instalación).
- CurseForge: `%USERPROFILE%\\curseforge\\minecraft\\Instances\\*\\minecraftinstance.json`.
- Prism Launcher / MultiMC: `instances\\*\\instance.cfg` + `mmc-pack.json`.
- Modrinth App: `profiles\\*\\profile.json` (si existe; si no, el nombre de la carpeta).

Un archivo roto no detiene la detección: esa instancia sale con lo que se pueda leer.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

LOADER_UIDS = {"net.neoforged": "neoforge", "net.minecraftforge": "forge",
               "net.fabricmc.fabric-loader": "fabric", "org.quiltmc.quilt-loader": "quilt"}
_MC = re.compile(r"\b1\.\d+(?:\.\d+)?\b")


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _neoforge_mc(version: str) -> str | None:
    """NeoForge 21.1.77 -> Minecraft 1.21.1; 21.0.x -> 1.21."""
    m = re.match(r"(\d+)\.(\d+)", version or "")
    if not m:
        return None
    return f"1.{m.group(1)}" + (f".{m.group(2)}" if m.group(2) != "0" else "")


def parse_version_id(version_id: str) -> tuple[str | None, str | None]:
    """(cargador, versión de Minecraft) a partir de un id de versión de launcher."""
    v = (version_id or "").lower()
    if v.startswith("neoforge-"):
        return "neoforge", _neoforge_mc(v.removeprefix("neoforge-"))
    for loader in ("fabric", "quilt", "forge"):
        if loader in v:
            mc = _MC.search(v)
            return loader, mc.group(0) if mc else None
    return None, None


def _entry(launcher: str, name: str, mods: Path, loader: str | None, mc: str | None) -> dict:
    return {"launcher": launcher, "name": name, "mods_dir": str(mods), "loader": loader,
            "minecraft_version": mc, "exists": mods.is_dir()}


def _official(appdata: Path) -> list[dict]:
    root = appdata / ".minecraft"
    data = _read_json(root / "launcher_profiles.json")
    out = []
    for p in (data.get("profiles") or {}).values():
        if not isinstance(p, dict):
            continue
        loader, mc = parse_version_id(p.get("lastVersionId", ""))
        if not loader:
            continue  # instalaciones sin cargador de mods (vanilla)
        game = Path(p["gameDir"]) if p.get("gameDir") else root
        out.append(_entry("official", p.get("name") or p.get("lastVersionId"), game / "mods", loader, mc))
    return out


def _curseforge(home: Path) -> list[dict]:
    out = []
    base = home / "curseforge" / "minecraft" / "Instances"
    for inst in sorted(base.iterdir()) if base.is_dir() else []:
        if not inst.is_dir():
            continue
        data = _read_json(inst / "minecraftinstance.json")
        loader, _ = parse_version_id((data.get("baseModLoader") or {}).get("name", ""))
        out.append(_entry("curseforge", data.get("name") or inst.name, inst / "mods", loader, data.get("gameVersion")))
    return out


def _prism(base: Path, launcher: str) -> list[dict]:
    out = []
    for inst in sorted(base.iterdir()) if base.is_dir() else []:
        cfg = inst / "instance.cfg"
        if not cfg.is_file():
            continue
        name = inst.name
        try:
            m = re.search(r"^name=(.+)$", cfg.read_text(encoding="utf-8", errors="replace"), re.MULTILINE)
            name = m.group(1).strip() if m else name
        except OSError:
            pass
        loader = mc = None
        for comp in _read_json(inst / "mmc-pack.json").get("components") or []:
            if comp.get("uid") == "net.minecraft":
                mc = comp.get("version")
            elif comp.get("uid") in LOADER_UIDS:
                loader = LOADER_UIDS[comp["uid"]]
        game = next((inst / d for d in ("minecraft", ".minecraft") if (inst / d).is_dir()), inst / ".minecraft")
        out.append(_entry(launcher, name, game / "mods", loader, mc))
    return out


def _modrinth(base: Path) -> list[dict]:
    out = []
    for prof in sorted(base.iterdir()) if base.is_dir() else []:
        if not prof.is_dir():
            continue
        data = _read_json(prof / "profile.json")
        meta = data.get("metadata") if isinstance(data.get("metadata"), dict) else data
        out.append(_entry("modrinth", meta.get("name") or prof.name, prof / "mods", meta.get("loader"),
                          meta.get("game_version")))
    return out


def detect_instances(appdata: Path | None = None, home: Path | None = None) -> list[dict]:
    """Instancias encontradas (una por carpeta de mods), con su cargador y versión si se saben."""
    appdata = appdata or Path(os.environ.get("APPDATA") or Path.home())
    home = home or Path.home()
    found = (_official(appdata) + _curseforge(home)
             + _prism(appdata / "PrismLauncher" / "instances", "prism")
             + _prism(appdata / "MultiMC" / "instances", "multimc")
             + _modrinth(appdata / "ModrinthApp" / "profiles")
             + _modrinth(appdata / "com.modrinth.theseus" / "profiles"))
    seen: set[str] = set()
    out = []
    for i in found:
        key = os.path.normcase(os.path.normpath(i["mods_dir"]))
        if key in seen or not i["exists"]:
            continue
        seen.add(key)
        out.append(i)
    return out
