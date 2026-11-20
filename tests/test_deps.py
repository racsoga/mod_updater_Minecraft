"""Planificación de dependencias. Caso real de referencia: JEI 19.71 requiere MezzConfig."""

from pathlib import Path

from mod_updater.deps import plan_with_dependencies
from mod_updater.resolver import (
    ACTUALIZABLE,
    AL_DIA,
    CF,
    DESCARGA_MANUAL,
    INSTALL,
    MR,
    Dep,
    Resolution,
)
from mod_updater.scanner import ModFile

# IDs reales de CurseForge / Modrinth
JEI_CF, MEZZ_CF = "238222", "1689768"
MEZZ_MR = "7tEfOcA7"


def installed(name, *, source=CF, pid="1", status=AL_DIA, current_deps=(), new_deps=(),
              mod_id=None, mr_id=None, current_date="2026-01-01", slug=None):
    mod = ModFile(path=Path(f"{name}.jar"), file_name=f"{name}.jar", size=1, sha1=name, sha512="",
                  cf_fingerprint=0, mod_id=mod_id or name.lower())
    ids = {(source, pid)}
    if mr_id:
        ids.add((MR, mr_id))
    return Resolution(
        mod=mod, status=status, source=source, project_id=pid, project_name=name, slug=slug,
        current_version="1.0", current_date=current_date, new_version="2.0" if status == ACTUALIZABLE else None,
        new_file_name=f"{name}-2.0.jar" if status == ACTUALIZABLE else None,
        download_url="https://edge.forgecdn.net/x.jar" if status == ACTUALIZABLE else None,
        new_sha1="abc", current_deps=list(current_deps), new_deps=list(new_deps), known_ids=ids,
    )


def candidate(name, source, pid, *, url=True, deps=(), slug=None):
    return Resolution(
        mod=None, kind=INSTALL, status=ACTUALIZABLE if url else DESCARGA_MANUAL, source=source,
        project_id=pid, project_name=name, slug=slug or name.lower(), project_url=f"https://x/{name}",
        new_version="0.7.1", new_file_name=f"{name}-0.7.1.jar",
        download_url="https://cdn.modrinth.com/x.jar" if url else None, new_sha1="abc",
        new_deps=list(deps), known_ids={(source, pid)},
    )


class FakeFinder:
    def __init__(self, catalog=None, dates=None):
        self.catalog = catalog or {}  # (source, id) -> Resolution
        self.dates = dates or {}  # version_id -> fecha
        self.calls = []

    def find(self, dep):
        self.calls.append(dep.key)
        return self.catalog.get(dep.key)

    def version_date(self, dep):
        return self.dates.get(dep.version_id)


def names(items):
    return sorted(r.name for r in items)


# --------------------------------------------------------------------------- caso JEI → MezzConfig

def test_jei_update_adds_missing_mezzconfig():
    jei = installed("JEI", pid=JEI_CF, status=ACTUALIZABLE, new_deps=[Dep(CF, MEZZ_CF)])
    other = installed("Balm", pid="531761")
    finder = FakeFinder({(CF, MEZZ_CF): candidate("MezzConfig", CF, MEZZ_CF)})

    plan = plan_with_dependencies([jei, other], [jei], finder)

    assert names(plan.items) == ["JEI", "MezzConfig"]
    mezz = plan.installs[0]
    assert mezz.kind == INSTALL
    assert mezz.required_by == ["JEI"]
    assert plan.blocked == [] and plan.broken == []


def test_installed_jei_without_mezzconfig_is_detected_and_fixed():
    # La carpeta ya está rota: JEI instalado (sin actualizar) y MezzConfig ausente.
    jei = installed("JEI", pid=JEI_CF, current_deps=[Dep(CF, MEZZ_CF)])
    finder = FakeFinder({(CF, MEZZ_CF): candidate("MezzConfig", CF, MEZZ_CF)})

    plan = plan_with_dependencies([jei], [], finder)

    assert names(plan.items) == ["MezzConfig"]
    assert plan.installs[0].required_by == ["JEI"]


