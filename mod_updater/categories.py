"""Categorías unificadas: las de CurseForge y Modrinth traducidas a 12 propias (+ "otras").

Se traducen por *slug*, con un mapa explícito de todas las categorías actuales de las dos
fuentes. Si CurseForge añade una categoría nueva, se usa la de su padre (`parentCategoryId`);
el catálogo de categorías se descarga y se guarda en caché una semana para conocer esos padres.

Los identificadores propios son estables (se usan en el archivo `.modlist.json`); los nombres
visibles están en los archivos de idioma (`cat.<id>`).
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path


OURS: tuple[str, ...] = (
    "tecnologia", "magia", "aventura", "mundo", "mobs", "construccion",
    "almacenamiento", "comida", "mapas", "calidad_vida", "rendimiento", "librerias",
)
OTHER = "otras"
LIBRARY = "librerias"
CACHE_MAX_AGE = 7 * 24 * 3600  # una semana
KNOWLEDGE_FILE = Path(__file__).resolve().parent / "knowledge" / "categorias.json"

# CurseForge, clase Mods (classId 6). Las específicas mandan sobre su padre
# (p. ej. technology-farming es comida aunque su padre sea technology).
CF_SLUGS: dict[str, str] = {
    # Tecnología
    "technology": "tecnologia", "technology-automation": "tecnologia", "technology-energy": "tecnologia",
    "technology-genetics": "tecnologia", "technology-item-fluid-energy-transport": "tecnologia",
    "technology-processing": "tecnologia", "redstone": "tecnologia",
    "create": "tecnologia", "addons-buildcraft": "tecnologia", "addons-industrialcraft": "tecnologia",
    "addons-thermalexpansion": "tecnologia", "integrated-dynamics": "tecnologia",
    # Magia
    "magic": "magia", "addons-thaumcraft": "magia", "blood-magic": "magia",
    # Aventura y exploración
    "adventure-rpg": "aventura", "horror": "aventura", "twilight-forest": "aventura", "galacticraft": "aventura",
    "technology-player-transport": "aventura",  # ascensores, waystones, alas: moverse por el mundo
    # Mundo y biomas
    "world-gen": "mundo", "world-biomes": "mundo", "world-dimensions": "mundo", "world-ores-resources": "mundo",
    "world-structures": "mundo", "skyblock": "mundo",
    # Mobs y combate
    "world-mobs": "mobs", "armor-weapons-tools": "mobs", "addons-tinkers-construct": "mobs",
    # Construcción y decoración
    "cosmetic": "construccion", "creativemode": "construccion",
    # Almacenamiento
    "storage": "almacenamiento", "applied-energistics-2": "almacenamiento", "refined-storage": "almacenamiento",
    # Comida y granjas
    "mc-food": "comida", "technology-farming": "comida", "farmers-delight": "comida", "addons-forestry": "comida",
    # Mapas e información
    "map-information": "mapas",
    # Calidad de vida
    "utility-qol": "calidad_vida", "server-utility": "calidad_vida",
    # Rendimiento
    "performance": "rendimiento", "bug-fixes": "rendimiento",
    # Librerías
    "library-api": "librerias", "crafttweaker": "librerias", "kubejs": "librerias",
    # Otras
    "mc-addons": OTHER, "mc-miscellaneous": OTHER, "education": OTHER, "mc-creator": OTHER,
    "twitch-integration": OTHER, "modjam-2025": OTHER,
}

# Categorías de primer nivel de CurseForge por id: sirven para subir al padre de una
# categoría nueva aunque no haya catálogo descargado.
CF_TOP_IDS: dict[int, str] = {
    422: "adventure-rpg", 434: "armor-weapons-tools", 6821: "bug-fixes", 424: "cosmetic", 9026: "creativemode",
    5299: "education", 10775: "horror", 421: "library-api", 419: "magic", 423: "map-information",
    426: "mc-addons", 4906: "mc-creator", 436: "mc-food", 425: "mc-miscellaneous", 6814: "performance",
    4558: "redstone", 435: "server-utility", 420: "storage", 412: "technology", 4671: "twitch-integration",
    5191: "utility-qol", 406: "world-gen",
}

# Modrinth: solo las etiquetas de tipo "categories" (no los cargadores ni las resoluciones).
MR_SLUGS: dict[str, str] = {
    "technology": "tecnologia", "transportation": "aventura", "magic": "magia", "adventure": "aventura",
    "worldgen": "mundo", "mobs": "mobs", "equipment": "mobs", "decoration": "construccion",
    "storage": "almacenamiento", "food": "comida", "utility": "calidad_vida", "management": "calidad_vida",
    "optimization": "rendimiento", "library": "librerias",
    "game-mechanics": OTHER, "economy": OTHER, "social": OTHER, "minigame": OTHER, "cursed": OTHER,
}


@dataclass
class Catalog:
    """Jerarquía de categorías de CurseForge (id -> padre, id -> slug)."""

    cf_parent: dict[int, int] = field(default_factory=dict)
    cf_slug: dict[int, str] = field(default_factory=dict)

    @classmethod
    def from_api(cls, items: list[dict]) -> "Catalog":
        return cls(
            cf_parent={int(c["id"]): int(c.get("parentCategoryId") or 0) for c in items},
            cf_slug={int(c["id"]): str(c.get("slug") or "") for c in items},
        )

    @classmethod
    def load(cls, cache_path: Path, curseforge=None, max_age: float = CACHE_MAX_AGE,
             now: float | None = None) -> "Catalog":
        """Catálogo de la caché si tiene menos de `max_age`; si no, se descarga (necesita key).
        Sin red, se usa la caché aunque esté caducada; sin nada, un catálogo vacío (el mapa
        explícito sigue funcionando)."""
        now = time.time() if now is None else now
        cached = None
        try:
            data = json.loads(Path(cache_path).read_text(encoding="utf-8"))
            cached = (float(data["saved"]), cls.from_api(data["cf"]))
        except (OSError, ValueError, KeyError, TypeError):
            cached = None
        if cached and now - cached[0] < max_age:
            return cached[1]
        if curseforge is not None:
            try:
                items = curseforge.categories()
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                cache_path.write_text(json.dumps({"saved": now, "cf": items}), encoding="utf-8")
                return cls.from_api(items)
            except Exception:  # noqa: BLE001 - las categorías nunca deben impedir la revisión
                pass
        return cached[1] if cached else cls()


def _unique(items: list[str]) -> list[str]:
    seen: list[str] = []
    for i in items:
        if i not in seen:
            seen.append(i)
    return seen


def _other_last(cats: list[str]) -> list[str]:
    """"Otras" nunca es la principal si hay otra categoría (p. ej. un addon de Mekanism cuya
    categoría principal en CurseForge es "Addons" pero también es de Tecnología)."""
    return [c for c in cats if c != OTHER] + [c for c in cats if c == OTHER]


def _cf_one(cat: dict, catalog: Catalog | None) -> str:
    slug = cat.get("slug") or ""
    if slug in CF_SLUGS:
        return CF_SLUGS[slug]
    # Categoría nueva: subir por la jerarquía (máximo unos pocos niveles).
    parent = cat.get("parentCategoryId")
    for _ in range(4):
        if not parent:
            break
        parent_slug = (catalog.cf_slug.get(parent) if catalog else None) or CF_TOP_IDS.get(parent)
        if parent_slug in CF_SLUGS:
            return CF_SLUGS[parent_slug]
        parent = catalog.cf_parent.get(parent) if catalog else None
    return OTHER


@lru_cache(maxsize=1)
def overrides() -> dict[str, dict[str, str]]:
    """Tabla de correcciones (`knowledge/categorias.json`): {fuente: {id de proyecto: categoría}}.
    Para los mods que ninguna regla clasifica bien (p. ej. Supplementaries)."""
    try:
        data = json.loads(KNOWLEDGE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {src: {str(pid): entry["categoria"] for pid, entry in (data.get(src) or {}).items()
                  if isinstance(entry, dict) and entry.get("categoria") in OURS}
            for src in ("curseforge", "modrinth")}


def _with_override(cats: list[str], source: str, project_id) -> list[str]:
    fixed = overrides().get(source, {}).get(str(project_id)) if project_id is not None else None
    if not fixed:
        return cats
    return [fixed] + [c for c in cats if c != fixed]


def _is_subcategory(cat: dict) -> bool:
    """Las subcategorías de CurseForge (p. ej. technology-farming) son más específicas que las de
    primer nivel, cuyo padre es la propia clase Mods (6)."""
    parent = cat.get("parentCategoryId")
    return bool(parent) and parent not in (6, cat.get("classId"))


def from_curseforge(info: dict, catalog: Catalog | None = None) -> list[str]:
    """Categorías propias de un mod de CurseForge, la principal primero.

    `primaryCategoryId` no se usa a ciegas cuando es genérica (Tecnología u Otras): entonces gana la
    categoría más específica (una subcategoría gana a una de primer nivel y, entre subcategorías,
    cualquier otra gana a Tecnología: un addon de Create para granjas es de Comida). Si la principal
    ya es concreta (p. ej. Almacenamiento), se respeta. "Otras" nunca es la principal si hay otra. La tabla de correcciones manda.
    """
    raw = [c for c in (info.get("categories") or []) if isinstance(c, dict)]
    primary_id = info.get("primaryCategoryId")
    scored = [(_cf_one(c, catalog), _is_subcategory(c), c.get("id") == primary_id, -i) for i, c in enumerate(raw)]
    all_cats = _unique([s[0] for s in scored])
    primary = next((s[0] for s in scored if s[2]), None)
    if primary == LIBRARY or (primary == OTHER and LIBRARY in all_cats):
        # Librería (también si la principal es "miscelánea" y está marcada como librería: Bookshelf).
        best = LIBRARY
    else:
        content = [s for s in scored if s[0] not in (OTHER, LIBRARY)]
        if primary not in (None, OTHER, "tecnologia"):
            content = [s for s in content if s[2]]  # la principal ya es concreta (p. ej. Almacenamiento): se respeta
        # (subcategoría, subcategoría que no es Tecnología, principal de CurseForge, orden)
        best = max(content, key=lambda s: (s[1], s[1] and s[0] != "tecnologia", s[2], s[3]))[0] if content else (
            LIBRARY if LIBRARY in all_cats else (OTHER if all_cats else None))
    cats = ([best] if best else []) + [c for c in all_cats if c != best]
    return _with_override(_other_last(cats), "curseforge", info.get("id"))


def from_modrinth(project: dict) -> list[str]:
    """Categorías propias de un proyecto de Modrinth. La principal es la primera que no
    sea "otras" (Modrinth no marca ninguna como principal); la tabla de correcciones manda."""
    slugs = list(project.get("categories") or []) + list(project.get("additional_categories") or [])
    cats = _other_last(_unique([MR_SLUGS[s] for s in slugs if s in MR_SLUGS]))
    return _with_override(cats, "modrinth", project.get("id"))


def is_library(cats: list[str]) -> bool:
    """Librería = su categoría principal es "librerias" (JEI lleva la etiqueta de librería en
    CurseForge, pero su categoría principal es otra y no se debe ocultar con las librerías)."""
    return cats[:1] == [LIBRARY]
