"""¿Puedo pasar a otra versión de Minecraft? (hito 6 del plan v4)

Para cada mod activo del perfil mira si hay versión para la versión de destino y el cargador:
- CurseForge: `latestFilesIndexes` de cada mod, en una sola consulta para todos.
- Modrinth: última versión para el destino por hash de cada jar, también en una consulta.

Después pasa lo que se instalaría por el mismo planificador de dependencias que las
actualizaciones, pero para la versión de destino: el perfil nuevo lleva las librerías que piden
las versiones nuevas, y un mod al que le falta una librería que no se puede descargar no está listo.

Resultado: **listos**, **con alternativa** (el mismo mod solo en la otra web, que entra en el perfil;
u otro mod del mismo grupo de `solapamientos.json`, que es opcional y va sin marcar) y **faltan**
(con la fecha de su última versión publicada y el motivo). También dice qué no estará en el perfil.
"""

from __future__ import annotations

from .curseforge import latest_file_ids
from .knowledge import load_knowledge
from .resolver import ACTUALIZABLE, CF, INSTALL, MR, Resolution, cf_deps, choose_for_install, mr_deps

SOURCE_LABEL = {CF: "CurseForge", MR: "Modrinth"}


def _key(r: Resolution) -> str:
    return f"{r.source}:{r.project_id}"


def _cf_ids(r: Resolution) -> list[int]:
    return [int(pid) for src, pid in r.known_ids if src == CF and str(pid).isdigit()]


def _mr_ids(r: Resolution) -> list[str]:
    return [pid for src, pid in r.known_ids if src == MR]


def _from_cf(f, name, known_ids, icon=None) -> Resolution:
    return Resolution(mod=None, kind=INSTALL, status=ACTUALIZABLE if f.download_url else "descarga_manual",
                      source=CF, project_id=str(f.mod_id), project_name=name, icon_url=icon,
                      new_version=f.display_name, new_channel=f.version_type, new_file_name=f.file_name,
                      download_url=f.download_url, new_sha1=f.sha1, new_size=f.size, new_deps=cf_deps(f),
                      known_ids=set(known_ids) | {(CF, str(f.mod_id))})


def _from_mr(v, name, known_ids, icon=None) -> Resolution | None:
    f = v.primary_file
    if f is None:
        return None
    return Resolution(mod=None, kind=INSTALL, status=ACTUALIZABLE if f.url else "descarga_manual",
                      source=MR, project_id=v.project_id, project_name=name, icon_url=icon,
                      new_version=v.version_number, new_channel=v.version_type, new_file_name=f.filename,
                      download_url=f.url, new_sha1=f.sha1, new_sha512=f.sha512, new_size=f.size,
                      new_deps=mr_deps(v), known_ids=set(known_ids) | {(MR, v.project_id)})


