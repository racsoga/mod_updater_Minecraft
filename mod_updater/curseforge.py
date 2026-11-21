"""Cliente mínimo de la API de CurseForge (v1).

La API key se envía solo en la cabecera `x-api-key` y nunca se incluye en
mensajes de error ni en logs.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import requests

from .i18n import t
from .net import ApiError, request_with_retry

BASE_URL = "https://api.curseforge.com"
MINECRAFT_GAME_ID = 432
LOADER_TYPES = {"forge": 1, "fabric": 4, "quilt": 5, "neoforge": 6}
RELEASE_TYPES = {1: "release", 2: "beta", 3: "alpha"}
HASH_SHA1 = 1
REL_REQUIRED = 3
REL_INCOMPATIBLE = 5
BATCH = 100


class CurseForgeAuthError(ApiError):
    pass


@dataclass
class CfFile:
    id: str  # str para ser comparable con Modrinth en el resolver
    mod_id: int
    display_name: str
    file_name: str
    date_published: str  # fileDate ISO 8601
    version_type: str  # release | beta | alpha
    download_url: str | None
    sha1: str | None
    fingerprint: int | None
    game_versions: list[str] = field(default_factory=list)
    dependencies: list[dict] = field(default_factory=list)

    @classmethod
    def from_api(cls, d: dict) -> "CfFile":
        sha1 = next((h["value"] for h in d.get("hashes") or [] if h.get("algo") == HASH_SHA1), None)
        return cls(
            id=str(d["id"]),
            mod_id=d["modId"],
            display_name=d.get("displayName") or d.get("fileName", ""),
            file_name=d.get("fileName", ""),
            date_published=d.get("fileDate", ""),
            version_type=RELEASE_TYPES.get(d.get("releaseType"), "alpha"),
            download_url=d.get("downloadUrl"),
            sha1=sha1,
            fingerprint=d.get("fileFingerprint"),
            game_versions=d.get("gameVersions") or [],
            dependencies=d.get("dependencies") or [],
        )

    @property
    def required_mod_ids(self) -> list[int]:
        return [dep["modId"] for dep in self.dependencies if dep.get("relationType") == REL_REQUIRED]

    @property
    def incompatible_mod_ids(self) -> list[int]:
        return [dep["modId"] for dep in self.dependencies if dep.get("relationType") == REL_INCOMPATIBLE]


@dataclass
class CfMatch:
    mod_id: int
    file: CfFile


class CurseForgeClient:
    def __init__(self, api_key: str, session: requests.Session | None = None):
        if not api_key:
            raise ValueError("Falta CF_API_KEY")
        self.session = session or requests.Session()
        self.session.headers.update({"x-api-key": api_key, "Accept": "application/json"})

    def _call(self, method: str, path: str, **kwargs):
        # Sin seguir redirecciones: requests reenviaría la cabecera x-api-key al nuevo destino.
        resp = request_with_retry(self.session, method, BASE_URL + path, min_interval=0.1, allow_redirects=False, **kwargs)
        if resp.is_redirect:
            raise ApiError(f"CurseForge {method} {path}: redirección a {resp.headers.get('Location', '?')} (no se sigue)")
        if resp.status_code in (401, 403):
            raise CurseForgeAuthError(t("cf.key_rejected", status=resp.status_code))
        if resp.status_code == 404:
            return None
        if not resp.ok:
            kind = "busy" if resp.status_code == 429 else "http"
            raise ApiError(f"CurseForge {method} {path}: HTTP {resp.status_code} {resp.text[:200]}", kind=kind, status=resp.status_code)
        return resp.json().get("data")

    def check(self) -> None:
        """Petición mínima para comprobar la key. Lanza CurseForgeAuthError si no vale."""
        if self._call("GET", f"/v1/games/{MINECRAFT_GAME_ID}") is None:
            raise ApiError(t("cf.unexpected"))

    # ------------------------------------------------------------------ identificación

    def match_fingerprints(self, fingerprints: list[int]) -> dict[int, CfMatch]:
        """{fingerprint: CfMatch} para los archivos reconocidos exactamente."""
        out: dict[int, CfMatch] = {}
        unique = sorted(set(fingerprints))
        for i in range(0, len(unique), BATCH):
            chunk = unique[i : i + BATCH]
            data = self._call("POST", f"/v1/fingerprints/{MINECRAFT_GAME_ID}", json={"fingerprints": chunk}) or {}
            for m in data.get("exactMatches") or []:
                f = CfFile.from_api(m["file"])
                if f.fingerprint is not None:
                    out[f.fingerprint] = CfMatch(mod_id=m["id"], file=f)
        return out

    # ------------------------------------------------------------------ mods y archivos

    def mods(self, mod_ids: list[int]) -> dict[int, dict]:
        out: dict[int, dict] = {}
        ids = sorted(set(mod_ids))
        for i in range(0, len(ids), BATCH):
            data = self._call("POST", "/v1/mods", json={"modIds": ids[i : i + BATCH]}) or []
            out.update({m["id"]: m for m in data})
        return out

    def file_changelog(self, mod_id: int, file_id: int) -> str:
        """Changelog (HTML) de un archivo; cadena vacía si no hay."""
        data = self._call("GET", f"/v1/mods/{mod_id}/files/{file_id}/changelog")
        return data if isinstance(data, str) else ""

    def categories(self) -> list[dict]:
        """Categorías de la clase Mods (id, slug, name, parentCategoryId, iconUrl...)."""
        return self._call("GET", "/v1/categories", params={"gameId": MINECRAFT_GAME_ID, "classId": 6}) or []

    def files(self, file_ids: list[int]) -> dict[str, CfFile]:
        out: dict[str, CfFile] = {}
        ids = sorted(set(file_ids))
        for i in range(0, len(ids), BATCH):
            data = self._call("POST", "/v1/mods/files", json={"fileIds": ids[i : i + BATCH]}) or []
            for d in data:
                f = CfFile.from_api(d)
                out[f.id] = f
        return out

    def mod_files(self, mod_id: int, game_version: str, loader: str) -> list[CfFile]:
        """Archivos compatibles de un mod, de más nuevo a más viejo."""
        params = {"gameVersion": game_version, "modLoaderType": LOADER_TYPES[loader], "pageSize": 50}
        data = self._call("GET", f"/v1/mods/{mod_id}/files", params=params) or []
        files = [CfFile.from_api(d) for d in data]
        files.sort(key=lambda f: f.date_published, reverse=True)
        return files


def latest_file_ids(mod: dict, game_version: str, loader: str) -> list[int]:
    """IDs de los últimos archivos (uno por canal) para versión+loader, según
    `latestFilesIndexes` del mod. Lista vacía si no hay índice para ese loader."""
    loader_type = LOADER_TYPES[loader]
    return [
        idx["fileId"]
        for idx in mod.get("latestFilesIndexes") or []
        if idx.get("gameVersion") == game_version and idx.get("modLoader") == loader_type
    ]
