"""CLI del actualizador de mods.

Por defecto NO modifica nada (dry-run): solo escanea, consulta y muestra la tabla.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from rich.console import Console
from rich.markup import escape

from . import __version__
from .config import load_config
from .curseforge import CurseForgeAuthError, CurseForgeClient
from .deps import DependencyFinder, DepPlan, plan_with_dependencies
from .downloader import apply_updates, backup_root, prune_backups, updatable
from .modrinth import ModrinthClient
from .net import ApiError
from .procs import minecraft_running
from .report import print_report
from .resolver import INSTALL, resolve_all
from .scanner import scan_folder

YES_ANSWERS = {"s", "si", "sí", "y", "yes"}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="mod_updater", description="Actualizador de mods de Minecraft (NeoForge).")
    p.add_argument("--mods-dir", type=Path, help="carpeta de mods (por defecto %%APPDATA%%\\.minecraft\\mods)")
    p.add_argument("--config", type=Path, help="ruta a config.toml")
    p.add_argument("--allow-beta", action="store_true", help="proponer betas aunque el actual sea release")
    p.add_argument("--only", help="filtrar por nombre, lista separada por comas (ej. create,jei)")
    p.add_argument("--hide-up-to-date", action="store_true", help="no listar los mods al día")
    p.add_argument("--no-cache", action="store_true", help="recalcular todos los hashes")
    p.add_argument("--apply", action="store_true", help="descargar y aplicar las actualizaciones")
    p.add_argument("--yes", action="store_true", help="no pedir confirmación con --apply")
    p.add_argument("--keep-backups", type=int, metavar="N", help="backups a conservar (por defecto el de config, 1)")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return p


def is_yes(answer: str) -> bool:
    """Respuesta a una pregunta [S/n]: Intro (vacío) cuenta como sí."""
    a = answer.strip().lower()
    return a == "" or a in YES_ANSWERS


def plan_summary(n_update: int, n_install: int) -> str:
    """'Se actualizarán 3 mods y se instalará 1 dependencia nueva'."""
    parts = []
    if n_update:
        parts.append(f"se actualizará 1 mod" if n_update == 1 else f"se actualizarán {n_update} mods")
    if n_install:
        parts.append(
            "se instalará 1 dependencia nueva" if n_install == 1 else f"se instalarán {n_install} dependencias nuevas"
        )
    text = " y ".join(parts)
    return text[:1].upper() + text[1:]


def _matches(filters: list[str], *texts: str | None) -> bool:
    hay = " ".join(t.lower() for t in texts if t)
    return any(f in hay for f in filters)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    console = Console()
    cfg = load_config(args.config)
    if args.mods_dir:
        cfg.mods_dir = args.mods_dir
    if args.keep_backups is not None:
        cfg.backups_to_keep = args.keep_backups

    console.print(f"Carpeta de mods: [bold]{escape(str(cfg.mods_dir))}[/]  (MC {cfg.minecraft_version}, {cfg.loader})")
    try:
        with console.status("Calculando hashes…") as status:
            mods = scan_folder(
                cfg.mods_dir,
                cache_path=None if args.no_cache else cfg.scan_cache,
                progress=lambda path: status.update(f"Calculando hashes: {path.name}"),
            )
    except FileNotFoundError as exc:
        console.print(f"[red]{escape(str(exc))}[/]")
        return 1
    console.print(f"{len(mods)} archivos .jar encontrados.")
    if not mods:
        return 0

    modrinth = ModrinthClient(cfg.user_agent)
    curseforge = CurseForgeClient(cfg.cf_api_key) if cfg.cf_api_key else None
    if curseforge is None:
        console.print("[yellow]Sin CF_API_KEY en .env: solo se consultará Modrinth.[/]")
    opts = dict(loader=cfg.loader, game_version=cfg.minecraft_version, allow_beta=args.allow_beta)
    try:
        with console.status("Consultando CurseForge y Modrinth…"):
            try:
                results = resolve_all(mods, curseforge=curseforge, modrinth=modrinth, **opts)
            except CurseForgeAuthError as exc:
                console.print(f"[yellow]{escape(str(exc))}. Se usa solo Modrinth.[/]")
                curseforge = None
                results = resolve_all(mods, curseforge=None, modrinth=modrinth, **opts)

        shown = results
        if args.only:
            filters = [f.strip().lower() for f in args.only.split(",") if f.strip()]
            shown = [
                r for r in results
                if _matches(filters, r.project_name, r.mod.mod_id, r.mod.mod_name, r.mod.file_name)
            ]
        selected, skipped = updatable(shown)

        with console.status("Comprobando dependencias…"):
            finder = DependencyFinder(curseforge, modrinth, **opts)
            plan = plan_with_dependencies(results, selected, finder)
    except ApiError as exc:
        console.print(f"[red]Error de red: {escape(str(exc))}[/]")
        return 1

    print_report(shown, console, plan=plan, show_up_to_date=not args.hide_up_to_date)
    for r in skipped:
        console.print(f"[yellow]Se salta {escape(r.name)}: el mismo mod está duplicado en la carpeta.[/]")

    if not args.apply:
        console.print("[dim]Modo revisión: no se ha modificado ningún archivo. Usa --apply para actualizar.[/]")
        return 0
    return run_apply(plan, cfg.mods_dir, modrinth, curseforge, console,
                     assume_yes=args.yes, keep_backups=cfg.backups_to_keep)


def run_apply(
    plan: DepPlan,
    mods_dir: Path,
    modrinth: ModrinthClient,
    curseforge: CurseForgeClient | None,
    console: Console,
    *,
    assume_yes: bool,
    keep_backups: int,
    running=minecraft_running,
    ask=None,
) -> int:
    items = plan.items
    if not items:
        console.print("Nada que actualizar.")
        return 0

    pids = running(mods_dir.parent)
    if pids:
        console.print(
            f"[bold red]Minecraft está abierto con esta carpeta (proceso {', '.join(map(str, pids))}).[/] "
            "Ciérralo y vuelve a intentarlo. No se ha modificado nada."
        )
        return 1

    n_install = sum(1 for r in items if r.kind == INSTALL)
    n_update = len(items) - n_install
    console.print("\n" + plan_summary(n_update, n_install) + ".")
    if n_update:
        console.print(
            f"Los jar viejos se moverán (no se borran) a [bold]{escape(str(backup_root(mods_dir) / '<fecha>'))}[/]."
        )
    if not assume_yes:
        answer = (ask or console.input)("¿Continuar? [S/n] ")
        if not is_yes(answer):
            console.print("Cancelado. No se ha modificado nada.")
            return 0

    with console.status("Descargando…") as status:
        backup_dir, outcomes = apply_updates(
            items,
            mods_dir,
            modrinth_session=modrinth.session,
            curseforge_session=curseforge.session if curseforge else None,
            progress=lambda r: status.update(f"Descargando {escape(r.name)}…"),
        )

    ok = [o for o in outcomes if o.ok]
    failed = [o for o in outcomes if not o.ok]
    for o in failed:
        console.print(f"[red]✗ {escape(o.resolution.name)}: {escape(o.message)}[/] (sin cambios)")
    installed = sum(1 for o in ok if o.resolution.kind == INSTALL)
    console.print(
        f"[bold green]{len(ok) - installed} actualizados[/], [cyan]{installed} instalados[/], "
        f"[red]{len(failed)} fallidos[/]."
    )
    console.print(f"Backup y registro de cambios en: [bold]{escape(str(backup_dir))}[/]")
    if ok:
        removed = prune_backups(mods_dir, keep_backups)
        if removed:
            console.print(f"[dim]Se han borrado {len(removed)} backups antiguos (se guardan los últimos {keep_backups}).[/]")
    return 1 if failed else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
