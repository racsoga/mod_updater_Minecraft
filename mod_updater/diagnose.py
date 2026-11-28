"""Diagnóstico de crasheos (hito 4 del plan v4): lee los crash reports y los logs de la carpeta
de la partida y, con reglas locales (sin IA ni red), dice qué mod sospechar y por qué.

- Errores de carga de NeoForge: dependencias que faltan o con versión vieja, incompatibilidades.
- Mixins que fallan ("from mod X") y la clase que no encuentran (para saber con qué otro mod chocan).
- Trazas de pila: el primer mod que aparece (`TRANSFORMER/<modid>@...`) o el "Suspected Mod".
- Patrones de `knowledge/crasheos.json`: duplicados, mod de otro cargador, Java, falta de memoria.

Nada se sube a ningún sitio. `anonymize` quita el usuario de Windows, el de Minecraft y los
tokens antes de copiar un resumen.
"""

from __future__ import annotations

import getpass
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from .i18n import t
from .knowledge import load_knowledge

MAX_BYTES = 8 * 1024 * 1024  # de un log enorme solo interesa el final
PLATFORM_IDS = {"minecraft", "neoforge", "forge", "fml", "javafml", "mixinextras", "java"}


@dataclass
class Finding:
    kind: str  # missing | version | incompatible | mixin | suspect | duplicate | wrong_loader | java | oom
    mods: list[str] = field(default_factory=list)  # modIds afectados (el que falla o el sospechoso)
    target: str | None = None  # dependencia, mod incompatible o clase que falta
    detail: dict = field(default_factory=dict)
    evidence: list[str] = field(default_factory=list)  # líneas del informe que lo demuestran


# --------------------------------------------------------------------------- informes

def _kind(name: str) -> str:
    low = name.lower()
    for k in ("fml", "client", "server"):
        if low.endswith(f"-{k}.txt"):
            return k
    return "log" if low.endswith(".log") else "client"


def list_reports(game_dir: Path) -> list[dict]:
    """Crash reports (más recientes primero) y después latest.log y debug.log. Solo lectura."""
    out = []
    crash = Path(game_dir) / "crash-reports"
    try:
        files = [p for p in crash.iterdir() if p.is_file() and p.suffix.lower() == ".txt"] if crash.is_dir() else []
    except OSError:
        files = []
    for p in sorted(files, key=lambda p: p.stat().st_mtime, reverse=True):
        out.append({"path": p, "name": p.name, "kind": _kind(p.name), "mtime": p.stat().st_mtime})
    for name in ("latest.log", "debug.log"):
        p = Path(game_dir) / "logs" / name
        if p.is_file():
            out.append({"path": p, "name": name, "kind": "log", "mtime": p.stat().st_mtime})
    return out


def read_text(path: Path) -> str:
    """Texto del informe: como mucho los últimos 8 MB, sin bytes nulos y sin fallar por la codificación."""
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        f.seek(max(0, size - MAX_BYTES))
        data = f.read()
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = data.decode("cp1252", errors="replace")
    return text.replace("\x00", "")


def anonymize(text: str, windows_user: str | None = None) -> str:
    """Quita el usuario de Windows (rutas y nombre), el jugador de Minecraft, UUID y tokens."""
    user_tag, player_tag, hidden = t("dg.anon_user"), t("dg.anon_player"), t("dg.anon_hidden")
    players = set(re.findall(r"Setting user: ([^\s,\]]+)", text))
    players |= set(re.findall(r"--username[ ,=]+([^\s,\]]+)", text))
    text = re.sub(r"(--(?:accessToken|uuid|xuid|clientId)[ ,=]+)([^\s,\]]+)", lambda m: m.group(1) + hidden, text)
    text = re.sub(r"(?i)([\\/]Users[\\/])([^\\/\s]+)", lambda m: m.group(1) + user_tag, text)
    for name in sorted(players, key=len, reverse=True):
        if len(name) >= 3:
            text = re.sub(rf"(?<![\w]){re.escape(name)}(?![\w])", player_tag, text)
    try:
        windows_user = windows_user or getpass.getuser()
    except Exception:  # noqa: BLE001 - sin usuario no hay nada que quitar
        windows_user = None
    if windows_user and len(windows_user) >= 3:
        text = re.sub(rf"(?i)(?<![\w]){re.escape(windows_user)}(?![\w])", user_tag, text)
    return text


# --------------------------------------------------------------------------- reglas

_MISSING = re.compile(r"Mod (\S+) requires (\S+) ([^\r\n]+?)\s*[\r\n]+\s*Currently, \2 is not installed")
_VERSION = re.compile(r"Mod (\S+) requires (\S+) ([^\r\n]+?)\s*[\r\n]+\s*Currently, \2 is (?!not installed)(\S+)")
_INCOMPAT = re.compile(r"Mod (\S+) is incompatible with (\S+) ([^\r\n]+?)\s*[\r\n]+\s*Currently, \2 is (\S+)"
                       r"(?:\s*[\r\n]+\s*The reason is: ([^\r\n]+))?")
