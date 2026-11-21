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
from collections import Counter
import re
import tomllib
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .i18n import t
from .murmur2 import curseforge_fingerprint

CACHE_VERSION = 3  # 2: añade loader y mc_range; 3: requires y side

# Dependencias que no son mods (el juego, el cargador, Java): no cuentan como "requeridas".
_PLATFORM_IDS = {"minecraft", "neoforge", "forge", "java", "fabricloader", "fabric", "quilt_loader"}


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
    loader: str | None = None
    mc_range: str | None = None
    requires: list[str] = field(default_factory=list)  # modIds obligatorios según el propio jar
    side: str | None = None  # "client" / "server" / "both" si el jar lo declara (Fabric)

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


def _fabric_metadata(jar: zipfile.ZipFile) -> dict:
    try:
        data = json.loads(jar.read("fabric.mod.json").decode("utf-8", errors="replace"))
    except (ValueError, KeyError):
        return {"loader": "fabric"}
    if not isinstance(data, dict):
        return {"loader": "fabric"}
    depends = data.get("depends") if isinstance(data.get("depends"), dict) else {}
    mc = depends.get("minecraft")
    env = data.get("environment")
    return {
        "loader": "fabric",
        "mod_id": data.get("id"),
        "mod_name": data.get("name"),
        "version": data.get("version") if isinstance(data.get("version"), str) else None,
        "mc_range": mc if isinstance(mc, str) else None,
        "requires": [k for k in depends if k not in _PLATFORM_IDS],
        "side": {"client": "client", "server": "server", "*": "both"}.get(env) if isinstance(env, str) else None,
    }


def _mc_range(data: dict, mod_id: str | None) -> str | None:
    """versionRange de la dependencia `minecraft` en un mods.toml."""
    deps = data.get("dependencies") or {}
    groups = [deps.get(mod_id)] if mod_id and isinstance(deps.get(mod_id), list) else []
    groups += [v for v in deps.values() if isinstance(v, list)]
    for group in groups:
        for d in group or []:
            if isinstance(d, dict) and d.get("modId") == "minecraft" and isinstance(d.get("versionRange"), str):
                return d["versionRange"]
    return None


def _toml_requires(data: dict) -> list[str]:
    """modIds obligatorios de [[dependencies.*]] (NeoForge: type="required"; Forge: mandatory=true)."""
    out: list[str] = []
    deps = data.get("dependencies") or {}
    for group in deps.values() if isinstance(deps, dict) else []:
        for d in group if isinstance(group, list) else []:
            if not isinstance(d, dict):
                continue
            mod_id = d.get("modId")
            required = str(d.get("type", "")).lower() == "required" or d.get("mandatory") is True
            if required and isinstance(mod_id, str) and mod_id not in _PLATFORM_IDS and mod_id not in out:
                out.append(mod_id)
    return out


def read_metadata(jar: zipfile.ZipFile) -> dict:
    """Lee modId, nombre, versión, loader y rango de Minecraft del jar."""
    names = set(jar.namelist())
    toml_name = next(
        (n for n in ("META-INF/neoforge.mods.toml", "META-INF/mods.toml") if n in names),
        None,
    )
    if toml_name is None:
        return _fabric_metadata(jar) if "fabric.mod.json" in names else {}
    loader = "neoforge" if toml_name.startswith("META-INF/neoforge") else "forge"

    try:
        raw = jar.read(toml_name).decode("utf-8", errors="replace")
        data = tomllib.loads(raw)
    except (tomllib.TOMLDecodeError, KeyError, zipfile.BadZipFile):
        return {"loader": loader}

    mods = data.get("mods") or []
    if not isinstance(mods, list) or not mods or not isinstance(mods[0], dict):
        return {"loader": loader}
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
        "loader": loader,
        "mod_id": first.get("modId"),
        "mod_name": first.get("displayName"),
        "version": version if isinstance(version, str) else None,
        "extra_mod_ids": [m.get("modId") for m in mods[1:] if isinstance(m, dict) and m.get("modId")],
        "mc_range": _mc_range(data, first.get("modId")),
        "requires": [m for m in _toml_requires(data) if m not in {x.get("modId") for x in mods if isinstance(x, dict)}],
    }