def test_mezzconfig_already_installed_by_id():
    jei = installed("JEI", pid=JEI_CF, status=ACTUALIZABLE, new_deps=[Dep(CF, MEZZ_CF)])
    mezz = installed("MezzConfig", pid=MEZZ_CF)
    finder = FakeFinder()
    plan = plan_with_dependencies([jei, mezz], [jei], finder)
    assert names(plan.items) == ["JEI"]
    assert finder.calls == []


def test_dependency_known_only_by_other_source_id():
    # JEI resuelto por Modrinth pide MezzConfig por su ID de Modrinth; MezzConfig
    # está instalado y se identificó por CurseForge, pero también tiene ID de Modrinth.
    jei = installed("JEI", source=MR, pid="u6dRKJwZ", status=ACTUALIZABLE, new_deps=[Dep(MR, MEZZ_MR)])
    mezz = installed("MezzConfig", pid=MEZZ_CF, mr_id=MEZZ_MR)
    plan = plan_with_dependencies([jei, mezz], [jei], FakeFinder())
    assert names(plan.items) == ["JEI"]


def test_dependency_matched_by_mod_id_when_ids_unknown():
    jei = installed("JEI", pid=JEI_CF, status=ACTUALIZABLE, new_deps=[Dep(CF, MEZZ_CF)])
    mezz = installed("mezz-config-jar", pid="999", mod_id="mezzconfig")  # identificado con otro ID
    finder = FakeFinder({(CF, MEZZ_CF): candidate("MezzConfig", CF, MEZZ_CF, slug="mezzconfig")})
    plan = plan_with_dependencies([jei, mezz], [jei], finder)
    assert names(plan.items) == ["JEI"]


# --------------------------------------------------------------------------- recursión, ciclos, compartidas

def test_recursive_dependencies():
    a = installed("A", pid="1", status=ACTUALIZABLE, new_deps=[Dep(CF, "2")])
    finder = FakeFinder({
        (CF, "2"): candidate("B", CF, "2", deps=[Dep(CF, "3")]),
        (CF, "3"): candidate("C", CF, "3"),
    })
    plan = plan_with_dependencies([a], [a], finder)
    assert names(plan.items) == ["A", "B", "C"]
    c = next(r for r in plan.items if r.name == "C")
    assert c.required_by == ["B"]


def test_cycle_terminates():
    a = installed("A", pid="1", status=ACTUALIZABLE, new_deps=[Dep(CF, "2")])
    finder = FakeFinder({
        (CF, "2"): candidate("B", CF, "2", deps=[Dep(CF, "3")]),
        (CF, "3"): candidate("C", CF, "3", deps=[Dep(CF, "2"), Dep(CF, "1")]),
    })
    plan = plan_with_dependencies([a], [a], finder)
    assert names(plan.items) == ["A", "B", "C"]
    assert finder.calls.count((CF, "2")) == 1


def test_shared_dependency_installed_once():
    a = installed("A", pid="1", status=ACTUALIZABLE, new_deps=[Dep(CF, "9")])
    b = installed("B", pid="2", status=ACTUALIZABLE, new_deps=[Dep(CF, "9")])
    finder = FakeFinder({(CF, "9"): candidate("Lib", CF, "9")})
    plan = plan_with_dependencies([a, b], [a, b], finder)
    assert names(plan.items) == ["A", "B", "Lib"]
    assert sorted(plan.installs[0].required_by) == ["A", "B"]
    assert finder.calls == [(CF, "9")]


# --------------------------------------------------------------------------- bloqueos

def test_undownloadable_dependency_blocks_update():
    jei = installed("JEI", pid=JEI_CF, status=ACTUALIZABLE, new_deps=[Dep(CF, MEZZ_CF)])
    finder = FakeFinder({(CF, MEZZ_CF): candidate("MezzConfig", CF, MEZZ_CF, url=False)})
    plan = plan_with_dependencies([jei], [jei], finder)
    assert plan.items == []
    assert plan.blocked == [jei]
    assert jei.status == DESCARGA_MANUAL
    assert "MezzConfig" in jei.note