_FRAME = re.compile(r"^\s*at TRANSFORMER/([a-z0-9_.\-]+)@", re.MULTILINE)
_MIXIN_MOD = re.compile(r"[^\r\n]*[Mm]ixin[^\r\n]*?\bfrom mod ([a-z0-9_.\-]+)")
_NO_CLASS = re.compile(r"(?:ClassNotFoundException|NoClassDefFoundError):\s*([\w.$/]+)")
_SUSPECTED = re.compile(r"Suspected Mods?:\s*[\r\n]+((?:[ \t]+[^\r\n]+[\r\n]*)+)")


def _line(text: str, pos: int) -> str:
    start = text.rfind("\n", 0, pos) + 1
    end = text.find("\n", pos)
    return text[start:end if end != -1 else len(text)].strip()


def _not_frame(text: str, m: re.Match) -> bool:
    return not _line(text, m.start(1)).startswith("at ")


_QUIET_LEVEL = re.compile(r"/(?:DEBUG|INFO|WARN|TRACE)\]")
_ERROR_WORDS = re.compile(r"Exception|Error|error|failed|Failed|Critical|critical")


def _is_error_line(line: str) -> bool:
    """Un mixin solo cuenta si su línea es un error (no un aviso o una traza de depuración del log)."""
    return not _QUIET_LEVEL.search(line) and bool(_ERROR_WORDS.search(line))


_FATAL = re.compile(r"/FATAL\]|---- Minecraft Crash Report ----|Preparing crash report")


def analyze(text: str, *, log: bool = False) -> list[Finding]:
    """Hallazgos del informe, de más concreto a menos. Lista vacía si no hay nada que señalar.

    `log=True` (latest.log, debug.log): las trazas de errores que el juego captura y sigue no
    cuentan; solo se busca un sospechoso en la traza si hubo un fallo fatal."""
    out: list[Finding] = []

    missing: dict[str, Finding] = {}
    for m in _MISSING.finditer(text):
        mod, dep, rng = m.groups()
        f = missing.setdefault(dep, Finding("missing", target=dep, detail={"range": rng.strip()}))
        if mod not in f.mods:
            f.mods.append(mod)
            f.evidence.append(f"Mod {mod} requires {dep} {rng.strip()}")
    for f in missing.values():
        f.evidence.append(f"Currently, {f.target} is not installed")
        out.append(f)

    for m in _VERSION.finditer(text):
        mod, dep, rng, have = m.groups()
        out.append(Finding("version", [mod], dep, {"range": rng.strip(), "have": have},
                           [f"Mod {mod} requires {dep} {rng.strip()}", f"Currently, {dep} is {have}"]))

    for m in _INCOMPAT.finditer(text):
        mod, other, rng, have, reason = m.groups()
        ev = [f"Mod {mod} is incompatible with {other} {rng.strip()}"] + ([f"The reason is: {reason.strip()}"] if reason else [])
        out.append(Finding("incompatible", [mod], other, {"have": have, "reason": (reason or "").strip()}, ev))

    mixin = next((m for m in _MIXIN_MOD.finditer(text) if _not_frame(text, m) and _is_error_line(m.group(0))), None)
    if mixin is not None:
        f = Finding("mixin", [mixin.group(1)], evidence=[mixin.group(0).strip()[:300]])
        cls = next((c for c in _NO_CLASS.finditer(text) if _not_frame(text, c)), None)
        if cls is not None:
            f.target = cls.group(1).replace("/", ".")
            f.evidence.append(_line(text, cls.start())[:300])
        out.append(f)

    for p in load_knowledge().get("crasheos", []):
        for m in re.finditer(p["regex"], text):
            g = m.groupdict()
            if p["tipo"] == "duplicate":
                files = [x.strip() for x in (g.get("files") or "").split(",") if x.strip()]
                out.append(Finding("duplicate", [g.get("mod") or "?"], detail={"files": files}, evidence=[_line(text, m.start())]))
            elif p["tipo"] == "wrong_loader":
                out.append(Finding("wrong_loader", detail={"file": g.get("file"), "loader": g.get("loader")},
                                   evidence=[_line(text, m.start())]))
            elif not any(x.kind == p["tipo"] for x in out):  # java / oom: una vez basta
                out.append(Finding(p["tipo"], evidence=[_line(text, m.start())[:300]]))

    if not any(f.kind in ("missing", "version", "incompatible", "mixin", "duplicate", "wrong_loader") for f in out):
        suspect = _suspect(text) if not log or _FATAL.search(text) else None
        if suspect is not None:
            out.append(suspect)
    return out


def _suspect(text: str) -> Finding | None:
    """El mod más probable según la traza: el "Suspected Mod" si lo hay; si no, el primer
    mod que aparece en la causa más profunda (o en la traza principal)."""
    m = _SUSPECTED.search(text)
    if m:
        ids = re.findall(r"\(([a-z0-9_.\-]+)\)", m.group(1))
        ids = [i for i in ids if i not in PLATFORM_IDS]
        if ids:
            return Finding("suspect", [ids[0]], evidence=[_line(text, m.start(1))])
    blocks = re.split(r"^Caused by:", text, flags=re.MULTILINE)
    for block in reversed(blocks):
        for f in _FRAME.finditer(block):
            if f.group(1) not in PLATFORM_IDS:
                return Finding("suspect", [f.group(1)], evidence=[_line(block, f.start(1))[:300]])
    return None
