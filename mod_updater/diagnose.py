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
from .resolver import ACTUALIZABLE, CF, MR

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


# --------------------------------------------------------------------------- acciones

@dataclass
class Action:
    type: str  # install | swap | disable | enable | update | versions
    label: str
    primary: bool = False
    files: list[str] = field(default_factory=list)  # jars que se activan o desactivan
    install: object | None = None  # Resolution a instalar (install / swap)
    row: object | None = None  # Resolution del mod (update / versions)

    def key(self) -> tuple:
        pid = getattr(self.install, "project_id", None)
        return (self.type, tuple(sorted(self.files)), pid, id(self.row) if self.row is not None else None)


@dataclass
class Card:
    kind: str
    kicker: str
    title: str
    why: str
    evidence: list[str]
    actions: list[Action] = field(default_factory=list)
    note: str = ""
    subject: str = ""  # nombre del mod principal (para el título de la pantalla)
    targets: set = field(default_factory=set)  # modIds que esta tarjeta desactiva o sustituye


def _project_ids(entry: dict) -> set:
    ids = set()
    if entry.get("curseforge"):
        ids.add((CF, str(entry["curseforge"])))
    if entry.get("modrinth"):
        ids.add((MR, str(entry["modrinth"])))
    return ids


def _join(names: list[str]) -> str:
    names = [n for n in names if n]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + t("ui.and") + names[-1] if names else ""