def check(results: list[Resolution], *, target: str, loader: str, curseforge, modrinth,
          knowledge: dict | None = None, finder=None) -> dict:
    from .deps import DependencyFinder, plan_with_dependencies  # aquí para no crear un import circular
    from .i18n import t

    knowledge = knowledge if knowledge is not None else load_knowledge()
    finder = finder or DependencyFinder(curseforge, modrinth, loader=loader, game_version=target)
    present = [r for r in results if r.mod is not None and not r.mod.disabled and not r.unreadable]
    active = [r for r in present if r.source in (CF, MR)]
    unknown = [r for r in present if r.source not in (CF, MR)]
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

    # CurseForge: los mods instalados y los de sus grupos, en una consulta (más una para los archivos).
    cf_ids = {i for r in active for i in _cf_ids(r)}
    cf_ids |= {int(m["curseforge"]) for r in active for m in group_members(r) if m.get("curseforge")}
    cf_info = curseforge.mods(sorted(cf_ids)) if curseforge is not None and cf_ids else {}
    cf_ready = {mid: ids for mid, info in cf_info.items() if (ids := latest_file_ids(info, target, loader))}
    cf_files = curseforge.files(sorted({f for ids in cf_ready.values() for f in ids})) if cf_ready else {}
    mr_latest = modrinth.latest_from_hashes([r.mod.sha1 for r in active], loader, target) if active else {}
    mr_cache: dict = {}

    def cf_pick(mid):
        return choose_for_install([cf_files[str(f)] for f in cf_ready.get(mid, []) if str(f) in cf_files], False)

    def mr_project(pid):
        if pid not in mr_cache:
            mr_cache[pid] = choose_for_install(modrinth.project_versions(pid, loader, target), False)
        return mr_cache[pid]

    items: dict[int, dict] = {}  # id(candidato) -> elemento del resultado
    candidates: list[Resolution] = []
    missing, alternative, optional = [], [], {}
    for r in active:
        if r.is_library:  # una librería solo entra si la pide un mod listo (lo decide el planificador)
            continue
        cf_mid = next((i for i in _cf_ids(r) if i in cf_ready), None)
        mr_v = mr_latest.get(r.mod.sha1)
        primary = (r.source == CF and cf_mid is not None) or (r.source == MR and mr_v is not None)
        cand = None
        if cf_mid is not None and (r.source == CF or mr_v is None):
            f = cf_pick(cf_mid)
            cand = _from_cf(f, r.name, r.known_ids, r.icon_url) if f is not None else None
        elif mr_v is not None:
            cand = _from_mr(mr_v, r.name, r.known_ids, r.icon_url)
        if cand is not None:
            item = {"name": r.name, "key": _key(r), "beta": cand.new_channel not in (None, "release")}
            if cand.status != ACTUALIZABLE:  # el autor no deja descargarlo desde otras apps
                missing.append({**item, "date": r.project_updated, "why": t("mg.why_manual")})
                continue
            if not primary:
                item["via"] = SOURCE_LABEL[cand.source]
            items[id(cand)] = {**item, "primary": primary}
            candidates.append(cand)
            continue
        alt = None
        for m in group_members(r):
            if m.get("curseforge") and int(m["curseforge"]) in cf_ready and (f := cf_pick(int(m["curseforge"]))):
                alt = _from_cf(f, m["nombre"], {(CF, str(m["curseforge"]))})
            elif m.get("modrinth") and (v := mr_project(m["modrinth"])):
                alt = _from_mr(v, m["nombre"], {(MR, m["modrinth"])})
            if alt is not None and alt.status == ACTUALIZABLE:
                break
            alt = None
        if alt is not None:
            okey = f"{alt.source}:{alt.project_id}"
            optional[okey] = [alt]
            alternative.append({"name": r.name, "key": _key(r), "via": None, "instead": alt.name, "optional": okey})
        else:
            missing.append({"name": r.name, "key": _key(r), "date": r.project_updated, "why": ""})
    for r in unknown:
        missing.append({"name": r.name, "key": None, "date": None, "why": t("mg.why_unknown")})

    # Dependencias de las versiones nuevas, para la versión de destino.
    plan = plan_with_dependencies([], candidates, finder)
    blocked = {id(b) for b in plan.blocked}
    ready = []
    for cand in candidates:
        it = items[id(cand)]
        base = {k: v for k, v in it.items() if k != "primary"}
        if id(cand) in blocked:
            missing.append({**base, "date": None, "why": cand.note})
        elif it["primary"]:
            ready.append(base)
        else:
            alternative.append({**base, "instead": None, "optional": None})
    install = [r for r in plan.items if id(r) not in blocked]
    mods_ids = {id(c) for c in candidates}
    install_mods = sum(1 for r in install if id(r) in mods_ids)
    out = {"target": target, "ready": _sorted(ready), "alternative": _sorted(alternative), "missing": _sorted(missing),
           "total": len(ready) + len(alternative) + len(missing), "ready_count": len(ready),
           "no_curseforge": curseforge is None, "install": install, "install_mods": install_mods,
           "install_libs": len(install) - install_mods, "optional": optional}
    out["wont_have"] = sorted({m["name"] for m in out["missing"]} | {a["name"] for a in out["alternative"] if a["instead"]},
                              key=str.lower)
    return out


def with_optional(base: list[Resolution], extra: list[Resolution], finder) -> tuple[list[Resolution], list[Resolution]]:
    """Lo que se instala añadiendo alternativas elegidas (con sus dependencias). (items, bloqueados)"""
    from .deps import plan_with_dependencies

    plan = plan_with_dependencies([], list(base) + list(extra), finder)
    blocked = {id(b) for b in plan.blocked}
    return [r for r in plan.items if id(r) not in blocked], plan.blocked


def _sorted(items: list[dict]) -> list[dict]:
    return sorted(items, key=lambda i: i["name"].lower())


def compare_with_last(now: dict, last: dict | None) -> int | None:
    """Cuántos mods más están listos que la última vez que se miró ese mismo destino."""
    if not last or last.get("target") != now.get("target"):
        return None
    return len(set(now.get("ready") or []) - set(last.get("ready") or []))
