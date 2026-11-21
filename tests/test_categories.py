"""Categorías unificadas: mapa de CurseForge y Modrinth a las 12 propias, catálogo con caché."""

import json
import time

import pytest

from mod_updater import categories as cats
from mod_updater.categories import (
    LIBRARY,
    OTHER,
    OURS,
    Catalog,
    from_curseforge,
    from_modrinth,
    is_library,
)
from mod_updater.net import ApiError

# Listas reales (noviembre de 2026): CurseForge GET /v1/categories?gameId=432&classId=6 y
# Modrinth GET /v2/tag/category (header "categories", project_type "mod").
CF_TOP = {
    422: "adventure-rpg", 434: "armor-weapons-tools", 6821: "bug-fixes", 424: "cosmetic", 9026: "creativemode",
    5299: "education", 10775: "horror", 421: "library-api", 419: "magic", 423: "map-information",
    426: "mc-addons", 4906: "mc-creator", 436: "mc-food", 425: "mc-miscellaneous", 8937: "modjam-2025",
    6814: "performance", 4558: "redstone", 435: "server-utility", 420: "storage", 412: "technology",
    4671: "twitch-integration", 5191: "utility-qol", 406: "world-gen",
}
CF_CHILDREN = {  # id: (slug, padre)
    432: ("addons-buildcraft", 426), 433: ("addons-forestry", 426), 429: ("addons-industrialcraft", 426),
    430: ("addons-thaumcraft", 426), 427: ("addons-thermalexpansion", 426), 428: ("addons-tinkers-construct", 426),
    4545: ("applied-energistics-2", 426), 4485: ("blood-magic", 426), 4773: ("crafttweaker", 426),
    6484: ("create", 426), 10754: ("farmers-delight", 426), 5232: ("galacticraft", 426),
    6954: ("integrated-dynamics", 426), 5314: ("kubejs", 426), 9049: ("refined-storage", 426),
    6145: ("skyblock", 426), 7669: ("twilight-forest", 426),
    4843: ("technology-automation", 412), 417: ("technology-energy", 412), 416: ("technology-farming", 412),
    418: ("technology-genetics", 412), 415: ("technology-item-fluid-energy-transport", 412),
    414: ("technology-player-transport", 412), 413: ("technology-processing", 412),
    407: ("world-biomes", 406), 410: ("world-dimensions", 406), 411: ("world-mobs", 406),
    408: ("world-ores-resources", 406), 409: ("world-structures", 406),
}
MR_TAGS = ["adventure", "cursed", "decoration", "economy", "equipment", "food", "game-mechanics", "library",
           "magic", "management", "minigame", "mobs", "optimization", "social", "storage", "technology",
           "transportation", "utility", "worldgen"]


def cf_api_list():
    out = [{"id": i, "slug": s, "parentCategoryId": 6, "classId": 6} for i, s in CF_TOP.items()]
    out += [{"id": i, "slug": s, "parentCategoryId": p, "classId": 6} for i, (s, p) in CF_CHILDREN.items()]
    return out


def cf_info(*ids, primary=None):
    every = {**CF_TOP, **{i: s for i, (s, _) in CF_CHILDREN.items()}}
    parents = {i: p for i, (_, p) in CF_CHILDREN.items()}
    return {"categories": [{"id": i, "slug": every.get(i, f"nueva-{i}"), "parentCategoryId": parents.get(i, 6)}
                           for i in ids], "primaryCategoryId": primary or (ids[0] if ids else None)}


# --------------------------------------------------------------------------- el mapa


def test_twelve_categories_plus_other():
    assert len(OURS) == 12 and OTHER not in OURS and LIBRARY in OURS


def test_every_real_curseforge_category_is_mapped():
    every = {**CF_TOP, **{i: s for i, (s, _) in CF_CHILDREN.items()}}
    for slug in every.values():
        assert slug in cats.CF_SLUGS, f"falta {slug} en CF_SLUGS"
        assert cats.CF_SLUGS[slug] in OURS + (OTHER,)


def test_every_real_modrinth_category_is_mapped():
    for slug in MR_TAGS:
        assert slug in cats.MR_SLUGS, f"falta {slug} en MR_SLUGS"
        assert cats.MR_SLUGS[slug] in OURS + (OTHER,)


@pytest.mark.parametrize("slug,expected", [
    ("technology", "tecnologia"), ("technology-farming", "comida"), ("create", "tecnologia"),
    ("magic", "magia"), ("world-biomes", "mundo"), ("world-mobs", "mobs"), ("storage", "almacenamiento"),
    ("applied-energistics-2", "almacenamiento"), ("map-information", "mapas"), ("utility-qol", "calidad_vida"),
    ("performance", "rendimiento"), ("library-api", "librerias"), ("mc-food", "comida"),
    ("cosmetic", "construccion"), ("mc-miscellaneous", "otras"),
])
def test_curseforge_examples(slug, expected):
    assert cats.CF_SLUGS[slug] == expected