def plan_cards(findings: list[Finding], results: list, *, lookup, knowledge: dict) -> list[Card]:
    """Tarjetas con acciones de un clic. `lookup(modid)` devuelve la Resolution a instalar (o None).

    Ninguna acción crea un problema nuevo: desactivar incluye (y nombra) a los mods que dependen
    de lo desactivado; instalar algo que choca con lo instalado se convierte en "Cambiar Y por X"
    solo si nadie necesita Y; si no, no se propone. Las tarjetas que se arreglan con la misma
    acción se fusionan en una."""
    from .deps import dependents_of  # aquí para no crear un import circular

    installed = [r for r in results if r.mod is not None]
    by_id: dict[str, list] = {}
    for r in installed:
        for m in [r.mod.mod_id, *r.mod.extra_mod_ids]:
            if m:
                by_id.setdefault(m, []).append(r)
    active = [r for r in installed if not r.mod.disabled]

    def name(modid: str) -> str:
        rs = by_id.get(modid)
        return rs[0].name if rs else modid

    def disable(rs: list, primary=False) -> Action | None:
        rs = [r for r in rs if not r.mod.disabled]
        if not rs:
            return None
        all_rs = rs + dependents_of(results, rs)
        return Action("disable", t("dg.act_disable", names=_join([r.name for r in all_rs])), primary,
                      files=[r.mod.file_name for r in all_rs])

    def update(r) -> Action | None:
        if r is not None and r.status == ACTUALIZABLE and not r.pinned:
            return Action("update", t("dg.act_update", name=r.name), row=r)
        return None

    pairs = []
    for p in knowledge.get("incompatibilidades", []):
        a, b = _project_ids(p.get("a") or {}), _project_ids(p.get("b") or {})
        pairs += [(a, b), (b, a)]

    def conflicts(cand, modid: str) -> list:
        """Mods activos que chocarían con `cand`: por la base de conocimiento, porque el mod
        instalado lo declara incompatible en su mods.toml, o porque la API lo declara."""
        api = {d.key for d in getattr(cand, "new_incompat", []) or []}
        return [y for y in active
                if any(cand.known_ids & a and y.known_ids & b for a, b in pairs)
                or modid in y.mod.incompatible or y.known_ids & api]

    cards: list[Card] = []
    for f in findings:
        ev = list(f.evidence)
        if f.kind == "missing":
            needers = [r for m in f.mods for r in by_id.get(m, [])]
            dep_name = name(f.target)
            c = Card("missing", t("dg.k_missing"), t("dg.t_missing", name=dep_name),
                     t("dg.w_missing", count=len(f.mods), names=_join([name(m) for m in f.mods]), dep=dep_name,
                       range=f.detail.get("range", "")), ev, subject=dep_name)
            if installed:
                have = by_id.get(f.target, [])
                if have and all(r.mod.disabled for r in have):
                    c.actions.append(Action("enable", t("dg.act_enable", name=have[0].name), files=[have[0].mod.file_name]))
                elif not have:
                    cand = lookup(f.target)
                    if cand is None:
                        c.note = t("dg.note_not_found", name=dep_name)
                    else:
                        dep_name = cand.name
                        c.title = t("dg.t_missing", name=dep_name)
                        c.why = t("dg.w_missing", count=len(f.mods), names=_join([name(m) for m in f.mods]), dep=dep_name,
                                  range=f.detail.get("range", ""))
                        clash = conflicts(cand, f.target)
                        if not clash:
                            c.actions.append(Action("install", t("dg.act_install", name=cand.name), install=cand))
                        elif not dependents_of(results, clash):
                            c.actions.append(Action("swap", t("dg.act_swap", old=_join([y.name for y in clash]), new=cand.name),
                                                    files=[y.mod.file_name for y in clash], install=cand))
                            c.targets |= {y.mod.mod_id for y in clash}
                        else:
                            c.note = t("dg.note_conflict", name=cand.name, names=_join([y.name for y in clash]))
                a = disable(needers)
                if a:
                    c.actions.append(a)
            cards.append(c)
        elif f.kind == "version" and f.target in PLATFORM_IDS:
            mod = name(f.mods[0])
            key = "dg.w_wrong_mc" if f.target == "minecraft" else "dg.w_old_loader"
            c = Card("platform", t("dg.k_platform"), t("dg.t_platform", name=mod),
                     t(key, name=mod, range=f.detail["range"], have=f.detail["have"]), ev, subject=mod)
            a = disable(by_id.get(f.mods[0], []))
            if a:
                c.actions.append(a)
            cards.append(c)
        elif f.kind == "version":
            mod, dep = name(f.mods[0]), name(f.target)
            c = Card("version", t("dg.k_version"), t("dg.t_version", name=dep),
                     t("dg.w_version", name=mod, dep=dep, range=f.detail["range"], have=f.detail["have"]), ev, subject=dep)
            if installed:
                target = (by_id.get(f.target) or [None])[0]
                up = update(target)
                if up:
                    c.actions.append(up)
                elif target is not None:
                    c.note = t("dg.no_newer", name=dep)
                a = disable(by_id.get(f.mods[0], []))
                if a:
                    c.actions.append(a)
            cards.append(c)
        elif f.kind == "incompatible":
            mod, other = name(f.mods[0]), name(f.target)
            why = t("dg.w_incompat", name=mod, other=other)
            c = Card("incompatible", t("dg.k_incompat"), t("dg.t_incompat", name=mod, other=other), why, ev, subject=other)
            c.targets |= {f.target, f.mods[0]}
            for rs in (by_id.get(f.target, []), by_id.get(f.mods[0], [])):
                a = disable(rs)
                if a:
                    c.actions.append(a)
            cards.append(c)
        elif f.kind in ("mixin", "suspect"):
            mod = name(f.mods[0])
            r = (by_id.get(f.mods[0]) or [None])[0]
            owner = None
            if f.target:
                owner = next((o for o in installed if o is not r and any(
                    f.target == p or f.target.startswith(p + ".") for p in o.mod.packages)), None)
            if owner is not None:
                c = Card(f.kind, t("dg.k_likely"), t("dg.t_mixin_other", name=mod, other=owner.name),
                         t("dg.w_mixin_other", name=mod, other=owner.name, cls=f.target.rsplit(".", 1)[-1]), ev, subject=mod)
            elif f.kind == "mixin":
                c = Card(f.kind, t("dg.k_likely"), t("dg.t_suspect", name=mod), t("dg.w_mixin", name=mod), ev, subject=mod)
            else:
                c = Card(f.kind, t("dg.k_possible"), t("dg.t_suspect", name=mod), t("dg.w_suspect", name=mod), ev, subject=mod)
            if r is not None:
                up = update(r)
                if up:
                    c.actions.append(up)
                else:
                    c.note = t("dg.no_newer", name=mod)
                if owner is not None:
                    c.actions.append(Action("versions", t("dg.act_versions", name=owner.name), row=owner))
                a = disable([r])
                if a:
                    c.actions.append(a)
            cards.append(c)
        elif f.kind == "duplicate":
            files = f.detail.get("files", [])
            mod = name(f.mods[0])
            c = Card("duplicate", t("dg.k_duplicate"), t("dg.t_duplicate", name=mod), t("dg.w_duplicate", name=mod), ev, subject=mod)
            keep = sorted(files)[-1:] if files else []
            for fn in sorted(files):
                r = next((x for x in installed if x.mod.file_name == fn), None)
                if fn not in keep and r is not None and not r.mod.disabled:
                    c.actions.append(Action("disable", t("dg.act_disable", names=fn), files=[fn]))
            cards.append(c)
        elif f.kind == "wrong_loader":
            fn = f.detail.get("file") or "?"
            c = Card("wrong_loader", t("dg.k_wrong_loader"), t("dg.t_wrong_loader", file=fn),
                     t("dg.w_wrong_loader", file=fn, loader=f.detail.get("loader") or "?"), ev, subject=fn)
            r = next((x for x in installed if x.mod.file_name == fn and not x.mod.disabled), None)
            if r is not None:
                c.actions.append(Action("disable", t("dg.act_disable", names=fn), files=[fn]))
            cards.append(c)
        elif f.kind in ("java", "oom"):
            cards.append(Card(f.kind, t(f"dg.k_{f.kind}"), t(f"dg.t_{f.kind}"), t(f"dg.w_{f.kind}"), ev))
    return _merge(cards)


def _merge(cards: list[Card]) -> list[Card]:
    """Una tarjeta por acción: si un cambio (p. ej. "Cambiar Embeddium por Sodium") arregla también
    otra tarjeta (la incompatibilidad con Embeddium), o dos tarjetas tienen la misma acción
    principal, se juntan. Después se marca como principal la primera acción de cada tarjeta."""
    out: list[Card] = []
    for c in cards:
        host = None
        for o in out:
            swap = next((a for a in o.actions if a.type == "swap"), None)
            if c.kind == "incompatible" and swap is not None and o.targets & c.targets:
                host = o
            elif c.actions and o.actions and c.actions[0].key() == o.actions[0].key():
                host = o
            if host is not None:
                break
        if host is None:
            out.append(c)
            continue
        host.why = f"{host.why} {c.why}"
        host.evidence += [e for e in c.evidence if e not in host.evidence]
        keys = {a.key() for a in host.actions}
        swapped = {fn for a in host.actions if a.type == "swap" for fn in a.files}
        for a in c.actions:
            if a.key() not in keys and not (a.type == "disable" and set(a.files) <= swapped):
                host.actions.append(a)
    for c in out:
        for i, a in enumerate(c.actions):
            a.primary = i == 0
    return out
