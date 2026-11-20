"""CLI del actualizador de mods.

Por defecto NO modifica nada (dry-run): solo escanea, consulta y muestra la tabla.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from rich.console import Console

from . import __version__
from .config import load_config
from .modrinth import ModrinthClient
from .net import ApiError
from .report import print_report
from .resolver import resolve_with_modrinth
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

    if args.apply:
        console.print("[yellow]--apply todavía no está implementado (hito 5). No se ha tocado nada.[/]")
        return 2

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

    client = ModrinthClient(cfg.user_agent)
    try:
        with console.status("Consultando Modrinth…"):
            results = resolve_with_modrinth(
                mods,
                client,
                loader=cfg.loader,
                game_version=cfg.minecraft_version,
                allow_beta=args.allow_beta,
            )
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
    console.print("[dim]Modo revisión: no se ha modificado ningún archivo.[/]")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
