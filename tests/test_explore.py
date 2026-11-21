"""Explorar: búsqueda combinada en CurseForge y Modrinth, detalle e instalación desde la cesta."""

from pathlib import Path

from mod_updater.changelog import sanitize_html
from mod_updater.explore import detail, search
from mod_updater.resolver import AL_DIA, CF, MR, Resolution
from mod_updater.scanner import ModFile


def cf_mod(mid, name, slug, downloads=1000, updated="2026-10-01T00:00:00Z", cats=((412, "technology"),),
           allow=True, author="Autor"):
    return {"id": mid, "name": name, "slug": slug, "summary": f"Resumen de {name}", "downloadCount": downloads,
            "dateReleased": updated, "logo": {"thumbnailUrl": f"https://media.forgecdn.net/{mid}.png"},
            "authors": [{"name": author}], "allowModDistribution": allow,
            "categories": [{"id": i, "slug": s, "parentCategoryId": 6} for i, s in cats],
            "primaryCategoryId": cats[0][0] if cats else None,
            "links": {"websiteUrl": f"https://www.curseforge.com/minecraft/mc-mods/{slug}"}}


def mr_hit(pid, title, slug, downloads=500, cats=("technology",)):
    return {"project_id": pid, "slug": slug, "title": title, "author": "Otro", "description": f"Desc {title}",
            "downloads": downloads, "date_modified": "2026-09-01T00:00:00Z",
            "icon_url": f"https://cdn.modrinth.com/{pid}.png", "categories": ["neoforge", *cats]}


class Cf:
    def __init__(self, mods):
        self.mods_, self.calls = mods, []

    def search(self, **kw):
        self.calls.append(kw)
        return self.mods_

    def mods(self, ids):
        return {m["id"]: m for m in self.mods_ if m["id"] in ids}

    def description(self, mid):
        return '<p>Hola</p><script>alert(1)</script><img src="https://media.forgecdn.net/s.png">'


class Mr:
    def __init__(self, hits):
        self.hits, self.calls = hits, []

    def search(self, **kw):
        self.calls.append(kw)
        return self.hits

    def project(self, pid):
        h = next((h for h in self.hits if h["project_id"] == pid), None)
        return h and {"id": pid, "title": h["title"], "slug": h["slug"], "body": "## Uso\n<iframe></iframe>",
                      "gallery": [{"url": "https://cdn.modrinth.com/g.png"}], "source_url": "https://github.com/x"}


def installed(name, source=CF, pid="1"):
    mod = ModFile(path=Path(f"{name}.jar"), file_name=f"{name}.jar", size=1, sha1="", sha512="", cf_fingerprint=0)
    return Resolution(mod=mod, status=AL_DIA, source=source, project_id=pid, project_name=name,
                      known_ids={(source, pid)})


OPTS = dict(game_version="1.21.1", loader="neoforge")


def test_filters_by_version_and_loader_in_both_sources():
    cf, mr = Cf([]), Mr([])
    search(cf, mr, query="create", category=None, sort="popular", page=0, installed=[], **OPTS)
    assert cf.calls[0]["game_version"] == "1.21.1" and cf.calls[0]["loader"] == "neoforge"
    assert cf.calls[0]["query"] == "create"
    assert mr.calls[0]["game_version"] == "1.21.1" and mr.calls[0]["loader"] == "neoforge"


def test_same_mod_in_both_sources_appears_once_preferring_curseforge():
    cf = Cf([cf_mod(328085, "Create", "create", downloads=9_000_000)])
    mr = Mr([mr_hit("LNytGWDc", "Create", "create", downloads=4_000_000), mr_hit("AANobbMI", "Sodium", "sodium")])
    cards = search(cf, mr, query="", category=None, sort="downloads", page=0, installed=[], **OPTS)
    assert [c["name"] for c in cards] == ["Create", "Sodium"]
    create = cards[0]
    assert create["source"] == CF and create["id"] == "328085" and create["also_on"] == [MR]


def test_without_curseforge_key_uses_modrinth():
    cards = search(None, Mr([mr_hit("AANobbMI", "Sodium", "sodium")]), query="", category=None, sort="popular",
                   page=0, installed=[], **OPTS)
    assert [(c["source"], c["id"]) for c in cards] == [(MR, "AANobbMI")]


