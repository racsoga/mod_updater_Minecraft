"""¿Puedo pasar a otra versión de Minecraft? (hito 6 del plan v4)

Para cada mod activo del perfil mira si hay versión para la versión de destino y el cargador:
- CurseForge: `latestFilesIndexes` de cada mod, en una sola consulta para todos.
- Modrinth: última versión para el destino por hash de cada jar, también en una consulta.

Resultado en tres grupos: **listos** (su web lo tiene), **con alternativa** (solo lo tiene la otra
web, o falta pero otro mod del mismo grupo de `solapamientos.json` sí está) y **faltan** (con la
fecha de su última versión, para ver si el mod sigue vivo). Las librerías van aparte: lo que
importa es si los mods que las usan están listos. También prepara lo que se instalaría en un
perfil nuevo para esa versión (sin tocar el actual).
"""

from __future__ import annotations

from .curseforge import latest_file_ids
from .knowledge import load_knowledge
from .resolver import ACTUALIZABLE, CF, INSTALL, MR, Resolution, choose_for_install

SOURCE_LABEL = {CF: "CurseForge", MR: "Modrinth"}


def _key(r: Resolution) -> str:
    return f"{r.source}:{r.project_id}"


def _cf_ids(r: Resolution) -> list[int]:
    return [int(pid) for src, pid in r.known_ids if src == CF and str(pid).isdigit()]


def _mr_ids(r: Resolution) -> list[str]:
    return [pid for src, pid in r.known_ids if src == MR]


def check(results: list[Resolution], *, target: str, loader: str, curseforge, modrinth, knowledge: dict | None = None) -> dict:
    knowledge = knowledge if knowledge is not None else load_knowledge()
    active = [r for r in results if r.mod is not None and not r.mod.disabled and not r.unreadable and r.source in (CF, MR)]
    groups = knowledge.get("solapamientos", [])

    def group_members(r: Resolution) -> list[dict]:
        mine = {(CF, str(c)) for c in _cf_ids(r)} | {(MR, m) for m in _mr_ids(r)}
        out = []
        for g in groups:
            ids = [({(CF, str(m["curseforge"]))} if m.get("curseforge") else set())
                   | ({(MR, m["modrinth"])} if m.get("modrinth") else set()) for m in g["mods"]]
            if any(mine & x for x in ids):
                out += [m for m, x in zip(g["mods"], ids) if not (mine & x)]
        return out

    # CurseForge: los mods instalados y los de sus grupos, en una consulta.
    cf_ids = {i for r in active for i in _cf_ids(r)}
    cf_ids |= {int(m["curseforge"]) for r in active for m in group_members(r) if m.get("curseforge")}
    cf_info = curseforge.mods(sorted(cf_ids)) if curseforge is not None and cf_ids else {}
    cf_ready = {mid: latest_file_ids(info, target, loader) for mid, info in cf_info.items()}
    cf_ready = {mid: ids for mid, ids in cf_ready.items() if ids}
    mr_latest = modrinth.latest_from_hashes([r.mod.sha1 for r in active], loader, target) if active else {}

    ready, alternative, missing, libs, install_cf, install_mr = [], [], [], [], {}, {}
    for r in active:
        cf_ok = next((i for i in _cf_ids(r) if i in cf_ready), None)
        mr_ok = r.mod.sha1 in mr_latest
        primary = (r.source == CF and cf_ok is not None) or (r.source == MR and mr_ok)
        item = {"name": r.name, "key": _key(r)}
        if primary or cf_ok is not None or mr_ok:
            use_cf = cf_ok is not None and (r.source == CF or not mr_ok)
            if use_cf:
                install_cf[cf_ok] = r
            else:
                install_mr[r.mod.sha1] = r
            if r.is_library:
                libs.append({**item, "ok": True})
            elif primary:
                ready.append(item)
            else:
                alternative.append({**item, "via": SOURCE_LABEL[CF if use_cf else MR], "instead": None})
            continue
        instead = None
        if not r.is_library:
            for m in group_members(r):
                if m.get("curseforge") and int(m["curseforge"]) in cf_ready:
                    instead = m["nombre"]
                elif m.get("modrinth") and modrinth.project_versions(m["modrinth"], loader, target):
                    instead = m["nombre"]
                if instead:
                    break
        if r.is_library:
            libs.append({**item, "ok": False})
        elif instead:
            alternative.append({**item, "via": None, "instead": instead})
        else:
            missing.append({**item, "date": r.project_updated, "lib": False})

    out = {"target": target, "ready": _sorted(ready), "alternative": _sorted(alternative), "missing": _sorted(missing),
           "libs": _sorted(libs), "total": len(ready) + len(alternative) + len(missing), "ready_count": len(ready),
           "no_curseforge": curseforge is None}
    out["install"] = _install(install_cf, install_mr, cf_ready, mr_latest, curseforge)
    return out


def _sorted(items: list[dict]) -> list[dict]:
    return sorted(items, key=lambda i: i["name"].lower())


def _install(install_cf: dict, install_mr: dict, cf_ready: dict, mr_latest: dict, curseforge) -> list[Resolution]:
    """Lo que se descargaría en el perfil nuevo: el archivo de esa versión de cada mod listo."""
    out = []
    if install_cf and curseforge is not None:
        files = curseforge.files(sorted({fid for mid in install_cf for fid in cf_ready[mid]}))
        for mid, r in install_cf.items():
            f = choose_for_install([files[str(fid)] for fid in cf_ready[mid] if str(fid) in files], False)
            if f is not None and f.download_url:
                out.append(Resolution(mod=None, kind=INSTALL, status=ACTUALIZABLE, source=CF, project_id=str(mid),
                                      project_name=r.name, icon_url=r.icon_url, new_version=f.display_name,
                                      new_file_name=f.file_name, download_url=f.download_url, new_sha1=f.sha1,
                                      new_size=f.size, known_ids=set(r.known_ids)))
    for sha, r in install_mr.items():
        v = mr_latest[sha]
        f = v.primary_file
        if f is not None and f.url:
            out.append(Resolution(mod=None, kind=INSTALL, status=ACTUALIZABLE, source=MR, project_id=v.project_id,
                                  project_name=r.name, icon_url=r.icon_url, new_version=v.version_number,
                                  new_file_name=f.filename, download_url=f.url, new_sha1=f.sha1, new_sha512=f.sha512,
                                  new_size=f.size, known_ids=set(r.known_ids)))
    return out


def compare_with_last(now: dict, last: dict | None) -> int | None:
    """Cuántos mods más están listos que la última vez que se miró ese mismo destino."""
    if not last or last.get("target") != now.get("target"):
        return None
    return len(set(now.get("ready") or []) - set(last.get("ready") or []))
