"""Lista de mods para compartir: exportar e importar un perfil (`.modlist.json` propio y versionado,
o `.mrpack` estándar de Modrinth), comparar perfiles y lista legible para pegar en un chat.

El archivo nunca lleva rutas, la key ni datos personales: solo nombres, ids de proyecto y de
archivo, versiones, sha1 y categoría.
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from urllib.parse import urlparse

from .resolver import ACTUALIZABLE, CF, INSTALL, MR, UPDATE, Resolution

FORMAT = 1
# Dominios que el formato .mrpack admite para las descargas (normas de Modrinth).
MRPACK_HOSTS = {"cdn.modrinth.com", "github.com", "raw.githubusercontent.com", "gitlab.com"}
MRPACK_LOADER_KEYS = {"neoforge": "neoforge", "forge": "forge", "fabric": "fabric-loader", "quilt": "quilt-loader"}


class ModlistError(ValueError):
    """Archivo que no es una lista de mods válida (corrupto o de un formato posterior)."""


def _pid(source: str | None, project_id):
    if source == CF and project_id is not None and str(project_id).isdigit():
        return int(project_id)
    return project_id


def build(results: list[Resolution], *, minecraft: str, loader: str, app: str) -> dict:
    mods = []
    for r in results:
        if r.mod is None:
            continue
        if r.source in (CF, MR) and r.project_id:
            mods.append({"nombre": r.name, "fuente": r.source, "proyecto": _pid(r.source, r.project_id),
                         "archivo": _pid(r.source, r.current_file_id), "version": r.current_version,
                         "sha1": r.mod.sha1, "categoria": r.categories[0] if r.categories else None})
        else:  # mod que ninguna fuente reconoce: solo se anota (no se puede descargar)
            mods.append({"nombre": r.name, "fuente": None, "nombre_archivo": r.mod.file_name,
                         "version": r.current_version, "sha1": r.mod.sha1})
        if r.mod.disabled:
            mods[-1]["activo"] = False
        if r.pinned:
            mods[-1]["fijado"] = True
    return {"formato": FORMAT, "app": app, "minecraft": minecraft, "cargador": loader, "mods": mods}


def dumps(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def parse(text: str) -> dict:
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise ModlistError("json") from exc
    if not isinstance(data, dict) or not isinstance(data.get("mods"), list):
        raise ModlistError("format")
    if not isinstance(data.get("formato"), int) or data["formato"] > FORMAT:
        raise ModlistError("version")
    if not isinstance(data.get("minecraft"), str) or not isinstance(data.get("cargador"), str):
        raise ModlistError("format")
    for m in data["mods"]:
        if not isinstance(m, dict) or not isinstance(m.get("nombre"), str):
            raise ModlistError("format")
        src = m.get("fuente")
        if src not in (None, CF, MR):
            raise ModlistError("format")
        if src == CF and not (_is_int(m.get("proyecto")) and _is_int(m.get("archivo"))):
            raise ModlistError("format")
        if src == MR and not (isinstance(m.get("proyecto"), str) and m["proyecto"] and isinstance(m.get("archivo"), str) and m["archivo"]):
            raise ModlistError("format")
    return data


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) or (isinstance(value, str) and value.isdigit())


def compare(data: dict, installed: list[Resolution], *, minecraft: str, loader: str) -> dict:
    """Qué cambiaría en el perfil para tener exactamente la lista: añadir, cambiar de versión,
    quitar (opcional), iguales y no disponibles (mods sin fuente que no tenemos)."""
    by_key: dict[tuple, Resolution] = {}
    by_sha = {r.mod.sha1: r for r in installed if r.mod is not None}
    for r in installed:
        for k in r.known_ids:
            by_key[k] = r
    out: dict = {"add": [], "update": [], "same": [], "unavailable": [], "remove": []}
    matched: set[int] = set()
    for m in data["mods"]:
        have = by_sha.get(m.get("sha1"))
        if have is not None:
            out["same"].append(m)
            matched.add(id(have))
            continue
        if not m.get("fuente"):
            out["unavailable"].append(m)
            continue
        have = by_key.get((m["fuente"], str(m["proyecto"])))
        if have is not None:
            out["update"].append(m | {"tienes": have.current_version})
            matched.add(id(have))
        else:
            out["add"].append(m)
    out["remove"] = [r for r in installed if r.mod is not None and id(r) not in matched]
    mismatch = None
    if (data.get("minecraft"), data.get("cargador")) != (minecraft, loader):
        mismatch = {"minecraft": data.get("minecraft"), "loader": data.get("cargador")}
    out["mismatch"] = mismatch
    return out


def readable(results: list[Resolution]) -> str:
    """"Nombre versión" por línea, ordenado: para pegar en un chat."""
    rows = sorted((f"{r.name} {r.current_version or ''}".strip() for r in results if r.mod is not None), key=str.lower)
    return "\n".join(rows)


def _label(mod) -> str:
    return mod.mod_name or Path(mod.file_name).stem


def compare_folders(a: list, b: list) -> dict:
    """Comparación local (sin red) de dos carpetas por modId y sha1."""
    ka = {(m.mod_id or m.file_name): m for m in a}
    kb = {(m.mod_id or m.file_name): m for m in b}
    return {
        "only_a": sorted((_label(ka[k]) for k in ka.keys() - kb.keys()), key=str.lower),
        "only_b": sorted((_label(kb[k]) for k in kb.keys() - ka.keys()), key=str.lower),
        "different": sorted((_label(ka[k]) for k in ka.keys() & kb.keys() if ka[k].sha1 != kb[k].sha1), key=str.lower),
        "same": sum(1 for k in ka.keys() & kb.keys() if ka[k].sha1 == kb[k].sha1),
    }


MRPACK_ENV = {  # lado en que hace falta el mod -> campo env del .mrpack
    "client": {"client": "required", "server": "unsupported"},
    "server": {"client": "unsupported", "server": "required"},
}


def build_mrpack(results: list[Resolution], mr_by_sha1: dict, *, name: str, minecraft: str, loader: str,
                 loader_version: str | None) -> tuple[bytes, list[str]]:
    """Paquete .mrpack con los mods cuyo archivo exacto está en Modrinth (u otro dominio admitido).
    Devuelve (bytes del zip, nombres que no se han podido incluir)."""
    files, excluded = [], []
    for r in results:
        if r.mod is None or r.mod.disabled:  # el paquete es lo que se juega: sin los desactivados
            continue
        v = mr_by_sha1.get(r.mod.sha1)
        f = next((x for x in (v.files if v else []) if x.sha1 == r.mod.sha1), None) or (v.primary_file if v else None)
        if f is None or (urlparse(f.url).hostname or "") not in MRPACK_HOSTS:
            excluded.append(r.name)
            continue
        files.append({"path": f"mods/{f.filename}", "hashes": {"sha1": f.sha1, "sha512": f.sha512},
                      "env": dict(MRPACK_ENV.get(r.side, {"client": "required", "server": "required"})),
                      "downloads": [f.url], "fileSize": f.size})
    deps = {"minecraft": minecraft}
    if loader_version and loader in MRPACK_LOADER_KEYS:
        deps[MRPACK_LOADER_KEYS[loader]] = loader_version
    index = {"formatVersion": 1, "game": "minecraft", "versionId": "1.0", "name": name, "files": files,
             "dependencies": deps}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("modrinth.index.json", json.dumps(index, ensure_ascii=False, indent=2))
    return buf.getvalue(), sorted(excluded, key=str.lower)


def resolve_exact(changes: dict, installed: list[Resolution], *, curseforge, modrinth) -> tuple[list[Resolution], list[dict]]:
    """Resoluciones para instalar las versiones EXACTAS de la lista ("add" y "update" de `compare`).
    Devuelve (resoluciones descargables, mods que hay que descargar a mano o que ya no existen)."""
    by_key = {k: r for r in installed for k in r.known_ids}
    entries = changes["add"] + changes["update"]
    cf_ids = [int(m["archivo"]) for m in entries if m["fuente"] == CF]
    cf_files = curseforge.files(cf_ids) if cf_ids and curseforge is not None else {}
    cf_info = curseforge.mods(sorted({int(m["proyecto"]) for m in entries if m["fuente"] == CF})) if cf_ids and curseforge is not None else {}
    out, manual = [], []
    for m in entries:
        have = by_key.get((m["fuente"], str(m["proyecto"])))
        url = name = version = file_name = sha1 = sha512 = None
        size = 0
        if m["fuente"] == CF:
            f = cf_files.get(str(m["archivo"]))
            info = cf_info.get(int(m["proyecto"])) or {}
            page = (info.get("links") or {}).get("websiteUrl")
            if f is not None and int(f.mod_id) == int(m["proyecto"]):  # el archivo debe ser de ese proyecto
                url, version, file_name, sha1, size = f.download_url, f.display_name, f.file_name, f.sha1, f.size
        else:
            v = modrinth.version(str(m["archivo"])) if modrinth is not None else None
            f = v.primary_file if v else None
            page = f"https://modrinth.com/mod/{m['proyecto']}"
            if f is not None and v.project_id == str(m["proyecto"]):
                url, version, file_name, sha1, sha512, size = f.url, v.version_number, f.filename, f.sha1, f.sha512, f.size
        if not url or not file_name:
            manual.append({"name": m["nombre"], "url": page})
            continue
        out.append(Resolution(
            mod=have.mod if have else None, kind=UPDATE if have else INSTALL, status=ACTUALIZABLE, source=m["fuente"],
            project_id=str(m["proyecto"]), project_name=m["nombre"], project_url=page,
            current_version=have.current_version if have else None, new_version=version,  # la del archivo, no la de la lista
            new_file_name=file_name, download_url=url, new_sha1=sha1, new_sha512=sha512, new_size=size,
            known_ids={(m["fuente"], str(m["proyecto"]))},
            install_disabled=have is None and m.get("activo") is False))  # una actualización conserva tu estado
    return out, manual
