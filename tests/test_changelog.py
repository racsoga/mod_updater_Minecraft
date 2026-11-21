"""Changelog antes de actualizar: limpieza del HTML/Markdown, rango de versiones y API."""

from pathlib import Path

from mod_updater.changelog import changelog_for, markdown_to_html, sanitize_html
from mod_updater.curseforge import CfFile
from mod_updater.modrinth import MrFile, MrVersion
from mod_updater.net import ApiError
from mod_updater.resolver import ACTUALIZABLE, CF, MR, Resolution
from mod_updater.scanner import ModFile

# --------------------------------------------------------------------------- limpieza


def test_script_and_its_content_are_removed():
    out = sanitize_html('<p>Hola</p><script>alert("x")</script><style>p{}</style>')
    assert "script" not in out and "alert" not in out and "style" not in out and "Hola" in out


def test_event_handlers_and_style_attributes_removed():
    out = sanitize_html('<p onclick="x()" style="color:red" class="a">Texto</p><img src="https://media.forgecdn.net/a.png" onerror="x()">')
    assert "onclick" not in out and "style=" not in out and "class=" not in out and "onerror" not in out
    assert '<img src="https://media.forgecdn.net/a.png"' in out


def test_javascript_links_lose_href_but_keep_text():
    out = sanitize_html('<a href="javascript:alert(1)">pulsa</a> <a href="https://github.com/x">repo</a>')
    assert "javascript" not in out and "pulsa" in out
    assert '<a href="https://github.com/x" data-external rel="noopener">repo</a>' in out


def test_iframes_forms_and_objects_removed():
    out = sanitize_html('<iframe src="https://evil"></iframe><form><input></form><object data="x"></object><b>ok</b>')
    assert "iframe" not in out and "form" not in out and "input" not in out and "object" not in out
    assert "<b>ok</b>" in out


def test_images_only_from_known_cdns():
    out = sanitize_html('<img src="https://evil.example/track.gif"><img src="http://media.forgecdn.net/x.png">'
                        '<img src="https://cdn.modrinth.com/data/x.png" alt="captura">')
    assert "evil" not in out and "http://media" not in out
    assert '<img src="https://cdn.modrinth.com/data/x.png" alt="captura"' in out


def test_unknown_tags_dropped_content_kept_and_structure_closed():
    out = sanitize_html("<div><font>Nuevo</font><ul><li>uno<li>dos</ul></div><p>sin cerrar")
    assert "div" not in out and "font" not in out and "Nuevo" in out
    assert out.count("<li>") == out.count("</li>") == 2 and out.endswith("</p>")


def test_warning_words_are_marked():
    out = sanitize_html("<p>BREAKING: requires a new world. Incompatible with old saves. Worldgen tweaks.</p>")
    assert '<mark class="cl-flag">BREAKING</mark>' in out
    assert '<mark class="cl-flag">requires</mark>' in out and '<mark class="cl-flag">world</mark>' in out
    assert '<mark class="cl-flag">Incompatible</mark>' in out
    assert "Worldgen" in out and "<mark class=\"cl-flag\">Worldgen" not in out  # solo palabras completas


def test_text_is_escaped():
    assert "&lt;3" in sanitize_html("<p>I &lt;3 mods</p>")


def test_empty_or_whitespace_is_empty():
    assert sanitize_html("") == "" and sanitize_html("<p> </p><br>") == ""


def test_markdown_converted_and_raw_html_neutralised():
    out = markdown_to_html("## Cambios\n\n- **Nuevo** bloque\n- [web](https://modrinth.com)\n\n<script>x</script>")
    assert "<h2>" in out and "<li><strong>Nuevo</strong> bloque</li>" in out
    assert '<a href="https://modrinth.com" data-external rel="noopener">web</a>' in out
    assert "<script>" not in out


# --------------------------------------------------------------------------- rango de versiones


def cf_file(fid, date, name=None):
    return CfFile(id=str(fid), mod_id=1, display_name=name or f"v{fid}", file_name=f"m-{fid}.jar",
                  date_published=date, version_type="release", download_url="https://edge.forgecdn.net/x.jar",
                  sha1="s", fingerprint=None)


