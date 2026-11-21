"""Explorar: buscar mods en CurseForge y Modrinth para la versión y el cargador del perfil.

- Siempre se filtra por versión de Minecraft y cargador (en la propia API).
- Un mod que está en las dos fuentes aparece una vez; se prefiere CurseForge si hay key
  (igual que en las actualizaciones). La tarjeta indica en qué otra fuente está.
- La descripción del detalle pasa por la misma limpieza que los changelogs.
"""

from __future__ import annotations

from .categories import CF_SLUGS, CF_TOP_IDS, MR_SLUGS, OTHER, from_curseforge, from_modrinth
from .changelog import markdown_to_html, sanitize_html, _safe_url
from .deps import name_key
from .resolver import CF, MR, Resolution, cf_project_url

PAGE_SIZE = 20
# Orden: (campo de CurseForge, índice de Modrinth). CurseForge: 2 popularidad, 3 actualizado,
# 4 nombre, 6 descargas. Modrinth: relevance, downloads, updated (sin orden por nombre).
SORTS = {
    "popular": (2, "relevance"),
    "downloads": (6, "downloads"),
    "updated": (3, "updated"),
    "name": (4, "relevance"),
}


def _cf_category_ids(category: str) -> list[int]:
    """ids de CurseForge que caen en una categoría propia (primero las de primer nivel)."""
    slugs = {s for s, c in CF_SLUGS.items() if c == category}
    return [i for i, s in CF_TOP_IDS.items() if s in slugs]


def _mr_categories(category: str) -> list[str]:
    return [s for s, c in MR_SLUGS.items() if c == category]


def _cf_card(m: dict) -> dict:
    cats = from_curseforge(m)
    return {
        "source": CF, "id": str(m["id"]), "slug": m.get("slug"), "name": m.get("name") or "?",
        "author": ((m.get("authors") or [{}])[0] or {}).get("name") or "",
        "summary": m.get("summary") or "", "downloads": int(m.get("downloadCount") or 0),
        "updated": m.get("dateReleased") or m.get("dateModified"),
        "icon": _safe_url(((m.get("logo") or {}).get("thumbnailUrl")), image=True),
        "cats": cats, "cat": cats[0] if cats else OTHER,
        "url": cf_project_url(m, m["id"]),
        "manual": m.get("allowModDistribution") is False,  # el autor no permite descargas desde otras apps
        "also_on": [],
    }


def _mr_card(h: dict) -> dict:
    cats = from_modrinth({"id": h.get("project_id"), "title": h.get("title"), "categories": h.get("categories") or []})
    return {
        "source": MR, "id": h["project_id"], "slug": h.get("slug"), "name": h.get("title") or "?",
        "author": h.get("author") or "", "summary": h.get("description") or "",
        "downloads": int(h.get("downloads") or 0), "updated": h.get("date_modified"),
        "icon": _safe_url(h.get("icon_url"), image=True), "cats": cats, "cat": cats[0] if cats else OTHER,
        "url": f"https://modrinth.com/mod/{h.get('slug') or h['project_id']}", "manual": False, "also_on": [],
    }


def _keys(card: dict) -> set[str]:
    return {k for k in (name_key(card["name"]), name_key(card.get("slug"))) if k}


def _same_mod(a: dict, b: dict) -> bool:
    """¿Es el mismo mod en las dos fuentes? Mismo slug, o mismo nombre y mismo autor. Dos mods
    distintos pueden llamarse igual, así que el nombre solo no basta."""
    if a["source"] == b["source"]:
        return a["id"] == b["id"]
    slug_a, slug_b = name_key(a.get("slug")), name_key(b.get("slug"))
    if slug_a and slug_a == slug_b:
        return True
    return name_key(a["name"]) == name_key(b["name"]) and bool(name_key(a["author"])) \
        and name_key(a["author"]) == name_key(b["author"])


def _installed_index(installed: list[Resolution]) -> tuple[set[tuple[str, str]], set[str]]:
    ids: set[tuple[str, str]] = set()
    names: set[str] = set()
    for r in installed:
        ids |= r.known_ids
        names |= {k for k in (name_key(r.name), name_key(r.slug)) if k}
    return ids, names


def search(curseforge, modrinth, *, query: str, category: str | None, sort: str, page: int,
           installed: list[Resolution], game_version: str, loader: str, hide_installed: bool = False) -> list[dict]:
    cf_sort, mr_index = SORTS.get(sort, SORTS["popular"])
    cf_cards: list[dict] = []
    if curseforge is not None:
        found = curseforge.search(query=query, game_version=game_version, loader=loader, sort_field=cf_sort,
                                  index=page * PAGE_SIZE, page_size=PAGE_SIZE,
                                  category_ids=_cf_category_ids(category) if category else None)
        cf_cards = [_cf_card(m) for m in found]
    mr_cards: list[dict] = []
    if modrinth is not None:
        hits = modrinth.search(query=query, game_version=game_version, loader=loader, index=mr_index,
                               offset=page * PAGE_SIZE, limit=PAGE_SIZE,
                               categories=_mr_categories(category) if category else None)
        mr_cards = [_mr_card(h) for h in hits]

    # Fusión sin duplicados: CurseForge primero (fuente principal); de Modrinth solo lo que no esté ya.
    merged: list[dict] = []
    for card in cf_cards + mr_cards:
        twin = next((m for m in merged if _same_mod(m, card)), None)
        if twin is not None:
            if card["source"] not in twin["also_on"] and card["source"] != twin["source"]:
                twin["also_on"].append(card["source"])
            continue
        merged.append(card)

    if category:  # la API filtra por sus categorías; aquí, por la principal propia
        merged = [c for c in merged if category in c["cats"]]

    ids, names = _installed_index(installed)
    for c in merged:
        c["installed"] = (c["source"], c["id"]) in ids or bool(_keys(c) & names)
    if hide_installed:
        merged = [c for c in merged if not c["installed"]]

    if sort == "downloads":
        merged.sort(key=lambda c: -c["downloads"])
    elif sort == "updated":
        merged.sort(key=lambda c: c["updated"] or "", reverse=True)
    elif sort == "name":
        merged.sort(key=lambda c: c["name"].lower())
    return merged


def detail(curseforge, modrinth, *, source: str, project_id: str) -> dict:
    """Descripción (limpia), capturas y enlaces de un mod."""
    if source == CF and curseforge is not None:
        info = curseforge.mods([int(project_id)]).get(int(project_id)) or {}
        links = info.get("links") or {}
        return {
            "html": sanitize_html(curseforge.description(int(project_id)), flag=False),
            "images": [u for u in (_safe_url(s.get("url"), image=True) for s in info.get("screenshots") or []) if u][:8],
            "links": {"page": cf_project_url(info, project_id) if info else None,
                      "source": _safe_url(links.get("sourceUrl")), "issues": _safe_url(links.get("issuesUrl")),
                      "wiki": _safe_url(links.get("wikiUrl"))},
        }
    if source == MR and modrinth is not None:
        p = modrinth.project(project_id) or {}
        return {
            "html": markdown_to_html(p.get("body"), flag=False),
            "images": [u for u in (_safe_url(g.get("url"), image=True) for g in p.get("gallery") or []) if u][:8],
            "links": {"page": f"https://modrinth.com/mod/{p.get('slug') or project_id}",
                      "source": _safe_url(p.get("source_url")), "issues": _safe_url(p.get("issues_url")),
                      "wiki": _safe_url(p.get("wiki_url"))},
        }
    return {"html": "", "images": [], "links": {}}
