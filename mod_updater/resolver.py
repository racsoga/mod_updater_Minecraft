"""Decide, para cada jar, si hay una versión nueva y de dónde sacarla.

Por ahora solo Modrinth (hito 3). CurseForge se añadirá como fuente principal
en el hito 4 y Modrinth quedará como respaldo.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Protocol, Sequence, TypeVar

from .modrinth import ModrinthClient, MrVersion
from .scanner import ModFile

AL_DIA = "al_dia"
ACTUALIZABLE = "actualizable"
DESCONOCIDO = "desconocido"
SOLO_MANUAL = "solo_manual"

CHANNEL_RANK = {"release": 1, "beta": 2, "alpha": 3}


class VersionLike(Protocol):
    id: str
    version_type: str
    date_published: str


V = TypeVar("V", bound=VersionLike)


@dataclass
class Resolution:
    mod: ModFile
    status: str
    source: str | None = None
    project_id: str | None = None
    project_name: str | None = None
    project_url: str | None = None
    current_version: str | None = None
    current_channel: str | None = None
    new_version: str | None = None
    new_channel: str | None = None
    new_file_name: str | None = None
    download_url: str | None = None
    new_sha1: str | None = None
    new_sha512: str | None = None
    note: str = ""

    @property
    def name(self) -> str:
        return self.project_name or self.mod.display_name


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
                Resolution(mod=mod, status=DESCONOCIDO, current_version=mod.version, note="no está en Modrinth")
            )
            continue

        project = projects.get(cur.project_id, {})
        res = Resolution(
            mod=mod,
            status=AL_DIA,
            source="modrinth",
            project_id=cur.project_id,
            project_name=project.get("title"),
            project_url=f"https://modrinth.com/mod/{project.get('slug') or cur.project_id}",
            current_version=cur.version_number or mod.version,
            current_channel=cur.version_type,
        )
        notes = []
        if dup_count[cur.project_id] > 1:
            notes.append("¡duplicado en la carpeta!")

        cand = latest.get(mod.sha1)
        candidates: list[MrVersion] = [cand] if cand else []
        if cand and not is_allowed(cand, cur.version_type, allow_beta):
            # La última es de un canal no permitido: buscar en el historial.
            candidates = client.project_versions(cur.project_id, loader, game_version)
        if not candidates:
            notes.append(f"sin versiones para {game_version}/{loader}")

        new = choose_update(cur, candidates, allow_beta)
        if new is not None:
            f = new.primary_file
            res.new_version = new.version_number
            res.new_channel = new.version_type
            if f and f.url:
                res.status = ACTUALIZABLE
                res.new_file_name = f.filename
                res.download_url = f.url
                res.new_sha1 = f.sha1
                res.new_sha512 = f.sha512
            else:
                res.status = SOLO_MANUAL
                notes.append("sin archivo descargable")
        res.note = "; ".join(notes)
        results.append(res)
    return results
