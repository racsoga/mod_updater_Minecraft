"""Tabla de resultados con rich."""

from __future__ import annotations

from collections import Counter

from rich.console import Console
from rich.markup import escape
from rich.table import Table

from .resolver import ACTUALIZABLE, AL_DIA, DESCONOCIDO, SOLO_MANUAL, Resolution

STATUS_STYLE = {
    ACTUALIZABLE: ("actualizable", "bold green"),
    AL_DIA: ("al día", "dim"),
    SOLO_MANUAL: ("solo manual", "yellow"),
    DESCONOCIDO: ("desconocido", "red"),
}
STATUS_ORDER = {ACTUALIZABLE: 0, SOLO_MANUAL: 1, DESCONOCIDO: 2, AL_DIA: 3}


def _channel(ch: str | None) -> str:
    return f" [magenta]({escape(ch)})[/]" if ch and ch != "release" else ""


def print_report(results: list[Resolution], console: Console | None = None, show_up_to_date: bool = True) -> None:
    console = console or Console()
    rows = sorted(results, key=lambda r: (STATUS_ORDER.get(r.status, 9), r.name.lower()))
    if not show_up_to_date:
        rows = [r for r in rows if r.status != AL_DIA]

    table = Table(title="Mods", show_lines=False, header_style="bold")
    table.add_column("Mod", overflow="fold")
    table.add_column("Versión actual", overflow="fold")
    table.add_column("→ Nueva", overflow="fold")
    table.add_column("Estado")
    table.add_column("Fuente")
    table.add_column("Notas", overflow="fold", style="dim")

    for r in rows:
        label, style = STATUS_STYLE.get(r.status, (r.status, ""))
        new = escape(r.new_version) + _channel(r.new_channel) if r.new_version else ""
        table.add_row(
            escape(r.name),
            escape(r.current_version or "?") + _channel(r.current_channel),
            f"[green]{new}[/]" if r.status == ACTUALIZABLE else new,
            f"[{style}]{label}[/]",
            r.source or "-",
            escape(r.note if r.status != DESCONOCIDO else f"{r.note}  ({r.mod.file_name})"),
        )
    console.print(table)

    counts = Counter(r.status for r in results)
    console.print(
        f"Total {len(results)}: "
        f"[bold green]{counts[ACTUALIZABLE]} actualizables[/], "
        f"{counts[AL_DIA]} al día, "
        f"[yellow]{counts[SOLO_MANUAL]} solo manual[/], "
        f"[red]{counts[DESCONOCIDO]} desconocidos[/]"
    )
