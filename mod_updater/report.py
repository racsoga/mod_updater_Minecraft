"""Tabla de resultados con rich (CLI). Textos en locales/<idioma>.json."""

from __future__ import annotations

from collections import Counter

from rich.console import Console
from rich.markup import escape
from rich.table import Table

from .deps import DepPlan
from .i18n import t
from .resolver import ACTUALIZABLE, AL_DIA, DESCARGA_MANUAL, INSTALL, NO_ENCONTRADO, Resolution

STATUS_KEY = {ACTUALIZABLE: "up", AL_DIA: "ok", DESCARGA_MANUAL: "manual", NO_ENCONTRADO: "missing"}
STATUS_STYLE = {ACTUALIZABLE: "bold green", AL_DIA: "dim", DESCARGA_MANUAL: "yellow", NO_ENCONTRADO: "red"}
STATUS_ORDER = {ACTUALIZABLE: 0, DESCARGA_MANUAL: 1, NO_ENCONTRADO: 2, AL_DIA: 3}


def status_label(r: Resolution) -> str:
    """Texto visible del estado ("Al día", "Nueva dependencia"...)."""
    return t("status.dep") if r.kind == INSTALL else t(f"status.{STATUS_KEY.get(r.status, 'missing')}")


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

    table = Table(title=t("cli.table_title"), header_style="bold")
    for col in ("cli.col_mod", "cli.col_current", "cli.col_new", "cli.col_status", "cli.col_source"):
        table.add_column(t(col), overflow="fold")
    table.add_column(t("cli.col_notes"), overflow="fold", style="dim")

    for r in installs + rows:
        new = escape(r.new_version) + _channel(r.new_channel) if r.new_version else ""
        if r.kind == INSTALL:
            style = "bold cyan"
            note = t("cli.required_by", names=", ".join(r.required_by))
        else:
            style = STATUS_STYLE.get(r.status, "")
            note = r.note
            if id(r) in added:
                note = "; ".join(filter(None, [t("cli.required_by", names=", ".join(r.required_by)), note]))
            if r.status == NO_ENCONTRADO and r.mod:
                note = f"{note}  ({r.mod.file_name})"
        table.add_row(
            escape(r.name),
            "—" if r.kind == INSTALL else escape(r.current_version or "?") + _channel(r.current_channel),
            f"[green]{new}[/]" if r.status == ACTUALIZABLE else new,
            f"[{style}]{status_label(r)}[/]",
            r.source or "-",
            escape(note),
        )
    console.print(table)

    counts = Counter(r.status for r in results)
    attention = counts[DESCARGA_MANUAL] + counts[NO_ENCONTRADO]
    parts = [
        f"[bold green]{t('cli.sum_updates', count=counts[ACTUALIZABLE])}[/]",
        t("cli.sum_ok", count=counts[AL_DIA]),
    ]
    if installs:
        parts.append(f"[bold cyan]{t('cli.sum_deps', count=len(installs))}[/]")
    if attention:
        parts.append(f"[yellow]{t('cli.sum_attention', count=attention)}[/]")
    console.print(" · ".join(parts))

    if plan:
        for r in installs:
            console.print(f"[cyan]{escape(t('cli.will_install', name=r.name, version=r.new_version or '', names=', '.join(r.required_by)))}[/]")
        for r in plan.blocked:
            console.print(f"[yellow]{escape(t('cli.blocked', name=r.name, note=r.note))}[/]")
        for b in plan.broken:
            console.print(f"[red]{escape(t('cli.broken', name=b.res.name, reason=b.reason))}[/]")
        for msg in plan.ignored:
            console.print(f"[dim]{escape(t('cli.notice', message=msg))}[/]")
