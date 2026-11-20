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
from .downloader import apply_updates, backup_root, updatable
from .curseforge import CurseForgeAuthError, CurseForgeClient
from .modrinth import ModrinthClient
from .net import ApiError
from .report import print_report
from .resolver import resolve_all
from .scanner import scan_folder


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
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return p


def _matches(filters: list[str], *texts: str | None) -> bool:
    hay = " ".join(t.lower() for t in texts if t)
    return any(f in hay for f in filters)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    console = Console()
    cfg = load_config(args.config)
    if args.mods_dir:
        cfg.mods_dir = args.mods_dir

    console.print(f"Carpeta de mods: [bold]{cfg.mods_dir}[/]  (MC {cfg.minecraft_version}, {cfg.loader})")
    try:
        with console.status("Calculando hashes…") as status:
            mods = scan_folder(
                cfg.mods_dir,
                cache_path=None if args.no_cache else cfg.scan_cache,
                progress=lambda path: status.update(f"Calculando hashes: {path.name}"),
            )
    except FileNotFoundError as exc:
        console.print(f"[red]{exc}[/]")
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
                console.print(f"[yellow]{exc}. Se usa solo Modrinth.[/]")
                curseforge = None
                results = resolve_all(mods, curseforge=None, modrinth=modrinth, **opts)
    except ApiError as exc:
        console.print(f"[red]Error de red: {exc}[/]")
        return 1

    if args.only:
        filters = [f.strip().lower() for f in args.only.split(",") if f.strip()]
        results = [
            r for r in results
            if _matches(filters, r.project_name, r.mod.mod_id, r.mod.mod_name, r.mod.file_name)
        ]

    print_report(results, console, show_up_to_date=not args.hide_up_to_date)
    if not args.apply:
        console.print("[dim]Modo revisión: no se ha modificado ningún archivo. Usa --apply para actualizar.[/]")
        return 0
    return run_apply(results, cfg.mods_dir, modrinth, curseforge, console, assume_yes=args.yes)


def run_apply(results, mods_dir, modrinth, curseforge, console: Console, *, assume_yes: bool) -> int:
    to_apply, skipped = updatable(results)
    for r in skipped:
        console.print(f"[yellow]Se salta {escape(r.name)}: el mismo mod está duplicado en la carpeta.[/]")
    if not to_apply:
        console.print("Nada que actualizar.")
        return 0

    console.print(
        f"\nSe actualizarán [bold]{len(to_apply)}[/] mods. Los jar viejos se moverán (no se borran) a "
        f"[bold]{escape(str(backup_root(mods_dir) / '<fecha>'))}[/]."
    )
    console.print("[yellow]Cierra Minecraft antes de continuar.[/]")
    if not assume_yes:
        answer = console.input("¿Continuar? [s/N] ").strip().lower()
        if answer not in ("s", "si", "sí", "y", "yes"):
            console.print("Cancelado. No se ha modificado nada.")
            return 0

    with console.status("Descargando…") as status:
        backup_dir, outcomes = apply_updates(
            to_apply,
            mods_dir,
            modrinth_session=modrinth.session,
            curseforge_session=curseforge.session if curseforge else None,
            progress=lambda r: status.update(f"Descargando {escape(r.name)}…"),
        )

    ok = [o for o in outcomes if o.ok]
    failed = [o for o in outcomes if not o.ok]
    for o in failed:
        console.print(f"[red]✗ {escape(o.resolution.name)}: {escape(o.message)}[/] (el jar viejo sigue en su sitio)")
    console.print(f"[bold green]{len(ok)} actualizados[/], [red]{len(failed)} fallidos[/].")
    console.print(f"Backup y registro de cambios en: [bold]{escape(str(backup_dir))}[/]")
    return 1 if failed else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