def test_dependency_without_compatible_version_is_ignored_with_warning():
    # Caso real: Create: Escalated declara "Create Fabric" (CF 624165), que no
    # tiene versión para NeoForge 1.21.1. No debe bloquear nada.
    a = installed("Create: Escalated", pid="1", status=ACTUALIZABLE, new_deps=[Dep(CF, "624165")])
    plan = plan_with_dependencies([a], [a], FakeFinder())
    assert plan.items == [a] and plan.blocked == []
    assert len(plan.ignored) == 1 and "Create: Escalated" in plan.ignored[0]


def test_ignored_dependency_on_installed_mod_is_not_reported_as_broken():
    a = installed("Create: Escalated", pid="1", current_deps=[Dep(CF, "624165")])
    b = installed("Other", pid="2", current_deps=[Dep(CF, "624165")])
    finder = FakeFinder()
    plan = plan_with_dependencies([a, b], [], finder)
    assert plan.items == [] and plan.broken == []
    assert len(plan.ignored) == 2
    assert finder.calls == [(CF, "624165")]  # se busca una sola vez


def test_version_from_filename():
    from mod_updater.deps import version_from_filename

    assert version_from_filename("mezzconfig-neoforge-1.21.1-0.7.1.jar", "1.21.1") == "0.7.1"
    assert version_from_filename("lib-2.3.jar", "1.21.1") == "2.3"
    assert version_from_filename("nada.jar", "1.21.1") is None


def test_block_propagates_through_chain():
    a = installed("A", pid="1", status=ACTUALIZABLE, new_deps=[Dep(CF, "2")])
    other = installed("Other", pid="5", status=ACTUALIZABLE)
    finder = FakeFinder({
        (CF, "2"): candidate("B", CF, "2", deps=[Dep(CF, "3")]),
        (CF, "3"): candidate("C", CF, "3", url=False),
    })
    plan = plan_with_dependencies([a, other], [a, other], finder)
    assert names(plan.items) == ["Other"]  # ni A ni B (que ya nadie necesita)
    assert plan.blocked == [a]


def test_broken_installed_mod_with_undownloadable_dep_is_reported():
    jei = installed("JEI", pid=JEI_CF, current_deps=[Dep(CF, MEZZ_CF)])
    finder = FakeFinder({(CF, MEZZ_CF): candidate("MezzConfig", CF, MEZZ_CF, url=False)})
    plan = plan_with_dependencies([jei], [], finder)
    assert plan.items == []
    assert len(plan.broken) == 1 and "MezzConfig" in plan.broken[0]
    assert jei.status == AL_DIA  # no se toca su estado: no se iba a actualizar


# --------------------------------------------------------------------------- versión mínima exigida

def test_required_newer_version_pulls_dependency_update():
    lib = installed("Lib", source=MR, pid="L", status=ACTUALIZABLE, current_date="2026-01-01")
    a = installed("A", source=MR, pid="A", status=ACTUALIZABLE, new_deps=[Dep(MR, "L", "v-new")])
    finder = FakeFinder(dates={"v-new": "2026-06-01"})
    plan = plan_with_dependencies([a, lib], [a], finder)  # el usuario solo eligió A (--only)
    assert names(plan.items) == ["A", "Lib"]
    assert lib.required_by == ["A"]
    assert plan.added_updates == [lib]


def test_required_version_already_satisfied():
    lib = installed("Lib", source=MR, pid="L", status=ACTUALIZABLE, current_date="2026-07-01")
    a = installed("A", source=MR, pid="A", status=ACTUALIZABLE, new_deps=[Dep(MR, "L", "v-old")])
    plan = plan_with_dependencies([a, lib], [a], FakeFinder(dates={"v-old": "2026-06-01"}))
    assert names(plan.items) == ["A"]


def test_required_newer_version_not_available_blocks():
    lib = installed("Lib", source=MR, pid="L", status=AL_DIA, current_date="2026-01-01")
    a = installed("A", source=MR, pid="A", status=ACTUALIZABLE, new_deps=[Dep(MR, "L", "v-new")])
    plan = plan_with_dependencies([a, lib], [a], FakeFinder(dates={"v-new": "2026-06-01"}))
    assert plan.items == [] and plan.blocked == [a]
