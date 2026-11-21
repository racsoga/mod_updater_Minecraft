"""Sugerencias según el tipo de partida: Quitar · Mantener · Añadir, cada una con su motivo.

Por reglas, con la base de conocimiento propia (`knowledge/`) y los datos de la revisión; sin IA
externa y sin enviar datos personales a nadie. Nada se aplica sin que el usuario lo marque.
"""

from __future__ import annotations

from .analysis import analyze
from .deps import name_key
from .i18n import t
from .resolver import CF, MR, Dep, Resolution

STYLES = ("tecnologia", "magia", "exploracion", "construir", "granjas", "combate", "tranquilo")
STYLE_CATS = {"tecnologia": {"tecnologia"}, "magia": {"magia"}, "exploracion": {"aventura", "mundo"},
              "construir": {"construccion"}, "granjas": {"comida"}, "combate": {"mobs"},
              "tranquilo": {"construccion", "comida", "calidad_vida"}}
HEAVY_BYTES = 40_000_000  # con un PC justo, los mods de más de 40 MB se señalan
KEEP_MAX = 15


def _keys(entry: dict) -> set[tuple[str, str]]:
    out = set()
    if entry.get("curseforge"):
        out.add((CF, str(entry["curseforge"])))
    if entry.get("modrinth"):
        out.add((MR, str(entry["modrinth"])))
    return out


def _style_label(style: str) -> str:
    return t(f"sug.style.{style}")


