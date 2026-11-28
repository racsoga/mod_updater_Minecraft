"""Hito 4 (v4): diagnóstico de crasheos. Los informes de ejemplo están en tests/fixtures/crash/
(anonimizados a partir de informes reales o inventados)."""

import zipfile
from pathlib import Path

import pytest

from mod_updater import i18n
from mod_updater.scanner import read_metadata

FIX = Path(__file__).parent / "fixtures" / "crash"


def setup_module():
    i18n.set_language("es")


def jar_with(tmp_path, toml: str, classes=()):
    p = tmp_path / "m.jar"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("META-INF/neoforge.mods.toml", toml)
        for c in classes:
            z.writestr(c, b"")
    return zipfile.ZipFile(p)


SODIUM_TOML = '''modLoader="javafml"
loaderVersion="[1,)"
[[mods]]
modId="sodium"
version="0.8.13"
[[dependencies.sodium]]
modId="minecraft"
type="required"
versionRange="1.21.1"
[[dependencies.sodium]]
modId="embeddium"
type="incompatible"
reason="Sodium and Embeddium cannot be used together. Please remove Embeddium."
versionRange="[0.0.1,)"
'''


def test_scanner_reads_incompatible_mods_and_packages(tmp_path):
    classes = ["net/caffeinemc/mods/sodium/client/SodiumClientMod.class",
               "net/caffeinemc/mods/sodium/client/gui/Options.class",
               "net/caffeinemc/mods/sodium/mixin/Foo.class", "assets/sodium/lang/en_us.json"]
    meta = read_metadata(jar_with(tmp_path, SODIUM_TOML, classes))
    assert meta["incompatible"] == ["embeddium"]
    assert meta["packages"] == ["net.caffeinemc.mods.sodium"]


def test_packages_are_capped_and_skip_the_default_package(tmp_path):
    classes = ["Top.class"] + [f"com/a{i}/x/Y.class" for i in range(60)]
    meta = read_metadata(jar_with(tmp_path, SODIUM_TOML, classes))
    assert len(meta["packages"]) == 40 and "" not in meta["packages"]


# ---------------------------------------------------------------- lectura y anonimización

from mod_updater.diagnose import analyze, anonymize, list_reports, read_text  # noqa: E402


def fixture(name):
    return read_text(FIX / name)


def test_list_reports_newest_first_and_logs(tmp_path):
    import os
    game = tmp_path / ".minecraft"
    (game / "crash-reports").mkdir(parents=True)
    (game / "logs").mkdir()
    for i, name in enumerate(["crash-2026-11-22_18.08.26-fml.txt", "crash-2026-11-24_12.08.00-client.txt"]):
        p = game / "crash-reports" / name
        p.write_text("x", encoding="utf-8")
        os.utime(p, (1_700_000_000 + i * 100, 1_700_000_000 + i * 100))
    (game / "crash-reports" / "notas.md").write_text("x", encoding="utf-8")
    (game / "logs" / "latest.log").write_text("x", encoding="utf-8")
    reps = list_reports(game)
    assert [r["name"] for r in reps] == ["crash-2026-11-24_12.08.00-client.txt", "crash-2026-11-22_18.08.26-fml.txt", "latest.log"]
    assert [r["kind"] for r in reps] == ["client", "fml", "log"]
    assert list_reports(tmp_path / "no-existe") == []


def test_read_text_keeps_only_the_end_of_huge_logs(tmp_path):
    p = tmp_path / "latest.log"
    p.write_bytes(b"A" * (9 * 1024 * 1024) + b"\nFINAL linea\n")
    text = read_text(p)
    assert text.endswith("FINAL linea\n") and len(text) <= 8 * 1024 * 1024 + 10


def test_read_text_odd_encodings(tmp_path):
    p = tmp_path / "x.log"
    p.write_bytes("Mod café requires sodium\x00".encode("cp1252"))
    assert "Mod caf" in read_text(p) and "\x00" not in read_text(p)


def test_anonymize_removes_user_player_and_tokens():
    text = anonymize(fixture("inventado_varios.log"), windows_user="Ana")
    for secret in ("Ana_Juega", r"\Users\Ana" + "\\", "0123456789abcdef0123456789abcdef", "--accessToken, ????????"):
        assert secret not in text
    assert "<usuario>" in text and "<jugador>" in text


# ---------------------------------------------------------------- reglas

def kinds(findings):
    return [(f.kind, f.mods, f.target) for f in findings]


def test_real_fml_report_missing_dependency_and_incompatibility():
    f = analyze(fixture("fml_sodium.txt"))
    assert kinds(f) == [("missing", ["irisflw", "createbetterfps"], "sodium"),
                        ("incompatible", ["iris"], "embeddium")]
    assert f[0].evidence[0] == "Mod irisflw requires sodium 0.6.9 or above"
    assert "Please use Sodium 0.8 instead." in f[1].detail["reason"]


def test_real_client_report_mixin_with_missing_class():
    f = analyze(fixture("client_mixin.txt"))
    assert kinds(f)[0] == ("mixin", ["irisflw"], "com.simibubi.create.AllSpecialTextures")
    assert any("from mod irisflw" in line for line in f[0].evidence)


def test_suspect_from_stack_frames():
    f = analyze(fixture("inventado_sospechoso.txt"))
    assert kinds(f) == [("suspect", ["storagedrawers"], None)]


def test_patterns_from_knowledge_file():
    f = analyze(fixture("inventado_varios.log"))
    assert ("duplicate", ["jei"], None) in kinds(f)
    dup = next(x for x in f if x.kind == "duplicate")
    assert dup.detail["files"] == ["jei-1.21.1-neoforge-19.20.0.jar", "jei-1.21.1-neoforge-19.21.0.jar"]
    assert any(x.kind == "wrong_loader" and x.detail["file"] == "appleskin-fabric-mc1.21-3.0.5.jar" for x in f)
    assert any(x.kind == "java" for x in f)


def test_out_of_memory():
    assert kinds(analyze(fixture("inventado_memoria.txt"))) == [("oom", [], None)]


def test_clean_log_has_no_findings():
    assert analyze(fixture("inventado_limpio.log")) == []


def test_knowledge_file_is_valid():
    import json
    import re
    data = json.loads((Path(__file__).parent.parent / "mod_updater" / "knowledge" / "crasheos.json").read_text(encoding="utf-8"))
    assert data["patrones"]
    for p in data["patrones"]:
        re.compile(p["regex"])
        assert p["tipo"] in ("duplicate", "wrong_loader", "java", "oom") and p.get("fuente")


def test_caught_exception_in_a_log_is_not_a_suspect():
    log = ("[12:00:00] [Render thread/WARN] [jei/]: Error al leer una receta, se ignora\n"
           "java.lang.IllegalStateException: receta rara\n"
           "\tat TRANSFORMER/jei@19.21.0/mezz.jei.library.load.Plugins.load(Plugins.java:10)\n"
           "[12:00:01] [Render thread/INFO] [minecraft/]: Loaded 1234 recipes\n")
    assert analyze(log, log=True) == []
    fatal = log + "[12:05:00] [Render thread/FATAL] [minecraft/]: Unreported exception thrown!\n"
    assert [f.kind for f in analyze(fatal, log=True)] == ["suspect"]
