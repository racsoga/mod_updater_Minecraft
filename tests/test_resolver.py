from dataclasses import dataclass
from pathlib import Path

from mod_updater.modrinth import MrFile, MrVersion
from mod_updater.resolver import (
    ACTUALIZABLE,
    AL_DIA,
    NO_ENCONTRADO,
    DESCARGA_MANUAL,
    choose_update,
    max_allowed_rank,
    resolve_with_modrinth,
)
from mod_updater.scanner import ModFile


@dataclass
class V:
    id: str
    version_type: str
    date_published: str


# --------------------------------------------------------------------------- regla de canal

def test_release_only_allows_release():
    assert max_allowed_rank("release", allow_beta=False) == 1


def test_beta_allows_beta():
    assert max_allowed_rank("beta", allow_beta=False) == 2


def test_allow_beta_flag():
    assert max_allowed_rank("release", allow_beta=True) == 2


def test_release_skips_newer_beta():
    cur = V("a", "release", "2024-01-01")
    cands = [V("c", "beta", "2024-03-01"), V("b", "release", "2024-02-01")]
    assert choose_update(cur, cands, allow_beta=False).id == "b"


def test_release_with_allow_beta_takes_beta():
    cur = V("a", "release", "2024-01-01")
    cands = [V("c", "beta", "2024-03-01"), V("b", "release", "2024-02-01")]
    assert choose_update(cur, cands, allow_beta=True).id == "c"


def test_beta_current_can_get_beta():
    cur = V("a", "beta", "2024-01-01")
    assert choose_update(cur, [V("b", "beta", "2024-02-01")], allow_beta=False).id == "b"


def test_beta_current_does_not_get_alpha():
    cur = V("a", "beta", "2024-01-01")
    assert choose_update(cur, [V("b", "alpha", "2024-02-01")], allow_beta=False) is None


def test_same_version_is_up_to_date():
    cur = V("a", "release", "2024-01-01")
    assert choose_update(cur, [cur], allow_beta=False) is None


def test_older_candidate_is_not_an_update():
    # El usuario tiene una beta más nueva que la última release.
    cur = V("a", "beta", "2024-05-01")
    assert choose_update(cur, [V("b", "release", "2024-02-01")], allow_beta=False) is None


def test_no_candidates():
    assert choose_update(V("a", "release", "2024-01-01"), [], allow_beta=False) is None


# --------------------------------------------------------------------------- resolve_with_modrinth

def mod(name, sha1):
    return ModFile(path=Path(name), file_name=name, size=1, sha1=sha1, sha512="", cf_fingerprint=0)


def ver(id, project, vtype, date, url="https://cdn/x.jar"):
    return MrVersion(
        id=id, project_id=project, name=id, version_number=id, version_type=vtype,
        date_published=date,
        files=[MrFile(url=url, filename=f"{id}.jar", sha1="s1", sha512="s512", size=1, primary=True)],
    )


class FakeClient:
    def __init__(self, current, latest, history=None):
        self.current, self.latest, self.history = current, latest, history or {}
        self.history_calls = []

    def versions_from_hashes(self, sha1s):
        return {h: v for h, v in self.current.items() if h in sha1s}

    def latest_from_hashes(self, sha1s, loader, game_version):
        return {h: v for h, v in self.latest.items() if h in sha1s}

    def projects(self, ids):
        return {i: {"id": i, "title": i.upper(), "slug": i} for i in ids}

    def project_versions(self, project_id, loader, game_version):
        self.history_calls.append(project_id)
        return self.history.get(project_id, [])


def resolve(client, mods, allow_beta=False):
    return {r.mod.file_name: r for r in resolve_with_modrinth(
        mods, client, loader="neoforge", game_version="1.21.1", allow_beta=allow_beta)}


def test_resolve_states():
    old = ver("1.0", "p1", "release", "2024-01-01")
    new = ver("1.1", "p1", "release", "2024-02-01")
    same = ver("2.0", "p2", "release", "2024-01-01")
    manual_old = ver("3.0", "p3", "release", "2024-01-01")
    manual_new = ver("3.1", "p3", "release", "2024-02-01", url="")
    client = FakeClient(
        current={"h1": old, "h2": same, "h3": manual_old},
        latest={"h1": new, "h2": same, "h3": manual_new},
    )
    r = resolve(client, [mod("a.jar", "h1"), mod("b.jar", "h2"), mod("c.jar", "h3"), mod("d.jar", "h4")])
    assert r["a.jar"].status == ACTUALIZABLE
    assert r["a.jar"].new_version == "1.1"
    assert r["a.jar"].project_name == "P1"
    assert r["b.jar"].status == AL_DIA
    assert r["c.jar"].status == DESCARGA_MANUAL
    assert r["d.jar"].status == NO_ENCONTRADO


