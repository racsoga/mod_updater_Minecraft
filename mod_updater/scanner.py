"""Escaneo de la carpeta de mods (solo lectura).

Por cada `.jar` calcula sha1, sha512 y el fingerprint CurseForge, y lee los
metadatos de `META-INF/neoforge.mods.toml` si existen. La carpeta de mods
nunca se modifica: los jar solo se abren en modo lectura.

Los hashes se guardan en una caché (fuera de la carpeta de mods) indexada por
nombre + tamaño + fecha de modificación, para no recalcular en cada ejecución.
"""

from __future__ import annotations

import hashlib
import json
import re
import tomllib
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .murmur2 import curseforge_fingerprint

CACHE_VERSION = 1


@dataclass
class ModFile:
    path: Path
    file_name: str
    size: int
    sha1: str
    sha512: str
    cf_fingerprint: int
    mod_id: str | None = None
    mod_name: str | None = None
    version: str | None = None
    extra_mod_ids: list[str] = field(default_factory=list)

    @property
    def display_name(self) -> str:
        return self.mod_name or self.mod_id or self.file_name


# --------------------------------------------------------------------------- hashes

def compute_hashes(data: bytes) -> dict:
    return {
        "sha1": hashlib.sha1(data).hexdigest(),
        "sha512": hashlib.sha512(data).hexdigest(),
        "cf_fingerprint": curseforge_fingerprint(data),
    }


# --------------------------------------------------------------------------- metadatos

_MANIFEST_VERSION = re.compile(r"^Implementation-Version:\s*(.+)$", re.MULTILINE)


def read_metadata(jar: zipfile.ZipFile) -> dict:
    """Lee modId, nombre y versión de neoforge.mods.toml (o mods.toml)."""
    names = set(jar.namelist())
    toml_name = next(
        (n for n in ("META-INF/neoforge.mods.toml", "META-INF/mods.toml") if n in names),
        None,
    )
    if toml_name is None:
        return {}

    try:
        raw = jar.read(toml_name).decode("utf-8", errors="replace")
        data = tomllib.loads(raw)
    except (tomllib.TOMLDecodeError, KeyError, zipfile.BadZipFile):
        return {}

    mods = data.get("mods") or []
    if not isinstance(mods, list) or not mods or not isinstance(mods[0], dict):
        return {}
    first = mods[0]
    version = first.get("version")

    # "${file.jarVersion}" se resuelve con el Implementation-Version del MANIFEST.
    if isinstance(version, str) and "${" in version:
        version = None
        if "META-INF/MANIFEST.MF" in names:
            manifest = jar.read("META-INF/MANIFEST.MF").decode("utf-8", errors="replace")
            m = _MANIFEST_VERSION.search(manifest)
            if m:
                version = m.group(1).strip()

    return {
        "mod_id": first.get("modId"),
        "mod_name": first.get("displayName"),
        "version": version if isinstance(version, str) else None,
        "extra_mod_ids": [m.get("modId") for m in mods[1:] if isinstance(m, dict) and m.get("modId")],
    }


# --------------------------------------------------------------------------- caché

def _load_cache(cache_path: Path | None) -> dict:
    if cache_path is None or not cache_path.exists():
        return {}
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if data.get("version") != CACHE_VERSION:
        return {}
    return data.get("entries", {})


def _save_cache(cache_path: Path | None, entries: dict) -> None:
    if cache_path is None:
        return
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = cache_path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"version": CACHE_VERSION, "entries": entries}), encoding="utf-8")
    tmp.replace(cache_path)


# --------------------------------------------------------------------------- escaneo

def scan_file(path: Path) -> dict:
    """Calcula hashes y metadatos de un jar. Solo lectura."""
    data = path.read_bytes()
    info = compute_hashes(data)
    try:
        with zipfile.ZipFile(path) as jar:
            info.update(read_metadata(jar))
    except zipfile.BadZipFile:
        pass
    return info


def scan_folder(mods_dir: Path, cache_path: Path | None = None, progress=None) -> list[ModFile]:
    """Escanea todos los .jar de `mods_dir` (no recursivo).

    `progress`, si se pasa, es un callable(path) que se invoca antes de
    procesar cada archivo que no esté en caché.
    """
    if not mods_dir.is_dir():
        raise FileNotFoundError(f"No existe la carpeta de mods: {mods_dir}")

    cache = _load_cache(cache_path)
    new_cache: dict = {}
    result: list[ModFile] = []

    jars = sorted(p for p in mods_dir.iterdir() if p.is_file() and p.suffix.lower() == ".jar")
    for path in jars:
        st = path.stat()
        key = f"{path.name}|{st.st_size}|{st.st_mtime_ns}"
        info = cache.get(key)
        if info is None:
            if progress:
                progress(path)
            info = scan_file(path)
        new_cache[key] = info
        result.append(
            ModFile(
                path=path,
                file_name=path.name,
                size=st.st_size,
                sha1=info["sha1"],
                sha512=info["sha512"],
                cf_fingerprint=info["cf_fingerprint"],
                mod_id=info.get("mod_id"),
                mod_name=info.get("mod_name"),
                version=info.get("version"),
                extra_mod_ids=info.get("extra_mod_ids", []),
            )
        )

    if new_cache != cache:
        _save_cache(cache_path, new_cache)
    return result


def to_dict(mod: ModFile) -> dict:
    d = asdict(mod)
    d["path"] = str(mod.path)
    return d