class FakeCf:
    def __init__(self, files, notes, fail=False):
        self.files, self.notes, self.fail, self.calls = files, notes, fail, []

    def mod_files(self, mod_id, game_version, loader):
        if self.fail:
            raise ApiError("sin red", kind="offline")
        return self.files

    def file_changelog(self, mod_id, file_id):
        self.calls.append(file_id)
        return self.notes.get(str(file_id), "")


def update(source=CF, current_date="2026-01-01T00:00:00Z", new_date="2026-04-01T00:00:00Z"):
    mod = ModFile(path=Path("m.jar"), file_name="m.jar", size=1, sha1="h", sha512="", cf_fingerprint=0)
    return Resolution(mod=mod, status=ACTUALIZABLE, source=source, project_id="1", project_name="Mod",
                      project_url="https://www.curseforge.com/minecraft/mc-mods/mod", current_version="1.0",
                      current_date=current_date, new_version="1.3", new_date=new_date)


def test_curseforge_all_versions_between_installed_and_new_newest_first():
    files = [cf_file(14, "2026-05-01T00:00:00Z"), cf_file(13, "2026-04-01T00:00:00Z"),
             cf_file(12, "2026-03-01T00:00:00Z"), cf_file(11, "2026-02-01T00:00:00Z"),
             cf_file(10, "2026-01-01T00:00:00Z")]
    cf = FakeCf(files, {"13": "<p>Tres</p>", "12": "<p>Dos</p>", "11": ""})
    data = changelog_for(update(), curseforge=cf, modrinth=None, game_version="1.21.1", loader="neoforge")
    assert [v["version"] for v in data["versions"]] == ["v13", "v12", "v11"]  # ni la instalada ni la posterior
    assert data["versions"][0]["html"] == "<p>Tres</p>" and data["versions"][2]["html"] == ""
    assert data["more"] == 0


def test_long_ranges_are_capped():
    files = [cf_file(100 + i, f"2026-03-{i + 1:02d}T00:00:00Z") for i in range(25)][::-1]
    cf = FakeCf(files, {})
    data = changelog_for(update(new_date="2026-03-25T00:00:00Z"), curseforge=cf, modrinth=None,
                         game_version="1.21.1", loader="neoforge")
    assert len(data["versions"]) == 15 and data["more"] == 10 and len(cf.calls) == 15


class FakeMr:
    def project_versions(self, project_id, loader, game_version):
        def v(n, date, notes):
            return MrVersion(id=n, project_id="p", name=n, version_number=n, version_type="release",
                             date_published=date, files=[MrFile("u", f"{n}.jar", "s", "s", 1, True)], changelog=notes)
        return [v("1.3", "2026-04-01T00:00:00Z", "- Arreglado **todo**"), v("1.2", "2026-02-01T00:00:00Z", ""),
                v("1.0", "2026-01-01T00:00:00Z", "vieja")]


def test_modrinth_markdown_versions_between():
    data = changelog_for(update(source=MR), curseforge=None, modrinth=FakeMr(), game_version="1.21.1", loader="neoforge")
    assert [v["version"] for v in data["versions"]] == ["1.3", "1.2"]
    assert "<strong>todo</strong>" in data["versions"][0]["html"] and data["versions"][1]["html"] == ""


def test_api_changelog_for_row_and_offline(tmp_path):
    from mod_updater.gui.api import Api
    a = Api(tmp_path / "s.json", get_key=lambda: ("k", "keyring"), run_async=lambda fn: fn(), cache_dir=tmp_path / "c",
            cf_factory=lambda key: FakeCf([cf_file(11, "2026-02-01T00:00:00Z")], {"11": "<p>Uno</p>"}))
    a._rows = [update()]
    res = a.changelog(0)
    assert res["ok"] and res["name"] == "Mod" and res["from"] == "1.0" and res["to"] == "1.3"
    assert res["versions"][0]["html"] == "<p>Uno</p>"
    a._changelogs.clear()
    a._cf_factory = lambda key: FakeCf([], {}, fail=True)
    res = a.changelog(0)
    assert res["ok"] is False and res["message"]
    assert a.changelog(99)["ok"] is False  # fila inexistente