def suggest(answers: dict, installed: list[Resolution], finder, *, knowledge: dict, now: float | None = None) -> dict:
    styles = [s for s in answers.get("styles") or [] if s in STYLES]
    difficulty, pc, players = answers.get("difficulty"), answers.get("pc"), answers.get("players")
    max_mods = int(answers.get("max") or 0)
    inst = [r for r in installed if r.mod is not None]
    data = analyze(inst, include_libraries=True, now=now)

    def find_installed(entry: dict) -> list[Resolution]:
        keys, nk = _keys(entry), name_key(entry.get("nombre"))
        return [r for r in inst if r.known_ids & keys or (nk and name_key(r.name) == nk)]

    # Qué necesita cada mod instalado (para no sugerir quitar algo que otro mod usa).
    def needed(r: Resolution) -> bool:
        own = {r.mod.mod_id, *r.mod.extra_mod_ids} - {None}
        for o in inst:
            if o is r:
                continue
            if r.known_ids & {d.key for d in o.current_deps} or own & set(o.mod.requires):
                return True
        return False

    remove: dict[int, dict] = {}

    def flag(r: Resolution, reason: str) -> None:
        if id(r) not in remove and not needed(r):
            remove[id(r)] = {"name": r.name, "reason": reason, "source": r.source, "id": r.project_id, "file": r.mod.file_name}

    covered_groups: set[str] = set()
    for g in knowledge["solapamientos"]:
        present: list[Resolution] = []
        for m in g["mods"]:
            present += [r for r in find_installed(m) if r not in present]
        if present:
            covered_groups.add(g["grupo"])
        if len(present) > 1:
            keeper = next((r for r in present if needed(r)), present[0])
            for o in present:
                if o is not keeper:
                    flag(o, t("sug.reason.overlap", group=t(f"sug.group.{g['grupo']}"), keep=keeper.name, other=o.name))
    for pair in knowledge["incompatibilidades"]:
        a, b = find_installed(pair["a"]), find_installed(pair["b"])
        if a and b:
            flag(b[0], t("sug.reason.incompatible", other=a[0].name))
    by_name = {r.name: r for r in inst}
    for s in data["stale"]["abandoned"]:
        if s["name"] in by_name:
            flag(by_name[s["name"]], t("sug.reason.abandoned", year=(s["date"] or "")[:4]))
    for o in data["orphans"]:
        if o["name"] in by_name:
            flag(by_name[o["name"]], t("sug.reason.orphan"))
    hard_keys = set().union(*(_keys(m) for m in knowledge["duros"])) if knowledge["duros"] else set()
    if difficulty == "relajada":
        for m in knowledge["duros"]:
            for r in find_installed(m):
                flag(r, t("sug.reason.hard"))
    if pc == "justo":
        for r in inst:
            if r.mod.size >= HEAVY_BYTES and not r.is_library:
                flag(r, t("sug.reason.heavy", size=round(r.mod.size / 1e6)))
    if players == "servidor":
        for r in inst:
            if r.side == "client":
                flag(r, t("sug.reason.client_only"))

    # Mantener: lo que encaja con lo elegido (imprescindibles primero).
    chosen_cats = set().union(*(STYLE_CATS[s] for s in styles)) if styles else set()
    essential_of: dict[int, str] = {}
    for style in styles + ["base"]:
        for m in knowledge["esenciales"].get(style, []):
            for r in find_installed(m):
                essential_of.setdefault(id(r), style)
    keep_essential, keep_style = [], []
    for r in inst:
        if id(r) in remove or r.is_library:
            continue
        if id(r) in essential_of:
            style = essential_of[id(r)]
            reason = t("sug.reason.keep_base") if style == "base" else t("sug.reason.keep_essential", style=_style_label(style))
            keep_essential.append({"name": r.name, "reason": reason})
        elif r.categories and r.categories[0] in chosen_cats:
            style = next(s for s in styles if r.categories[0] in STYLE_CATS[s])
            keep_style.append({"name": r.name, "reason": t("sug.reason.keep_style", style=_style_label(style))})
    by_name_key = lambda k: k["name"].lower()  # noqa: E731
    keep = (sorted(keep_essential, key=by_name_key) + sorted(keep_style, key=by_name_key))[:KEEP_MAX]

    # Añadir: recomendados que no tienes, que existen para tu versión y no chocan con lo que tienes.
    order = list(styles) + ["base"] + ([players] if players in ("amigos", "servidor") else []) \
        + (["rendimiento"] if pc in ("justo", "normal") else [])
    add: list[dict] = []
    seen: set[str] = set()
    removed_ids = set(remove)
    incompat_keys = {}
    for pair in knowledge["incompatibilidades"]:
        incompat_keys[frozenset(_keys(pair["a"]))] = pair["b"]
        incompat_keys[frozenset(_keys(pair["b"]))] = pair["a"]
    for style in order:
        for m in knowledge["esenciales"].get(style, []):
            nk = name_key(m["nombre"])
            if nk in seen or find_installed(m):
                continue
            keys = _keys(m)
            if keys & hard_keys and difficulty != "reto":
                continue
            group = next((g for g in knowledge["solapamientos"] if any(_keys(x) & keys for x in g["mods"])), None)
            if group and (group["grupo"] in covered_groups or any(name_key(a["name"]) in
                                                                  {name_key(x["nombre"]) for x in group["mods"]} for a in add)):
                continue
            other = incompat_keys.get(frozenset(keys))
            if other and [r for r in find_installed(other) if id(r) not in removed_ids]:
                continue
            dep = Dep(CF, str(m["curseforge"])) if m.get("curseforge") else Dep(MR, m["modrinth"])
            found = finder.find(dep)
            if found is None and m.get("curseforge") and m.get("modrinth"):
                dep = Dep(MR, m["modrinth"])
                found = finder.find(dep)
            if found is None:
                continue  # no existe para la versión y el cargador del perfil
            seen.add(nk)
            add.append({"name": m["nombre"], "reason": t(f"sug.reason.style_{style}"), "source": dep.source, "id": dep.id})

    current = len(inst) - len(remove)
    if max_mods:
        add = add[:max(0, max_mods - current)]
    return {"remove": list(remove.values()), "keep": keep, "add": add,
            "over_limit": max(0, len(inst) - max_mods) if max_mods else 0}
