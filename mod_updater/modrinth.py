"""Cliente mínimo de la API de Modrinth (v2). No requiere key, sí User-Agent."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import requests

from .net import ApiError, request_with_retry

BASE_URL = "https://api.modrinth.com"
BATCH = 100


@dataclass
class MrFile:
    url: str
    filename: str
    sha1: str
    sha512: str
    size: int
    primary: bool


@dataclass
class MrVersion:
    id: str
    project_id: str
    name: str
    version_number: str
    version_type: str  # release | beta | alpha
    date_published: str  # ISO 8601, comparable como texto
    files: list[MrFile]
    dependencies: list[dict] = field(default_factory=list)
    loaders: list[str] = field(default_factory=list)
    game_versions: list[str] = field(default_factory=list)
    changelog: str = ""  # Markdown

    @property
    def primary_file(self) -> MrFile | None:
        if not self.files:
            return None
        return next((f for f in self.files if f.primary), self.files[0])

    @property
    def required_deps(self) -> list[tuple[str | None, str | None]]:
        """[(project_id, version_id)] de las dependencias requeridas."""
        return [
            (d.get("project_id"), d.get("version_id"))
            for d in self.dependencies
            if d.get("dependency_type") == "required"
        ]

    @property
    def incompatible_ids(self) -> list[str]:
        """project_id de los proyectos declarados incompatibles."""
        return [d.get("project_id") for d in self.dependencies if d.get("dependency_type") == "incompatible" and d.get("project_id")]

    @classmethod
    def from_api(cls, d: dict) -> "MrVersion":
        files = [
            MrFile(
                url=f.get("url", ""),
                filename=f.get("filename", ""),
                sha1=(f.get("hashes") or {}).get("sha1", ""),
                sha512=(f.get("hashes") or {}).get("sha512", ""),
                size=f.get("size", 0),
                primary=bool(f.get("primary")),
            )
            for f in d.get("files", [])
        ]
        return cls(
            id=d["id"],
            project_id=d["project_id"],
            name=d.get("name") or d.get("version_number", ""),
            version_number=d.get("version_number", ""),
            version_type=d.get("version_type", "release"),
            date_published=d.get("date_published", ""),
            files=files,
            dependencies=d.get("dependencies") or [],
            loaders=d.get("loaders") or [],
            game_versions=d.get("game_versions") or [],
            changelog=d.get("changelog") or "",
        )


class ModrinthClient:
    def __init__(self, user_agent: str, session: requests.Session | None = None):
        self.session = session or requests.Session()
        self.session.headers["User-Agent"] = user_agent

    def _call(self, method: str, path: str, **kwargs):
        resp = request_with_retry(self.session, method, BASE_URL + path, min_interval=0.05, **kwargs)
        if resp.status_code == 404:
            return None
        if not resp.ok:
            kind = "busy" if resp.status_code == 429 else "http"
            raise ApiError(f"Modrinth {method} {path}: HTTP {resp.status_code} {resp.text[:200]}", kind=kind, status=resp.status_code)
        return resp.json()

    # ------------------------------------------------------------------ versiones por hash

    def versions_from_hashes(self, sha1s: list[str]) -> dict[str, MrVersion]:
        """Identifica la versión actual de cada archivo. Devuelve {sha1: versión}."""
        out: dict[str, MrVersion] = {}
        for i in range(0, len(sha1s), BATCH):
            chunk = sha1s[i : i + BATCH]
            data = self._call("POST", "/v2/version_files", json={"hashes": chunk, "algorithm": "sha1"}) or {}
            out.update({h: MrVersion.from_api(v) for h, v in data.items()})
        return out

    def latest_from_hashes(
        self, sha1s: list[str], loader: str, game_version: str
    ) -> dict[str, MrVersion]:
        """Última versión compatible (cualquier canal) por hash. {sha1: versión}."""
        out: dict[str, MrVersion] = {}
        body = {"algorithm": "sha1", "loaders": [loader], "game_versions": [game_version]}
        for i in range(0, len(sha1s), BATCH):
            chunk = sha1s[i : i + BATCH]
            data = self._call("POST", "/v2/version_files/update", json={**body, "hashes": chunk}) or {}
            out.update({h: MrVersion.from_api(v) for h, v in data.items()})
        return out

    # ------------------------------------------------------------------ proyectos

    def project_versions(self, project_id: str, loader: str, game_version: str) -> list[MrVersion]:
        """Todas las versiones compatibles de un proyecto, de más nueva a más vieja."""
        params = {"loaders": json.dumps([loader]), "game_versions": json.dumps([game_version])}
        data = self._call("GET", f"/v2/project/{project_id}/version", params=params) or []
        versions = [MrVersion.from_api(v) for v in data]
        versions.sort(key=lambda v: v.date_published, reverse=True)
        return versions

    def project(self, id_or_slug: str) -> dict | None:
        return self._call("GET", f"/v2/project/{id_or_slug}")

    def version(self, version_id: str) -> MrVersion | None:
        data = self._call("GET", f"/v2/version/{version_id}")
        return MrVersion.from_api(data) if data else None

    def projects(self, project_ids: list[str]) -> dict[str, dict]:
        """{project_id: {title, slug, ...}}"""
        out: dict[str, dict] = {}
        ids = sorted(set(project_ids))
        for i in range(0, len(ids), BATCH):
            chunk = ids[i : i + BATCH]
            data = self._call("GET", "/v2/projects", params={"ids": json.dumps(chunk)}) or []
            out.update({p["id"]: p for p in data})
        return out