def test_installed_badge_and_hide_installed():
    cf = Cf([cf_mod(1, "Create", "create"), cf_mod(2, "Waystones", "waystones")])
    inst = [installed("Create", CF, "1")]
    cards = search(cf, Mr([]), query="", category=None, sort="popular", page=0, installed=inst, **OPTS)
    assert {c["name"]: c["installed"] for c in cards} == {"Create": True, "Waystones": False}
    cards = search(cf, Mr([]), query="", category=None, sort="popular", page=0, installed=inst, hide_installed=True, **OPTS)
    assert [c["name"] for c in cards] == ["Waystones"]


def test_category_filter_and_own_categories():
    cf = Cf([cf_mod(1, "Create", "create"), cf_mod(2, "Farmer's Delight", "farmers-delight", cats=((436, "mc-food"),))])
    cards = search(cf, Mr([]), query="", category="comida", sort="popular", page=0, installed=[], **OPTS)
    assert [c["name"] for c in cards] == ["Farmer's Delight"] and cards[0]["cat"] == "comida"
    assert 436 in cf.calls[0]["category_ids"]


def test_manual_download_when_distribution_not_allowed():
    cards = search(Cf([cf_mod(9, "Raro", "raro", allow=False)]), Mr([]), query="", category=None, sort="popular",
                   page=0, installed=[], **OPTS)
    assert cards[0]["manual"] is True


def test_detail_sanitized_with_screenshots():
    d = detail(Cf([cf_mod(1, "Create", "create")]), Mr([]), source=CF, project_id="1")
    assert "<script>" not in d["html"] and "Hola" in d["html"]
    assert "cl-flag" not in sanitize_html("<p>world</p>", flag=False)  # sin avisos en descripciones
    d = detail(None, Mr([mr_hit("p1", "Sodium", "sodium")]), source=MR, project_id="p1")
    assert "<iframe" not in d["html"] and "<h2>" in d["html"]
    assert d["images"] == ["https://cdn.modrinth.com/g.png"] and d["links"]["source"] == "https://github.com/x"


def test_install_plan_adds_dependencies_skips_installed_and_reports_manual(tmp_path, monkeypatch):
    from mod_updater.gui import api as api_mod
    from mod_updater.gui.api import Api
    from mod_updater.resolver import Dep
    from test_deps import FakeFinder, candidate

    jei = candidate("JEI", CF, "238222", deps=[Dep(CF, "1689768")])
    mezz = candidate("MezzConfig", CF, "1689768")
    raro = candidate("Raro", CF, "9", url=False)
    finder = FakeFinder({(CF, "238222"): jei, (CF, "1689768"): mezz, (CF, "9"): raro})
    monkeypatch.setattr(api_mod, "DependencyFinder", lambda *a, **k: finder)

    a = Api(tmp_path / "s.json", get_key=lambda: (None, None), run_async=lambda fn: fn(), cache_dir=tmp_path / "c",
            running=lambda d: [])
    assert a.install_plan([{"source": CF, "id": "238222", "name": "JEI"}])["ok"] is False  # sin revisión
    a._results = [installed("Create", CF, "328085")]
    res = a.install_plan([{"source": CF, "id": "238222", "name": "JEI"}, {"source": CF, "id": "328085", "name": "Create"},
                          {"source": CF, "id": "9", "name": "Raro"}])
    assert res["ok"] and [r["name"] for r in res["rows"]] == ["JEI", "MezzConfig"]
    assert res["rows"][1]["to"] == "0.7.1" and res["size"] == sum(r["size"] for r in res["rows"])
    assert res["rows"][1]["neededBy"] == ["JEI"]
    assert res["already"] == ["Create"] and res["manual"][0]["name"] == "Raro"

    started = []
    monkeypatch.setattr(a, "_apply", lambda chosen, s, index: started.append(([r.name for r in chosen], sorted(index.values()))))
    assert a.install_start()["ok"] is True
    assert started == [(["JEI", "MezzConfig"], [100000, 100001])]
    assert a.install_start()["ok"] is False  # el plan ya se ha usado
