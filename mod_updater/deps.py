"""Resolución automática de dependencias requeridas (hito 6).

Dado el resultado de la revisión y la selección de mods a actualizar, construye
el plan final:

- Lee las dependencias requeridas de cada versión nueva (CurseForge
  `relationType == 3`, Modrinth `dependency_type == "required"`) y también las
  de los mods instalados que no se actualizan (detecta carpetas ya rotas).
- Una dependencia está instalada si su ID (en su fuente) coincide con el de un
  mod identificado; como respaldo, si su slug/nombre coincide con el `modId` o
  slug de un jar instalado.
- Si falta, busca la última versión compatible y la añade al plan como
  `INSTALL`, con `required_by`. Recursivo y a prueba de ciclos.
- Si la fuente exige una versión concreta (Modrinth `version_id`) más nueva que
  la instalada, añade también la actualización de esa dependencia.
- Si una dependencia no se puede descargar, el mod que la necesita queda
  bloqueado (`DESCARGA_MANUAL`) para no dejar el juego roto, y el bloqueo se
  propaga hacia arriba.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Protocol

from .curseforge import CfFile, CurseForgeClient, latest_file_ids
from .i18n import t
from .modrinth import ModrinthClient
from .resolver import (
    ACTUALIZABLE,
    CF,
    DESCARGA_MANUAL,
    INSTALL,
    MR,
    Dep,
    Resolution,
    cf_deps,
    cf_project_url,
    choose_for_install,
    mr_deps,
)


class Finder(Protocol):
    def find(self, dep: Dep) -> Resolution | None: ...

    def version_date(self, dep: Dep) -> str | None: ...


@dataclass
class Broken:
    """Mod instalado (que no se va a actualizar) al que le falta algo que no se puede instalar solo."""

    res: Resolution
    reason: str
    url: str | None = None


@dataclass
class DepPlan:
    items: list[Resolution]  # lo que se va a aplicar: actualizaciones + instalaciones
    blocked: list[Resolution] = field(default_factory=list)  # actualizaciones bloqueadas
    broken: list[Broken] = field(default_factory=list)  # mods instalados que ya están rotos
    ignored: list[str] = field(default_factory=list)  # dependencias sin versión para este loader
    conflicts: list[str] = field(default_factory=list)  # incompatibilidades declaradas (aviso, no bloquea)

    @property
    def installs(self) -> list[Resolution]:
        return [r for r in self.items if r.kind == INSTALL]

    @property
    def added_updates(self) -> list[Resolution]:
        """Actualizaciones añadidas por ser requeridas por otro mod."""
        return [r for r in self.items if r.kind != INSTALL and r.required_by]


def version_from_filename(file_name: str, game_version: str) -> str | None:
    """`mezzconfig-neoforge-1.21.1-0.7.1.jar` → `0.7.1` (el último número de versión
    que no sea la versión de Minecraft)."""
    stem = re.sub(r"\.jar$", "", file_name, flags=re.IGNORECASE)
    found = [v for v in re.findall(r"\d+(?:\.\d+)+", stem) if v != game_version]
    return found[-1] if found else None


def name_key(text: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def _name_keys(res: Resolution) -> set[str]:
    keys = {name_key(res.slug)}
    if res.mod:
        keys.add(name_key(res.mod.mod_id))
        keys.update(name_key(m) for m in res.mod.extra_mod_ids)
    keys.discard("")
    return keys


def plan_with_dependencies(results: list[Resolution], selected: list[Resolution], finder: Finder) -> DepPlan:
    installed: dict[tuple[str, str], Resolution] = {}
    by_name: dict[str, Resolution] = {}
    for r in results:
        if r.mod is None:
            continue
        for k in r.known_ids:
            installed.setdefault(k, r)
        for n in _name_keys(r):
            by_name.setdefault(n, r)

    plan: list[Resolution] = list(selected)
    in_plan: set[int] = {id(r) for r in plan}
    installs: dict[tuple[str, str], Resolution | None] = {}  # None = buscada y no encontrada
    edges: list[tuple[Resolution, Resolution]] = []  # (padre, dependencia que necesita)
    blocked: dict[int, tuple[str, str | None]] = {}  # id -> (motivo, enlace)
    origin: dict[int, Resolution] = {}
    ignored: list[str] = []

    def block(res: Resolution, reason: str, url: str | None = None) -> None:
        if id(res) not in blocked:
            blocked[id(res)] = (reason, url)
            origin[id(res)] = res

    def add_to_plan(res: Resolution, parent: Resolution) -> None:
        if parent.name not in res.required_by:
            res.required_by.append(parent.name)
        if id(res) not in in_plan:
            plan.append(res)
            in_plan.add(id(res))
            queue.append((res, res.new_deps))

    for r in selected:  # lo elegido (p. ej. una librería en la cesta) no se vuelve a buscar como dependencia
        if r.kind == INSTALL:
            for k in r.known_ids:
                installs[k] = r
    queue: list[tuple[Resolution, list[Dep]]] = [(r, r.new_deps) for r in selected]
    queue += [(r, r.current_deps) for r in results if r.mod is not None and id(r) not in in_plan]

    while queue:
        parent, deps = queue.pop(0)
        for dep in deps:
            have = installed.get(dep.key)
            if have is not None:
                _check_version(dep, have, parent, finder, add_to_plan, edges, block)
                continue

            if dep.key in installs:
                cand = installs[dep.key]
                if cand is None:
                    _ignore(ignored, parent, dep, finder)
                elif cand.status != ACTUALIZABLE:
                    block(parent, _missing_reason(cand), cand.project_url)
                else:
                    add_to_plan(cand, parent)
                    edges.append((parent, cand))
                continue

            cand = finder.find(dep)
            if cand is not None:
                match = next((by_name[n] for n in _name_keys(cand) | {name_key(cand.project_name)} if n in by_name), None)
                if match is not None:
                    # Ya instalado aunque la fuente no lo identificó con este ID.
                    installed[dep.key] = match
                    continue
                cand.kind = INSTALL
                for k in cand.known_ids | {dep.key}:
                    installs[k] = cand
            else:
                installs[dep.key] = None

            if cand is None:
                # Sin ninguna versión para este Minecraft/loader: casi siempre es una
                # dependencia de otro loader (p. ej. "Create Fabric"). Se avisa, no se bloquea.
                _ignore(ignored, parent, dep, finder)
                continue
            if cand.status != ACTUALIZABLE:
                block(parent, _missing_reason(cand), cand.project_url)
                continue
            add_to_plan(cand, parent)
            edges.append((parent, cand))

    # Propagar bloqueos: si una dependencia queda bloqueada, también quien la necesita.
    changed = True
    while changed:
        changed = False
        for parent, child in edges:
            if id(child) in blocked and id(parent) not in blocked:
                reason, url = blocked[id(child)]
                block(parent, t("deps.needs_blocked", name=child.name, reason=reason), url)
                changed = True

    # Quitar del plan lo bloqueado y las instalaciones que ya nadie necesita.
    def needed(res: Resolution) -> bool:
        parents = [p for p, c in edges if c is res]
        return any(id(p) not in blocked for p in parents)

    chosen = {id(r) for r in selected}  # lo que eligió el usuario (también instalaciones desde Explorar)
    final: list[Resolution] = []
    for r in plan:
        if id(r) in blocked:
            continue
        if id(r) not in chosen and (r.kind == INSTALL or r.required_by) and not needed(r):
            continue
        final.append(r)
    final_ids = {id(r) for r in final}
    for r in final:
        r.required_by = [p.name for p, c in edges if c is r and id(p) not in blocked] or r.required_by

    out = DepPlan(items=final, ignored=ignored, conflicts=_conflicts(results, final, installed))
    for rid, (reason, url) in blocked.items():
        res = origin[rid]
        if rid in chosen:
            res.status = DESCARGA_MANUAL
            res.add_note(t("deps.blocked", reason=reason))
            out.blocked.append(res)
            continue
        if res.kind != INSTALL and rid not in final_ids:
            out.broken.append(Broken(res, reason, url))
    return out


def _conflicts(results: list[Resolution], final: list[Resolution], installed: dict) -> list[str]:
    """Avisos de incompatibilidades que declaran los mods (CurseForge relación 5, Modrinth
    "incompatible") entre lo que quedará en la carpeta tras aplicar el plan."""
    planned = {id(r) for r in final}
    after: dict[tuple[str, str], Resolution] = dict(installed)  # lo instalado + lo que se va a instalar
    for r in final:
        if r.kind == INSTALL:
            for k in r.known_ids:
                after[k] = r
    messages: list[str] = []
    seen: set[frozenset] = set()
    for r in [x for x in results if x.mod is not None] + [x for x in final if x.kind == INSTALL]:
        updating = id(r) in planned
        declared = r.new_incompat if updating else r.current_incompat
        for dep in declared:
            other = after.get(dep.key)
            if other is None or other is r:
                continue
            pair = frozenset({id(r), id(other)})
            if pair in seen:
                continue
            seen.add(pair)
            version = r.new_version if updating else r.current_version
            messages.append(t("deps.incompatible", name=r.name, version=version or "", other=other.name))
    return messages


def _ignore(ignored: list[str], parent: Resolution, dep: Dep, finder: Finder) -> None:
    label = finder.describe(dep) if hasattr(finder, "describe") else f"{dep.source} {dep.id}"
    msg = t("deps.ignored", parent=parent.name, dep=label)
    if msg not in ignored:
        ignored.append(msg)


def _missing_reason(cand: Resolution) -> str:
    return t("deps.missing_manual", name=cand.name)


def _check_version(dep, have, parent, finder, add_to_plan, edges, block) -> None:
    """Si la fuente exige una versión concreta más nueva que la instalada."""
    if not dep.version_id or have.source != dep.source or not have.current_date:
        return
    required_date = finder.version_date(dep)
    if not required_date or required_date <= have.current_date:
        return
    if have.status == ACTUALIZABLE:
        add_to_plan(have, parent)
        edges.append((parent, have))
    else:
        block(parent, t("deps.needs_newer", name=have.name), have.project_url)


def _only_prerelease(chosen, candidates) -> bool:
    """La versión elegida es beta/alpha porque no existe ninguna estable."""
    return chosen.version_type != "release" and not any(c.version_type == "release" for c in candidates)


# --------------------------------------------------------------------------- búsqueda real

class DependencyFinder:
    """Busca la última versión compatible de una dependencia en su fuente."""

    def __init__(
        self,
        curseforge: CurseForgeClient | None,
        modrinth: ModrinthClient,
        *,
        loader: str,
        game_version: str,
        allow_beta: bool = False,
    ):
        self.cf, self.mr = curseforge, modrinth
        self.loader, self.game_version, self.allow_beta = loader, game_version, allow_beta

    def describe(self, dep: Dep) -> str:
        """Nombre legible de una dependencia (para avisos)."""
        try:
            if dep.source == CF and self.cf:
                info = self.cf.mods([int(dep.id)]).get(int(dep.id)) or {}
                return info.get("name") or f"CurseForge {dep.id}"
            if dep.source == MR:
                return (self.mr.project(dep.id) or {}).get("title") or f"Modrinth {dep.id}"
        except Exception:  # un aviso no debe romper la revisión
            pass
        return f"{dep.source} {dep.id}"

    def version_date(self, dep: Dep) -> str | None:
        if dep.source == MR and dep.version_id:
            v = self.mr.version(dep.version_id)
            return v.date_published if v else None
        return None

    def find(self, dep: Dep) -> Resolution | None:
        if dep.source == CF:
            res = self._find_cf(dep.id) if self.cf else None
            if res is not None and res.status != ACTUALIZABLE and res.slug:
                # CurseForge no deja descargarla: probar el mismo slug en Modrinth.
                alt = self._find_mr(res.slug)
                if alt is not None and alt.status == ACTUALIZABLE:
                    alt.known_ids |= res.known_ids
                    alt.add_note(t("note.cf_blocked_use_mr"))
                    return alt
            return res
        return self._find_mr(dep.id)

    def _find_cf(self, mod_id: str) -> Resolution | None:
        info = self.cf.mods([int(mod_id)]).get(int(mod_id))
        if not info:
            return None
        ids = latest_file_ids(info, self.game_version, self.loader)
        candidates: list[CfFile] = list(self.cf.files(ids).values()) if ids else []
        if not candidates:
            candidates = self.cf.mod_files(int(mod_id), self.game_version, self.loader)
        f = choose_for_install(candidates, self.allow_beta)
        if f is None:
            return None
        return Resolution(
            mod=None,
            kind=INSTALL,
            status=ACTUALIZABLE if f.download_url else DESCARGA_MANUAL,
            source=CF,
            project_id=str(mod_id),
            project_name=info.get("name"),
            project_url=cf_project_url(info, mod_id),
            slug=info.get("slug"),
            icon_url=(info.get("logo") or {}).get("thumbnailUrl"),
            new_version=version_from_filename(f.file_name, self.game_version) or f.display_name,
            new_channel=f.version_type,
            new_file_name=f.file_name,
            new_size=f.size,
            download_url=f.download_url,
            new_sha1=f.sha1,
            new_deps=cf_deps(f),
            known_ids={(CF, str(mod_id))},
            only_prerelease=_only_prerelease(f, candidates),
        )

    def _find_mr(self, id_or_slug: str) -> Resolution | None:
        project = self.mr.project(id_or_slug)
        if not project:
            return None
        versions = self.mr.project_versions(project["id"], self.loader, self.game_version)
        v = choose_for_install(versions, self.allow_beta)
        if v is None:
            return None
        f = v.primary_file
        return Resolution(
            mod=None,
            kind=INSTALL,
            status=ACTUALIZABLE if f and f.url else DESCARGA_MANUAL,
            source=MR,
            project_id=project["id"],
            project_name=project.get("title"),
            project_url=f"https://modrinth.com/mod/{project.get('slug') or project['id']}",
            slug=project.get("slug"),
            icon_url=project.get("icon_url"),
            new_version=v.version_number,
            new_channel=v.version_type,
            new_file_name=f.filename if f else None,
            new_size=(f.size or 0) if f else 0,
            download_url=f.url if f else None,
            new_sha1=f.sha1 if f else None,
            new_sha512=f.sha512 if f else None,
            new_deps=mr_deps(v),
            known_ids={(MR, project["id"])},
            only_prerelease=_only_prerelease(v, versions),
        )