# --------------------------------------------------------------------------- CurseForge


def test_curseforge_primary_first_without_repeats():
    # Create (tecnología) con categorías: almacenamiento, technology (primaria), technology-processing
    assert from_curseforge(cf_info(420, 412, 413, primary=412)) == ["tecnologia", "almacenamiento"]


def test_curseforge_unknown_child_uses_catalog_parent():
    catalog = Catalog(cf_parent={99999: 412}, cf_slug={412: "technology", 99999: "tecnologia-futura"})
    info = {"categories": [{"id": 99999, "slug": "tecnologia-futura", "parentCategoryId": 412}],
            "primaryCategoryId": 99999}
    assert from_curseforge(info, catalog) == ["tecnologia"]


def test_curseforge_unknown_child_uses_its_own_parent_id_without_catalog():
    info = {"categories": [{"id": 99999, "slug": "magia-nueva", "parentCategoryId": 419}], "primaryCategoryId": 99999}
    assert from_curseforge(info) == ["magia"]


def test_curseforge_unknown_without_parent_is_other():
    info = {"categories": [{"id": 77777, "slug": "rarisima", "parentCategoryId": 6}], "primaryCategoryId": 77777}
    assert from_curseforge(info) == [OTHER]


def test_curseforge_without_categories():
    assert from_curseforge({}) == []
    assert from_curseforge({"categories": None}) == []


# --------------------------------------------------------------------------- Modrinth


def test_modrinth_ignores_loaders_and_first_mapped_is_primary():
    project = {"categories": ["neoforge", "fabric", "social", "technology"], "additional_categories": ["storage"]}
    assert from_modrinth(project) == ["tecnologia", "almacenamiento", "otras"]


def test_modrinth_only_other():
    assert from_modrinth({"categories": ["cursed"]}) == [OTHER]


def test_modrinth_without_categories():
    assert from_modrinth({}) == []


def test_is_library():
    assert is_library(["librerias"]) and is_library(["librerias", "tecnologia"])
    assert not is_library(["mapas", "librerias"])  # JEI: etiqueta de librería, pero principal "mapas"
    assert not is_library(["tecnologia"]) and not is_library([])


def test_misc_primary_with_library_tag_is_library():
    # Bookshelf: principal mc-miscellaneous, también utility-qol y library-api
    assert from_curseforge(cf_info(425, 5191, 421, primary=425)) == ["librerias", "calidad_vida", "otras"]


# --------------------------------------------------------------------------- catálogo y caché


class FakeCf:
    def __init__(self, fail=False):
        self.calls, self.fail = 0, fail

    def categories(self):
        self.calls += 1
        if self.fail:
            raise ApiError("sin red", kind="offline")
        return cf_api_list()


def test_catalog_downloads_and_caches(tmp_path):
    path = tmp_path / "categories.json"
    cf = FakeCf()
    c = Catalog.load(path, curseforge=cf)
    assert cf.calls == 1 and c.cf_parent[416] == 412 and c.cf_slug[412] == "technology"
    again = Catalog.load(path, curseforge=cf)
    assert cf.calls == 1 and again.cf_parent == c.cf_parent  # caché válida: sin red


def test_catalog_expired_cache_is_refreshed(tmp_path):
    path = tmp_path / "categories.json"
    Catalog.load(path, curseforge=FakeCf())
    cf = FakeCf()
    Catalog.load(path, curseforge=cf, now=time.time() + 8 * 24 * 3600)
    assert cf.calls == 1


def test_catalog_offline_uses_expired_cache(tmp_path):
    path = tmp_path / "categories.json"
    Catalog.load(path, curseforge=FakeCf())
    c = Catalog.load(path, curseforge=FakeCf(fail=True), now=time.time() + 30 * 24 * 3600)
    assert c.cf_parent[416] == 412


def test_catalog_offline_without_cache_is_empty(tmp_path):
    c = Catalog.load(tmp_path / "categories.json", curseforge=FakeCf(fail=True))
    assert c.cf_parent == {} and from_curseforge(cf_info(412), c) == ["tecnologia"]


def test_catalog_corrupt_cache_is_ignored(tmp_path):
    path = tmp_path / "categories.json"
    path.write_text("{no es json", encoding="utf-8")
    cf = FakeCf()
    c = Catalog.load(path, curseforge=cf)
    assert cf.calls == 1 and c.cf_parent[416] == 412
    assert json.loads(path.read_text(encoding="utf-8"))["cf"]


def test_catalog_without_key_uses_cache_only(tmp_path):
    path = tmp_path / "categories.json"
    Catalog.load(path, curseforge=FakeCf())
    assert Catalog.load(path, curseforge=None, now=time.time() + 30 * 24 * 3600).cf_parent[416] == 412


# --------------------------------------------------------------------------- integración


