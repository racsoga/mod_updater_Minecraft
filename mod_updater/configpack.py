"""Configuración de los mods en las copias y en las listas compartidas (hito 8 del plan v4).

- `backup_config`: guarda `config` y `defaultconfigs` de la partida en la copia de seguridad, como
  `config.zip`, solo si han cambiado desde la última vez (se compara una huella).
- `export_zip`: un `.zip` con la lista de mods (`lista.modlist.json`) y la configuración, con rutas
  relativas, sin archivos de más de 5 MB (se dice cuáles se quedan fuera).
- `read_zip` / `preview_import` / `import_config`: abrir uno de esos `.zip` sin fiarse de él (nada
  fuera de `config/` y `defaultconfigs/`, ni rutas que salgan de la carpeta, ni tamaños desmesurados),
  decir qué archivos se sobrescribirían y, al importar, guardar antes los que se van a sobrescribir.
"""

from __future__ import annotations

import hashlib
import json
import os
import zipfile
from pathlib import Path, PurePosixPath

from . import modlist as modlist_mod

FOLDERS = ("config", "defaultconfigs")
MAX_FILE = 5 * 1024 * 1024  # archivos más grandes no se exportan
MAX_TOTAL = 200 * 1024 * 1024  # un zip que se descomprime en más que esto no se importa
LIST_NAME = "lista.modlist.json"


class ConfigPackError(Exception):
    pass


def _files(game_dir: Path) -> list[tuple[str, Path]]:
    """(ruta relativa con /, ruta real) de los archivos de config y defaultconfigs."""
    out = []
    for folder in FOLDERS:
        base = Path(game_dir) / folder
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*")):
            if p.is_file() and not p.is_symlink():
                out.append((PurePosixPath(folder, *p.relative_to(base).parts).as_posix(), p))
    return out


def _fingerprint(files: list[tuple[str, Path]]) -> str:
    h = hashlib.sha1()
    for rel, p in files:
        st = p.stat()
        h.update(f"{rel}|{st.st_size}|{st.st_mtime_ns}\n".encode())
    return h.hexdigest()


def backup_config(game_dir: Path, backup_dir: Path, state_file: Path) -> bool:
    """Guarda la configuración en `backup_dir/config.zip` si ha cambiado. True si se guardó."""
    files = _files(game_dir)
    if not files:
        return False
    fp = _fingerprint(files)
    try:
        last = json.loads(Path(state_file).read_text(encoding="utf-8")).get(str(game_dir))
    except (OSError, ValueError):
        last = None
    if last == fp:
        return False
    with zipfile.ZipFile(Path(backup_dir) / "config.zip", "w", zipfile.ZIP_DEFLATED) as z:
        for rel, p in files:
            z.write(p, rel)
    try:
        data = json.loads(Path(state_file).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    data[str(game_dir)] = fp
    Path(state_file).parent.mkdir(parents=True, exist_ok=True)
    Path(state_file).write_text(json.dumps(data), encoding="utf-8")
    return True


def export_zip(path: Path, modlist_data: dict, game_dir: Path) -> list[str]:
    """Escribe el .zip. Devuelve los archivos que se quedan fuera por tamaño."""
    excluded = []
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(LIST_NAME, modlist_mod.dumps(modlist_data))
        for rel, p in _files(game_dir):
            if p.stat().st_size > MAX_FILE:
                excluded.append(rel)
                continue
            z.write(p, rel)
    return excluded


def _safe(name: str) -> str | None:
    """Ruta relativa segura bajo config/ o defaultconfigs/; None si hay que ignorarla.
    Lanza ConfigPackError si la ruta intenta salir de la carpeta (zip malicioso)."""
    if name.endswith("/"):
        return None
    if name.startswith(("/", "\\")) or ":" in name or "\\" in name:
        raise ConfigPackError("path")
    parts = PurePosixPath(name).parts
    if ".." in parts:
        raise ConfigPackError("path")
    if not parts or parts[0] not in FOLDERS or len(parts) < 2:
        return None  # lo que no es configuración no se importa
    return PurePosixPath(*parts).as_posix()


def read_zip(path: Path) -> tuple[dict, list[str]]:
    """(lista de mods, archivos de configuración que trae). Valida el zip entero."""
    try:
        with zipfile.ZipFile(path) as z:
            infos = z.infolist()
            if sum(i.file_size for i in infos) > MAX_TOTAL:
                raise ConfigPackError("size")
            entries = sorted(n for n in (_safe(i.filename) for i in infos if i.filename != LIST_NAME) if n)
            if LIST_NAME not in z.namelist():
                raise ConfigPackError("list")
            data = modlist_mod.parse(z.read(LIST_NAME).decode("utf-8"))
    except (zipfile.BadZipFile, OSError, UnicodeDecodeError, modlist_mod.ModlistError) as exc:
        raise ConfigPackError("zip") from exc
    return data, entries


def preview_import(path: Path, game_dir: Path) -> dict:
    """Qué archivos de configuración se sobrescribirían y cuáles son nuevos."""
    _, entries = read_zip(path)
    overwrite, new = [], []
    with zipfile.ZipFile(path) as z:
        for rel in entries:
            target = Path(game_dir) / rel
            if target.is_file():
                if target.read_bytes() != z.read(rel):
                    overwrite.append(rel)
            else:
                new.append(rel)
    return {"overwrite": overwrite, "new": new, "total": len(entries)}


def import_config(path: Path, game_dir: Path, backup_dir: Path) -> Path:
    """Escribe la configuración del zip en la partida. Antes guarda en `backup_dir` los archivos
    que se van a sobrescribir. Devuelve `backup_dir`."""
    _, entries = read_zip(path)
    game_dir, backup_dir = Path(game_dir), Path(backup_dir)
    with zipfile.ZipFile(path) as z:
        for rel in entries:
            target = game_dir / rel
            data = z.read(rel)
            if target.is_file():
                if target.read_bytes() == data:
                    continue
                saved = backup_dir / rel
                saved.parent.mkdir(parents=True, exist_ok=True)
                saved.write_bytes(target.read_bytes())
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_name(target.name + ".mu-tmp")
            tmp.write_bytes(data)
            os.replace(tmp, target)
    return backup_dir
