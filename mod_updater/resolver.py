"""Decide, para cada jar, si hay una versión nueva y de dónde sacarla.

CurseForge es la fuente principal y Modrinth el respaldo (ver `resolve_all`).
Las dependencias se planifican aparte, en `deps.py`.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Protocol, Sequence, TypeVar

from .i18n import t
from .curseforge import CfFile, CurseForgeClient, latest_file_ids
from .modrinth import ModrinthClient, MrVersion
from .scanner import ModFile

# Estados (los textos para el usuario están en report.py)
AL_DIA = "al_dia"
ACTUALIZABLE = "actualizable"
DESCARGA_MANUAL = "descarga_manual"
NO_ENCONTRADO = "no_encontrado"

# Tipo de entrada del plan
UPDATE = "update"  # un jar instalado (se actualice o no)
INSTALL = "install"  # una dependencia nueva que no está en la carpeta

CF = "curseforge"
MR = "modrinth"

CHANNEL_RANK = {"release": 1, "beta": 2, "alpha": 3}


class VersionLike(Protocol):
    id: str
    version_type: str
    date_published: str


V = TypeVar("V", bound=VersionLike)


@dataclass(frozen=True)
class Dep:
    """Dependencia requerida: proyecto en una fuente, y versión mínima si la fuente la da."""

    source: str
    id: str
    version_id: str | None = None

    @property
    def key(self) -> tuple[str, str]:
        return (self.source, self.id)


@dataclass(eq=False)
class Resolution:
    mod: ModFile | None
    status: str
    kind: str = UPDATE
    source: str | None = None
    project_id: str | None = None
    project_name: str | None = None
    project_url: str | None = None
    slug: str | None = None
    icon_url: str | None = None
    current_version: str | None = None
    current_channel: str | None = None
    current_date: str | None = None
    new_version: str | None = None
    new_channel: str | None = None
    new_file_name: str | None = None
    download_url: str | None = None
    new_sha1: str | None = None
    new_sha512: str | None = None
    note: str = ""
    duplicate: bool = False  # el mismo proyecto aparece varias veces en la carpeta
    only_prerelease: bool = False  # instalación: no existe ninguna versión estable
    newer_prerelease: str | None = None  # al día, pero hay una beta/alpha más nueva (no se propone)
    current_deps: list[Dep] = field(default_factory=list)
    new_deps: list[Dep] = field(default_factory=list)
    known_ids: set[tuple[str, str]] = field(default_factory=set)
    required_by: list[str] = field(default_factory=list)

    @property
    def name(self) -> str:
        if self.project_name:
            return self.project_name
        return self.mod.display_name if self.mod else (self.new_file_name or "?")

    def add_note(self, text: str) -> None:
        self.note = "; ".join(filter(None, [self.note, text]))


def cf_deps(file: CfFile) -> list[Dep]:
    return [Dep(CF, str(mid)) for mid in file.required_mod_ids]


def mr_deps(version: MrVersion) -> list[Dep]:
    return [Dep(MR, pid, vid) for pid, vid in version.required_deps if pid]


# --------------------------------------------------------------------------- regla de canal

def max_allowed_rank(current_channel: str, allow_beta: bool) -> int:
    """release → solo release; beta → hasta beta; alpha → hasta alpha.

    Con `allow_beta` se permite al menos beta aunque el actual sea release.
    """
    current = CHANNEL_RANK.get(current_channel, 1)
    return max(current, CHANNEL_RANK["beta"] if allow_beta else CHANNEL_RANK["release"])


def is_allowed(candidate: VersionLike, current_channel: str, allow_beta: bool) -> bool:
    return CHANNEL_RANK.get(candidate.version_type, 3) <= max_allowed_rank(current_channel, allow_beta)


def choose_update(current: VersionLike, candidates: Sequence[V], allow_beta: bool) -> V | None:
    """Devuelve la versión más nueva permitida que sea posterior a `current`, o None.

    `candidates` puede venir en cualquier orden.
    """
    allowed = [c for c in candidates if is_allowed(c, current.version_type, allow_beta)]
    if not allowed:
        return None
    best = max(allowed, key=lambda c: c.date_published)
    if best.id == current.id or best.date_published <= current.date_published:
        return None
    return best


def newer_prerelease(current: VersionLike, candidates: Sequence[V]) -> V | None:
    """La versión más nueva que `current` aunque su canal no esté permitido (para avisar)."""
    newer = [c for c in candidates if c.id != current.id and c.date_published > current.date_published]
    return max(newer, key=lambda c: c.date_published) if newer else None


def choose_for_install(candidates: Sequence[V], allow_beta: bool) -> V | None:
    """Versión para instalar algo nuevo: la release más reciente (o beta con
    `allow_beta`). Si solo hay betas/alphas, la más reciente de ellas."""
    if not candidates:
        return None
    limit = CHANNEL_RANK["beta"] if allow_beta else CHANNEL_RANK["release"]
    allowed = [c for c in candidates if CHANNEL_RANK.get(c.version_type, 3) <= limit]
    return max(allowed or candidates, key=lambda c: c.date_published)


# --------------------------------------------------------------------------- versión legible

def guess_version(current_file: str, current_version: str | None, new_file: str) -> str | None:
    """Deduce la versión del archivo nuevo usando el nombre del actual como plantilla.

    `balm-neoforge-1.21.1-21.0.56.jar` con versión `21.0.56` da la plantilla
    `balm-neoforge-1.21.1-{v}.jar`; aplicada a `balm-neoforge-1.21.1-21.0.67.jar`
    devuelve `21.0.67`. Si la plantilla no encaja, devuelve None.
    """
    if not current_version or current_file.count(current_version) != 1:
        return None
    before, after = current_file.split(current_version)
    m = re.fullmatch(re.escape(before) + r"(.+?)" + re.escape(after), new_file, flags=re.IGNORECASE)
    return m.group(1) if m else None


# --------------------------------------------------------------------------- Modrinth

def resolve_with_modrinth(
    mods: list[ModFile],
    client: ModrinthClient,
    *,
    loader: str,
    game_version: str,
    allow_beta: bool = False,
) -> list[Resolution]:
    sha1s = [m.sha1 for m in mods]
    current = client.versions_from_hashes(sha1s)
    identified = [h for h in sha1s if h in current]
    latest = client.latest_from_hashes(identified, loader, game_version) if identified else {}
    projects = client.projects([v.project_id for v in current.values()]) if current else {}

    dup_count = Counter(current[m.sha1].project_id for m in mods if m.sha1 in current)

    results: list[Resolution] = []
    for mod in mods:
        cur = current.get(mod.sha1)
        if cur is None:
            results.append(
                Resolution(mod=mod, status=NO_ENCONTRADO, current_version=mod.version, note=t("note.not_on_modrinth"))
            )
            continue

        project = projects.get(cur.project_id, {})
        res = Resolution(
            mod=mod,
            status=AL_DIA,
            source=MR,
            project_id=cur.project_id,
            project_name=project.get("title"),
            project_url=f"https://modrinth.com/mod/{project.get('slug') or cur.project_id}",
            slug=project.get("slug"),
            icon_url=project.get("icon_url"),
            current_version=cur.version_number or mod.version,
            current_channel=cur.version_type,
            current_date=cur.date_published,
            current_deps=mr_deps(cur),
            known_ids={(MR, cur.project_id)},
        )
        if dup_count[cur.project_id] > 1:
            res.duplicate = True
            res.add_note(t("note.duplicate"))

        cand = latest.get(mod.sha1)
        candidates: list[MrVersion] = [cand] if cand else []
        if cand and not is_allowed(cand, cur.version_type, allow_beta):
            # La última es de un canal no permitido: buscar en el historial.
            candidates = client.project_versions(cur.project_id, loader, game_version)
        if not candidates:
            res.add_note(t("note.no_versions", game_version=game_version, loader=loader))

        new = choose_update(cur, candidates, allow_beta)
        if new is None and (pre := newer_prerelease(cur, candidates)) is not None:
            res.newer_prerelease = pre.version_number
        if new is not None:
            f = new.primary_file
            res.new_version = new.version_number
            res.new_channel = new.version_type
            res.new_deps = mr_deps(new)
            if f and f.url:
                res.status = ACTUALIZABLE
                res.new_file_name = f.filename
                res.download_url = f.url
                res.new_sha1 = f.sha1
                res.new_sha512 = f.sha512
            else:
                res.status = DESCARGA_MANUAL
                res.add_note(t("note.no_file"))
        results.append(res)
    return results


# --------------------------------------------------------------------------- CurseForge

def cf_project_url(info: dict, mod_id: int | str) -> str:
    return (info.get("links") or {}).get("websiteUrl") or (
        f"https://www.curseforge.com/minecraft/mc-mods/{info.get('slug', mod_id)}"
    )


def resolve_with_curseforge(
    mods: list[ModFile],
    client: CurseForgeClient,
    *,
    loader: str,
    game_version: str,
    allow_beta: bool = False,
) -> list[Resolution]:
    matches = client.match_fingerprints([m.cf_fingerprint for m in mods])
    cf_mods = client.mods([mt.mod_id for mt in matches.values()]) if matches else {}

    # Candidatos: los "últimos archivos" por canal del índice del mod (una sola
    # petición en lote). Si un mod no tiene índice para versión+loader, se
    # consulta su lista de archivos.
    index_ids: dict[int, list[int]] = {
        mod_id: latest_file_ids(info, game_version, loader) for mod_id, info in cf_mods.items()
    }
    files_by_id = client.files([fid for ids in index_ids.values() for fid in ids])
    candidates_by_mod: dict[int, list[CfFile]] = {
        mod_id: [files_by_id[str(fid)] for fid in ids if str(fid) in files_by_id]
        for mod_id, ids in index_ids.items()
    }

    dup_count = Counter(matches[m.cf_fingerprint].mod_id for m in mods if m.cf_fingerprint in matches)

    results: list[Resolution] = []
    for mod in mods:
        match = matches.get(mod.cf_fingerprint)
        if match is None:
            results.append(
                Resolution(mod=mod, status=NO_ENCONTRADO, current_version=mod.version, note=t("note.not_on_curseforge"))
            )
            continue

        info = cf_mods.get(match.mod_id, {})
        cur = match.file
        res = Resolution(
            mod=mod,
            status=AL_DIA,
            source=CF,
            project_id=str(match.mod_id),
            project_name=info.get("name"),
            project_url=cf_project_url(info, match.mod_id),
            slug=info.get("slug"),
            icon_url=(info.get("logo") or {}).get("thumbnailUrl"),
            current_version=mod.version or cur.display_name,
            current_channel=cur.version_type,
            current_date=cur.date_published,
            current_deps=cf_deps(cur),
            known_ids={(CF, str(match.mod_id))},
        )
        if dup_count[match.mod_id] > 1:
            res.duplicate = True
            res.add_note(t("note.duplicate"))

        candidates = candidates_by_mod.get(match.mod_id)
        if not candidates:
            candidates = client.mod_files(match.mod_id, game_version, loader)
        if not candidates:
            res.add_note(t("note.no_versions", game_version=game_version, loader=loader))

        new = choose_update(cur, candidates, allow_beta)
        if new is None and (pre := newer_prerelease(cur, candidates)) is not None:
            res.newer_prerelease = guess_version(mod.file_name, mod.version, pre.file_name) or pre.display_name
        if new is not None:
            res.new_version = guess_version(mod.file_name, mod.version, new.file_name) or new.display_name
            res.new_channel = new.version_type
            res.new_file_name = new.file_name
            res.new_sha1 = new.sha1
            res.new_deps = cf_deps(new)
            if new.download_url:
                res.status = ACTUALIZABLE
                res.download_url = new.download_url
            else:
                res.status = DESCARGA_MANUAL
                res.add_note(t("note.no_api_download"))
        results.append(res)
    return results


# --------------------------------------------------------------------------- combinación

def resolve_all(
    mods: list[ModFile],
    *,
    curseforge: CurseForgeClient | None,
    modrinth: ModrinthClient,
    loader: str,
    game_version: str,
    allow_beta: bool = False,
    on_phase=None,
) -> list[Resolution]:
    """CurseForge como fuente principal y Modrinth como respaldo.

    Se usa Modrinth para los mods que CurseForge no identifica y para los que
    tienen versión nueva pero no se pueden descargar por API. Además se anotan
    en cada resultado los IDs del mod en ambas fuentes (`known_ids`), que
    `deps.py` usa para saber qué dependencias ya están instaladas.
    """
    opts = dict(loader=loader, game_version=game_version, allow_beta=allow_beta)
    phase = on_phase or (lambda text: None)
    if curseforge is None:
        phase("mr")
        return resolve_with_modrinth(mods, modrinth, **opts)

    phase("cf")
    cf_results = resolve_with_curseforge(mods, curseforge, **opts)
    phase("mr")
    need_mr = [r.mod for r in cf_results if r.status in (NO_ENCONTRADO, DESCARGA_MANUAL)]
    mr_by_path = {r.mod.path: r for r in resolve_with_modrinth(need_mr, modrinth, **opts)} if need_mr else {}

    merged: list[Resolution] = []
    for cf in cf_results:
        mr = mr_by_path.get(cf.mod.path)
        if mr is None:
            merged.append(cf)
        elif cf.status == NO_ENCONTRADO:
            merged.append(mr)
        elif mr.status == ACTUALIZABLE:
            # CurseForge no deja descargar; Modrinth sí.
            mr.add_note(t("note.cf_blocked_use_mr"))
            mr.known_ids |= cf.known_ids
            mr.duplicate = mr.duplicate or cf.duplicate
            merged.append(mr)
        else:
            # Modrinth no ofrece la versión nueva: queda como descarga manual desde la web.
            cf.add_note(t("note.download_manually", url=cf.project_url))
            cf.known_ids |= mr.known_ids
            merged.append(cf)

    # IDs de Modrinth de los mods resueltos por CurseForge (una petición en lote).
    pending = [r for r in merged if r.source == CF and not any(s == MR for s, _ in r.known_ids)]
    if pending:
        mr_current = modrinth.versions_from_hashes([r.mod.sha1 for r in pending])
        for r in pending:
            v = mr_current.get(r.mod.sha1)
            if v:
                r.known_ids.add((MR, v.project_id))
    return merged