def test_resolve_falls_back_to_history_when_latest_is_beta():
    cur = ver("1.0", "p1", "release", "2024-01-01")
    beta = ver("2.0-beta", "p1", "beta", "2024-03-01")
    rel = ver("1.5", "p1", "release", "2024-02-01")
    client = FakeClient(current={"h1": cur}, latest={"h1": beta}, history={"p1": [beta, rel, cur]})
    r = resolve(client, [mod("a.jar", "h1")])
    assert client.history_calls == ["p1"]
    assert r["a.jar"].status == ACTUALIZABLE
    assert r["a.jar"].new_version == "1.5"


def test_resolve_allow_beta_takes_beta_directly():
    cur = ver("1.0", "p1", "release", "2024-01-01")
    beta = ver("2.0-beta", "p1", "beta", "2024-03-01")
    client = FakeClient(current={"h1": cur}, latest={"h1": beta})
    r = resolve(client, [mod("a.jar", "h1")], allow_beta=True)
    assert client.history_calls == []
    assert r["a.jar"].new_version == "2.0-beta"


def test_duplicate_projects_flagged():
    v = ver("1.0", "p1", "release", "2024-01-01")
    v2 = ver("0.9", "p1", "release", "2023-01-01")
    client = FakeClient(current={"h1": v, "h2": v2}, latest={"h1": v, "h2": v})
    r = resolve(client, [mod("a.jar", "h1"), mod("b.jar", "h2")])
    assert r["a.jar"].duplicate and r["b.jar"].duplicate
    assert "duplicado" in r["a.jar"].note


# --------------------------------------------------------------------------- CurseForge + combinación

from mod_updater.curseforge import CfFile, CfMatch
from mod_updater.resolver import resolve_all


def cf_file(id, mod_id, vtype, date, url="https://edge.forgecdn.net/x.jar"):
    return CfFile(id=str(id), mod_id=mod_id, display_name=f"v{id}", file_name=f"f{id}.jar",
                  date_published=date, version_type=vtype, download_url=url, sha1="s", fingerprint=None)


def cf_mod(name, sha1, fp):
    m = mod(name, sha1)
    m.cf_fingerprint = fp
    return m


class FakeCf:
    def __init__(self, matches, index, files, listing=None):
        self.matches, self.index, self._files, self.listing = matches, index, files, listing or {}
        self.listing_calls = []

    def match_fingerprints(self, fps):
        return {fp: m for fp, m in self.matches.items() if fp in fps}

    def mods(self, ids):
        return {i: {"id": i, "name": f"Mod{i}", "slug": f"mod{i}",
                    "latestFilesIndexes": [{"gameVersion": "1.21.1", "modLoader": 6, "fileId": f}
                                           for f in self.index.get(i, [])]} for i in ids}

    def files(self, ids):
        return {str(i): self._files[i] for i in ids if i in self._files}

    def mod_files(self, mod_id, game_version, loader):
        self.listing_calls.append(mod_id)
        return self.listing.get(mod_id, [])


def run_all(cf, mr, mods, allow_beta=False):
    return {r.mod.file_name: r for r in resolve_all(
        mods, curseforge=cf, modrinth=mr, loader="neoforge", game_version="1.21.1", allow_beta=allow_beta)}


def test_cf_primary_and_modrinth_fallback():
    cur1 = cf_file(10, 1, "release", "2024-01-01")
    new1 = cf_file(11, 1, "release", "2024-02-01")
    beta1 = cf_file(12, 1, "beta", "2024-03-01")
    cf = FakeCf(matches={100: CfMatch(1, cur1)}, index={1: [11, 12]}, files={11: new1, 12: beta1})
    mr = FakeClient(current={"h2": ver("1.0", "p2", "release", "2024-01-01")},
                    latest={"h2": ver("1.1", "p2", "release", "2024-02-01")})
    r = run_all(cf, mr, [cf_mod("a.jar", "h1", 100), cf_mod("b.jar", "h2", 200), cf_mod("c.jar", "h3", 300)])
    assert (r["a.jar"].source, r["a.jar"].status, r["a.jar"].new_version) == ("curseforge", ACTUALIZABLE, "v11")
    assert (r["b.jar"].source, r["b.jar"].status) == ("modrinth", ACTUALIZABLE)
    assert r["c.jar"].status == NO_ENCONTRADO


