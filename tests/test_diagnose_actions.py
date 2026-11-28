"""Hito 4 (v4): acciones del diagnóstico. Ninguna acción propuesta debe crear un problema nuevo,
y si dos problemas se arreglan con la misma acción se muestra una sola (punto de control A)."""

from pathlib import Path

from mod_updater import i18n
from mod_updater.diagnose import analyze, plan_cards, read_text
from mod_updater.knowledge import load_knowledge
from mod_updater.resolver import ACTUALIZABLE, AL_DIA, CF, INSTALL, MR, Dep, Resolution
from mod_updater.scanner import ModFile

FIX = Path(__file__).parent / "fixtures" / "crash"
SODIUM_MR, EMBEDDIUM_MR = "AANobbMI", "sk9rgfiA"  # IDs reales (incompatibilidades.json)


def setup_module():
    i18n.set_language("es")


def inst(name, mod_id, *, pid=None, source=MR, status=AL_DIA, deps=(), requires=(), incompatible=(), packages=(),
         disabled=False, new_version=None):
    file_name = f"{mod_id}.jar" + (".disabled" if disabled else "")
    mod = ModFile(path=Path(file_name), file_name=file_name, size=1, sha1=mod_id, sha512="", cf_fingerprint=0,
                  mod_id=mod_id, requires=list(requires), incompatible=list(incompatible), packages=list(packages))
    pid = pid or f"p-{mod_id}"
    return Resolution(mod=mod, status=status, source=source, project_id=pid, project_name=name, current_version="1.0",
                      new_version=new_version, current_deps=list(deps), known_ids={(source, pid)})


def candidate(name, pid, source=MR):
    return Resolution(mod=None, kind=INSTALL, status=ACTUALIZABLE, source=source, project_id=pid, project_name=name,
                      new_version="0.8.13", new_file_name=f"{name}-0.8.13.jar",
                      download_url="https://cdn.modrinth.com/x.jar", known_ids={(source, pid)})


def cards_for(fixture, results, lookup=lambda modid: None):
    return plan_cards(analyze(read_text(FIX / fixture)), results, lookup=lookup, knowledge=load_knowledge())


def labels(card):
    return [(a.label, a.primary) for a in card.actions]


SODIUM_CASE = [inst("Iris Flywheel Compat", "irisflw"), inst("Create Better FPS", "createbetterfps"),
               inst("Iris", "iris"), inst("Embeddium", "embeddium", pid=EMBEDDIUM_MR)]


def test_real_case_one_swap_fixes_both_problems():
    cards = cards_for("fml_sodium.txt", SODIUM_CASE,
                      lookup=lambda m: candidate("Sodium", SODIUM_MR) if m == "sodium" else None)
    assert len(cards) == 1
    c = cards[0]
    assert labels(c)[0] == ("Cambiar Embeddium por Sodium", True)
    assert ("Desactivar Iris Flywheel Compat y Create Better FPS", False) in labels(c)
    assert ("Desactivar Iris", False) in labels(c)
    assert "Instalar Sodium" not in [label for label, _ in labels(c)]  # instalarlo solo chocaría con Embeddium
    swap = c.actions[0]
    assert swap.type == "swap" and swap.files == ["embeddium.jar"] and swap.install.project_id == SODIUM_MR
    assert len(c.evidence) == 5  # las líneas de los dos problemas


def test_no_swap_if_something_needs_the_mod_to_remove():
    needs_embeddium = inst("Addon de Embeddium", "emb_addon", deps=[Dep(MR, EMBEDDIUM_MR)])
    cards = cards_for("fml_sodium.txt", SODIUM_CASE + [needs_embeddium],
                      lookup=lambda m: candidate("Sodium", SODIUM_MR) if m == "sodium" else None)
    every = [label for c in cards for label, _ in labels(c)]
    assert not any(label.startswith(("Cambiar", "Instalar Sodium")) for label in every)
    assert "Desactivar Embeddium y Addon de Embeddium" in every  # desactivar también nombra a quien lo necesita


def test_install_when_nothing_conflicts():
    text = "Mod jei requires mezz_config 1.0 or above\n\tCurrently, mezz_config is not installed\n"
    cards = plan_cards(analyze(text), [inst("Just Enough Items", "jei")],
                       lookup=lambda m: candidate("MezzConfig", "mz"), knowledge=load_knowledge())
    assert labels(cards[0])[0] == ("Instalar MezzConfig", True)


def test_installed_but_disabled_dependency_is_enabled():
    text = "Mod jei requires mezz_config 1.0 or above\n\tCurrently, mezz_config is not installed\n"
    cards = plan_cards(analyze(text), [inst("Just Enough Items", "jei"), inst("MezzConfig", "mezz_config", disabled=True)],
                       lookup=lambda m: None, knowledge=load_knowledge())
    assert labels(cards[0])[0] == ("Activar MezzConfig", True) and cards[0].actions[0].files == ["mezz_config.jar.disabled"]


def test_mixin_without_newer_version_promotes_the_next_action():
    create = inst("Create", "create", packages=["com.simibubi.create"])
    irisflw = inst("Iris Flywheel Compat", "irisflw")
    c = cards_for("client_mixin.txt", [create, irisflw])[0]
    assert c.title == "Iris Flywheel Compat no encaja con tu versión de Create"
    assert labels(c)[0] == ("Volver a una versión anterior de Create", True)
    assert c.note == "No hay versión más nueva de Iris Flywheel Compat."
    assert ("Desactivar Iris Flywheel Compat", False) in labels(c)
    assert "AllSpecialTextures" in c.why


def test_mixin_with_newer_version_updates_first():
    create = inst("Create", "create", packages=["com.simibubi.create"])
    irisflw = inst("Iris Flywheel Compat", "irisflw", status=ACTUALIZABLE, new_version="2.5.0")
    c = cards_for("client_mixin.txt", [create, irisflw])[0]
    assert labels(c)[0] == ("Actualizar Iris Flywheel Compat", True) and c.note == ""


def test_wrong_minecraft_version_cards_merge_per_mod():
    text = ("Mod xaerominimap requires minecraft 1.21 or above\n\tCurrently, minecraft is 1.20.1\n"
            "Mod xaerominimap requires neoforge 21.0 or above\n\tCurrently, neoforge is 20.4.1\n")
    cards = plan_cards(analyze(text), [inst("Xaero's Minimap", "xaerominimap")], lookup=lambda m: None,
                       knowledge=load_knowledge())
    assert len(cards) == 1 and labels(cards[0])[0] == ("Desactivar Xaero's Minimap", True)


def test_duplicate_disables_the_older_file():
    old, new = inst("JEI", "jei"), inst("JEI", "jei")
    old.mod.file_name, new.mod.file_name = "jei-1.21.1-neoforge-19.20.0.jar", "jei-1.21.1-neoforge-19.21.0.jar"
    cards = cards_for("inventado_varios.log", [old, new])
    dup = next(c for c in cards if c.kind == "duplicate")
    assert labels(dup)[0] == ("Desactivar jei-1.21.1-neoforge-19.20.0.jar", True)


def test_without_scan_there_are_explanations_but_no_actions():
    cards = cards_for("fml_sodium.txt", [])
    assert cards and all(c.actions == [] for c in cards)