# --------------------------------------------------------------------------- entorno

_VERSION = re.compile(r"\d+\.\d+(?:\.\d+)?")


def _lower_bound(version_range: str) -> str | None:
    """`[1.21.1,1.21.2)` → `1.21.1`; `>=1.21.1` → `1.21.1`; `~1.21` → `1.21`."""
    m = _VERSION.search(version_range or "")
    return m.group(0) if m else None


def peek_folder(mods_dir: Path) -> dict:
    """Vistazo rápido (sin hashes) para la pantalla de bienvenida: cuántos jars
    hay y qué versión de Minecraft y loader se deducen. Solo lectura."""
    if not mods_dir.is_dir():
        return {"exists": False, "jars": 0, "minecraft_version": None, "loader": None}
    infos = []
    jars = [p for p in mods_dir.iterdir() if p.is_file() and p.suffix.lower() == ".jar"]
    for path in jars:
        try:
            with zipfile.ZipFile(path) as jar:
                meta = read_metadata(jar)
        except (zipfile.BadZipFile, OSError):
            continue
        infos.append(ModFile(path=path, file_name=path.name, size=0, sha1="", sha512="", cf_fingerprint=0,
                             loader=meta.get("loader"), mc_range=meta.get("mc_range")))
    mc, loader = detect_environment(infos)
    return {"exists": True, "jars": len(jars), "minecraft_version": mc, "loader": loader}


def detect_environment(mods: list["ModFile"]) -> tuple[str | None, str | None]:
    """Deduce (versión de Minecraft, loader) a partir de los jars: el loader más
    frecuente y la cota inferior de versión más frecuente (prefiriendo x.y.z)."""
    loaders = Counter(m.loader for m in mods if m.loader)
    loader = loaders.most_common(1)[0][0] if loaders else None
    bounds = [b for b in (_lower_bound(m.mc_range) for m in mods if m.mc_range) if b]
    full = Counter(b for b in bounds if b.count(".") == 2)
    pick = full or Counter(bounds)
    return (pick.most_common(1)[0][0] if pick else None), loader


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


def scan_folder(
    mods_dir: Path, cache_path: Path | None = None, progress=None, on_item=None, unreadable: list | None = None
) -> list[ModFile]:
    """Escanea todos los .jar de `mods_dir` (no recursivo).

    `progress`, si se pasa, es un callable(path) que se invoca antes de
    procesar cada archivo que no esté en caché. `on_item`, si se pasa, es un
    callable(índice, total, path) que se invoca para cada jar (en caché o no).

    Un jar que no se puede leer (sin permiso, bloqueado, OneDrive sin descargar...)
    no aborta el escaneo: se salta y se añade `(path, error)` a `unreadable`.
    """
    if not mods_dir.is_dir():
        raise FileNotFoundError(t("scan.no_folder", path=mods_dir))

    cache = _load_cache(cache_path)
    new_cache: dict = {}
    result: list[ModFile] = []

    jars = sorted(p for p in mods_dir.iterdir() if p.is_file() and p.suffix.lower() == ".jar")
    for i, path in enumerate(jars, 1):
        if on_item:
            on_item(i, len(jars), path)
        try:
            st = path.stat()
            key = f"{path.name}|{st.st_size}|{st.st_mtime_ns}"
            info = cache.get(key)
            if info is None:
                if progress:
                    progress(path)
                info = scan_file(path)
        except OSError as exc:
            if unreadable is not None:
                unreadable.append((path, exc))
            continue
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
                loader=info.get("loader"),
                mc_range=info.get("mc_range"),
                requires=info.get("requires", []),
                side=info.get("side"),
            )
        )

    if new_cache != cache:
        _save_cache(cache_path, new_cache)
    return result


def to_dict(mod: ModFile) -> dict:
    d = asdict(mod)
    d["path"] = str(mod.path)
    return d