def test_cf_without_download_url_uses_modrinth():
    cur = cf_file(10, 1, "release", "2024-01-01")
    new = cf_file(11, 1, "release", "2024-02-01", url=None)
    cf = FakeCf(matches={100: CfMatch(1, cur)}, index={1: [11]}, files={11: new})
    mr = FakeClient(current={"h1": ver("1.0", "p1", "release", "2024-01-01")},
                    latest={"h1": ver("1.1", "p1", "release", "2024-02-01")})
    r = run_all(cf, mr, [cf_mod("a.jar", "h1", 100)])
    assert r["a.jar"].source == "modrinth"
    assert r["a.jar"].status == ACTUALIZABLE


def test_cf_without_download_url_and_no_modrinth_is_manual():
    cur = cf_file(10, 1, "release", "2024-01-01")
    new = cf_file(11, 1, "release", "2024-02-01", url=None)
    cf = FakeCf(matches={100: CfMatch(1, cur)}, index={1: [11]}, files={11: new})
    r = run_all(cf, FakeClient(current={}, latest={}), [cf_mod("a.jar", "h1", 100)])
    assert r["a.jar"].status == DESCARGA_MANUAL
    assert "curseforge.com" in r["a.jar"].note or "mod1" in r["a.jar"].note


def test_cf_missing_index_falls_back_to_file_listing():
    cur = cf_file(10, 1, "release", "2024-01-01")
    new = cf_file(11, 1, "release", "2024-02-01")
    cf = FakeCf(matches={100: CfMatch(1, cur)}, index={}, files={}, listing={1: [new, cur]})
    r = run_all(cf, FakeClient(current={}, latest={}), [cf_mod("a.jar", "h1", 100)])
    assert cf.listing_calls == [1]
    assert r["a.jar"].status == ACTUALIZABLE


def test_cf_release_ignores_beta_in_index():
    cur = cf_file(10, 1, "release", "2024-01-01")
    beta = cf_file(12, 1, "beta", "2024-03-01")
    cf = FakeCf(matches={100: CfMatch(1, cur)}, index={1: [10, 12]}, files={10: cur, 12: beta})
    r = run_all(cf, FakeClient(current={}, latest={}), [cf_mod("a.jar", "h1", 100)])
    assert r["a.jar"].status == AL_DIA
    r = run_all(cf, FakeClient(current={}, latest={}), [cf_mod("a.jar", "h1", 100)], allow_beta=True)
    assert r["a.jar"].new_version == "v12"


def test_up_to_date_release_reports_newer_beta():
    # Caso real: Create Enchantment Industry 2.4.2 (release) y 2.5.4b (beta).
    cur = cf_file(10, 1, "release", "2024-01-01")
    beta = cf_file(12, 1, "beta", "2024-03-01")
    cf = FakeCf(matches={100: CfMatch(1, cur)}, index={1: [10, 12]}, files={10: cur, 12: beta})
    r = run_all(cf, FakeClient(current={}, latest={}), [cf_mod("a.jar", "h1", 100)])
    assert r["a.jar"].status == AL_DIA
    assert r["a.jar"].newer_prerelease == "v12"


def test_modrinth_newer_beta_reported():
    cur = ver("2.4.2", "p1", "release", "2024-01-01")
    beta = ver("2.5.4b", "p1", "beta", "2024-03-01")
    client = FakeClient(current={"h1": cur}, latest={"h1": beta}, history={"p1": [beta, cur]})
    r = resolve(client, [mod("a.jar", "h1")])
    assert r["a.jar"].status == AL_DIA
    assert r["a.jar"].newer_prerelease == "2.5.4b"


def test_no_newer_beta_note_when_truly_latest():
    cur = ver("2.4.2", "p1", "release", "2024-03-01")
    client = FakeClient(current={"h1": cur}, latest={"h1": cur})
    r = resolve(client, [mod("a.jar", "h1")])
    assert r["a.jar"].newer_prerelease is None


from mod_updater.resolver import guess_version


def test_guess_version():
    assert guess_version("balm-neoforge-1.21.1-21.0.56.jar", "21.0.56", "balm-neoforge-1.21.1-21.0.67.jar") == "21.0.67"
    assert guess_version("AmbientSounds_NEOFORGE_v6.3.8_mc1.21.1.jar", "6.3.8",
                         "AmbientSounds_NEOFORGE_v6.3.11_mc1.21.1.jar") == "6.3.11"
    assert guess_version("a-1.0.jar", "1.0", "totally-different.jar") is None
    assert guess_version("a-1.0.jar", None, "a-1.1.jar") is None
    assert guess_version("1.0-a-1.0.jar", "1.0", "1.0-a-1.1.jar") is None  # ambiguo
