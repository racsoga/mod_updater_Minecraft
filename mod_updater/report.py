"""Tabla de resultados con rich."""

from __future__ import annotations

from collections import Counter

from rich.console import Console
from rich.markup import escape
from rich.table import Table

from .deps import DepPlan
from .resolver import ACTUALIZABLE, AL_DIA, DESCARGA_MANUAL, INSTALL, NO_ENCONTRADO, Resolution

# Textos para el usuario (también los usará la interfaz gráfica).
STATUS_LABEL = {
    ACTUALIZABLE: "Actualizable",
    AL_DIA: "Al día",
    DESCARGA_MANUAL: "Descarga manual",
    NO_ENCONTRADO: "No encontrado",
}
STATUS_HELP = {
    AL_DIA: "Ya tienes la última versión.",
    ACTUALIZABLE: "Hay una versión nueva compatible.",
    DESCARGA_MANUAL: "Hay versión nueva, pero no se puede descargar automáticamente. Abre su página.",
    NO_ENCONTRADO: "No está en CurseForge ni en Modrinth. Se deja como está.",
}
NEW_DEP_LABEL = "Nueva dependencia"
STATUS_STYLE = {ACTUALIZABLE: "bold green", AL_DIA: "dim", DESCARGA_MANUAL: "yellow", NO_ENCONTRADO: "red"}
STATUS_ORDER = {ACTUALIZABLE: 0, DESCARGA_MANUAL: 1, NO_ENCONTRADO: 2, AL_DIA: 3}


def status_label(r: Resolution) -> str:
    return NEW_DEP_LABEL if r.kind == INSTALL else STATUS_LABEL.get(r.status, r.status)


def _channel(ch: str | None) -> str:
    return f" [magenta]({escape(ch)})[/]" if ch and ch != "release" else ""


def print_report(
    results: list[Resolution],
    console: Console | None = None,
    *,
    plan: DepPlan | None = None,
    show_up_to_date: bool = True,
) -> None:
    console = console or Console()
    rows = sorted(results, key=lambda r: (STATUS_ORDER.get(r.status, 9), r.name.lower()))
    if not show_up_to_date:
        rows = [r for r in rows if r.status != AL_DIA]
    installs = plan.installs if plan else []
    added = {id(r) for r in plan.added_updates} if plan else set()

    table = Table(title="Mods", header_style="bold")
    table.add_column("Mod", overflow="fold")
    table.add_column("Versión actual", overflow="fold")
    table.add_column("→ Nueva", overflow="fold")
    table.add_column("Estado")
    table.add_column("Fuente")
    table.add_column("Notas", overflow="fold", style="dim")

    for r in installs + rows:
        new = escape(r.new_version) + _channel(r.new_channel) if r.new_version else ""
        if r.kind == INSTALL:
            label, style = NEW_DEP_LABEL, "bold cyan"
            note = f"requerida por {', '.join(r.required_by)}"
        else:
            label, style = status_label(r), STATUS_STYLE.get(r.status, "")
            note = r.note
            if id(r) in added:
                note = "; ".join(filter(None, [f"requerida por {', '.join(r.required_by)}", note]))
            if r.status == NO_ENCONTRADO and r.mod:
                note = f"{note}  ({r.mod.file_name})"
        table.add_row(
            escape(r.name),
            "—" if r.kind == INSTALL else escape(r.current_version or "?") + _channel(r.current_channel),
            f"[green]{new}[/]" if r.status == ACTUALIZABLE else new,
            f"[{style}]{label}[/]",
            r.source or "-",
            escape(note),
        )
    console.print(table)

    counts = Counter(r.status for r in results)
    attention = counts[DESCARGA_MANUAL] + counts[NO_ENCONTRADO]
    parts = [f"[bold green]{counts[ACTUALIZABLE]} actualizaciones disponibles[/]", f"{counts[AL_DIA]} al día"]
    if installs:
        parts.append(f"[bold cyan]{len(installs)} dependencias nuevas[/]")
    if attention:
        parts.append(f"[yellow]{attention} requieren atención[/]")
    console.print(" · ".join(parts))

    if plan:
        for r in installs:
            console.print(
                f"[cyan]Se instalará {escape(r.name)} {escape(r.new_version or '')} "
                f"(requerida por {escape(', '.join(r.required_by))}).[/]"
            )
        for r in plan.blocked:
            console.print(f"[yellow]No se actualizará {escape(r.name)}: {escape(r.note)}[/]")
        for msg in plan.broken:
            console.print(f"[red]Tu carpeta ya tiene un problema: {escape(msg)}[/]")
        for msg in plan.ignored:
            console.print(f"[dim]Aviso: {escape(msg)}.[/]")