def test_resolve_all_sets_categories_from_both_sources():
    from mod_updater.curseforge import CfMatch
    from test_resolver import FakeCf as ResolverCf, FakeClient, cf_file, cf_mod, ver

    class CfWithCats(ResolverCf):
        def mods(self, ids):
            out = super().mods(ids)
            for i in out:
                out[i] |= {"categories": [{"id": 421, "slug": "library-api", "parentCategoryId": 6}],
                           "primaryCategoryId": 421}
            return out

    class MrWithCats(FakeClient):
        def projects(self, ids):
            return {i: {"id": i, "title": i.upper(), "slug": i, "categories": ["fabric", "magic"]} for i in ids}

    cf = CfWithCats(matches={100: CfMatch(1, cf_file(10, 1, "release", "2024-01-01"))}, index={}, files={})
    mr = MrWithCats(current={"h2": ver("1.0", "p2", "release", "2024-01-01")}, latest={})
    from mod_updater.resolver import resolve_all
    res = {r.mod.file_name: r for r in resolve_all(
        [cf_mod("a.jar", "h1", 100), cf_mod("b.jar", "h2", 200), cf_mod("c.jar", "h3", 300)],
        curseforge=cf, modrinth=mr, loader="neoforge", game_version="1.21.1")}
    assert res["a.jar"].categories == ["librerias"] and res["a.jar"].is_library
    assert res["b.jar"].categories == ["magia"] and not res["b.jar"].is_library
    assert res["c.jar"].categories == []  # no encontrado: sin categorías, sin error


def test_serialized_row_has_category():
    from mod_updater.deps import DepPlan
    from mod_updater.gui.api import serialize
    from mod_updater.resolver import AL_DIA, NO_ENCONTRADO, Resolution
    from test_gui_api import _mod
    rows = serialize([Resolution(mod=_mod("a"), status=AL_DIA, categories=["tecnologia", "librerias"]),
                      Resolution(mod=_mod("b"), status=NO_ENCONTRADO)], DepPlan(items=[]))["rows"]
    assert (rows[0]["cat"], rows[0]["cats"], rows[0]["lib"]) == ("tecnologia", ["tecnologia", "librerias"], False)
    assert (rows[1]["cat"], rows[1]["lib"]) == (None, False)


def test_curseforge_primary_other_yields_to_real_category():
    # Addon de Mekanism: principal "mc-addons" (otras) y también "technology"
    assert from_curseforge(cf_info(426, 412, primary=426)) == ["tecnologia", "otras"]


def test_every_category_has_a_name_in_both_languages():
    from mod_updater import i18n
    for code in i18n.SUPPORTED:
        table = i18n._load(code)
        for c in OURS + (OTHER,):
            assert table.get(f"cat.{c}") and table.get(f"cat_short.{c}"), f"{code}: falta cat(_short).{c}"


# --------------------------------------------------------------------------- prioridad y correcciones


def test_specific_subcategory_beats_generic_primary():
    # Waystones: principal technology-player-transport (subcategoría) -> aventura (transporte)
    assert from_curseforge(cf_info(414, 422, 419, 435, primary=414))[0] == "aventura"
    # Integrated Farming: principal "create" (addon -> tecnología) y technology-farming -> comida
    assert from_curseforge(cf_info(6484, 426, 412, 4843, 416, primary=6484))[0] == "comida"


def test_technology_stays_when_nothing_more_specific():
    # Create: technology + redstone + cosmetic + armas, todas de primer nivel
    assert from_curseforge(cf_info(4558, 424, 412, 434, primary=412))[0] == "tecnologia"
    # Mekanism: sus subcategorías también son de tecnología
    assert from_curseforge(cf_info(434, 412, 420, 415, 413, primary=412))[0] == "tecnologia"


def test_overrides_from_knowledge_base():
    from mod_updater.categories import overrides
    table = overrides()
    assert table["curseforge"]["412082"] == "construccion"  # Supplementaries
    assert table["curseforge"]["820977"] == "comida"  # Create: Central Kitchen
    info = cf_info(425, 4558, 424, 420, primary=425) | {"id": 412082}
    assert from_curseforge(info)[0] == "construccion"
    # La corrección puede asignar una categoría que el mod no tenía en CurseForge
    assert from_curseforge({"id": 254284, **cf_info(425)}) [0] == "calidad_vida"  # AmbientSounds


def test_override_table_only_uses_valid_categories():
    from mod_updater.categories import overrides
    for source, table in overrides().items():
        for pid, cat in table.items():
            assert cat in OURS, f"{source} {pid}: {cat}"


def test_modrinth_override():
    from mod_updater.categories import overrides
    table = overrides()
    if table.get("modrinth"):
        pid, cat = next(iter(table["modrinth"].items()))
        assert from_modrinth({"id": pid, "categories": ["cursed"]})[0] == cat
