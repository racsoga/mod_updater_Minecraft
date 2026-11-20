"""CLI del actualizador de mods.

Por defecto NO modifica nada (dry-run): solo escanea, consulta y muestra la tabla.
Los textos están en locales/<idioma>.json (`--lang es|en|ca`, por defecto el de Windows).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from rich.console import Console
from rich.markup import escape

from . import __version__, i18n
from .config import load_config
from .curseforge import CurseForgeAuthError, CurseForgeClient
from .deps import DependencyFinder, DepPlan, plan_with_dependencies
from .downloader import apply_updates, backup_root, prune_backups, updatable
from .i18n import t
from .modrinth import ModrinthClient
from .net import ApiError
from .procs import minecraft_running
from .report import print_report
from .resolver import INSTALL, resolve_all
from .scanner import scan_folder

# Se aceptan en cualquier idioma: s/si/sí (español, català), y/yes (English).
YES_ANSWERS = {"s", "si", "sí", "y", "yes"}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="mod_updater", description=t("cli.description"))
    p.add_argument("--mods-dir", type=Path, help=t("cli.help_mods_dir"))
    p.add_argument("--config", type=Path, help=t("cli.help_config"))
    p.add_argument("--allow-beta", action="store_true", help=t("cli.help_allow_beta"))
    p.add_argument("--only", help=t("cli.help_only"))
    p.add_argument("--hide-up-to-date", action="store_true", help=t("cli.help_hide"))
    p.add_argument("--no-cache", action="store_true", help=t("cli.help_no_cache"))
    p.add_argument("--apply", action="store_true", help=t("cli.help_apply"))
    p.add_argument("--yes", action="store_true", help=t("cli.help_yes"))
    p.add_argument("--keep-backups", type=int, metavar="N", help=t("cli.help_keep"))
    p.add_argument("--lang", choices=("auto", *i18n.SUPPORTED), help=t("cli.help_lang"))
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return p


def _early_language(argv: list[str], config_path: Path | None) -> None:
    """El idioma hace falta antes de construir la ayuda: --lang, si no config.toml, si no Windows."""
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--lang")
    pre.add_argument("--config", type=Path)
    known, _ = pre.parse_known_args(argv)
    lang = known.lang or load_config(known.config or config_path).language
    i18n.set_language(lang)


def is_yes(answer: str) -> bool:
    """Respuesta a una pregunta [S/n] o [Y/n]: Intro (vacío) cuenta como sí."""
    a = answer.strip().lower()
    return a == "" or a in YES_ANSWERS


def plan_summary(n_update: int, n_install: int) -> str:
    """'Se actualizarán 3 mods y se instalará 1 dependencia nueva'."""
    parts = []
    if n_update:
        parts.append(t("cli.plan_update", count=n_update))
    if n_install:
        parts.append(t("cli.plan_install", count=n_install))
    text = t("cli.and").join(parts)
    return text[:1].upper() + text[1:]


def _matches(filters: list[str], *texts: str | None) -> bool:
    hay = " ".join(x.lower() for x in texts if x)
    return any(f in hay for f in filters)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    _early_language(argv, None)
    args = build_parser().parse_args(argv)
    console = Console()
    cfg = load_config(args.config)
    if args.mods_dir:
        cfg.mods_dir = args.mods_dir
    if args.keep_backups is not None:
        cfg.backups_to_keep = args.keep_backups

    console.print(t("cli.header", path=escape(str(cfg.mods_dir)), version=cfg.minecraft_version, loader=cfg.loader))
    try:
        with console.status(t("cli.hashing")) as status:
            mods = scan_folder(
                cfg.mods_dir,
                cache_path=None if args.no_cache else cfg.scan_cache,
                progress=lambda path: status.update(t("cli.hashing_file", name=path.name)),
            )
    except FileNotFoundError as exc:
        console.print(f"[red]{escape(str(exc))}[/]")
        return 1
    console.print(t("cli.jars_found", count=len(mods)))
    if not mods:
        return 0

    modrinth = ModrinthClient(cfg.user_agent)
    curseforge = CurseForgeClient(cfg.cf_api_key) if cfg.cf_api_key else None
    if curseforge is None:
        console.print(f"[yellow]{t('cli.no_key')}[/]")
    opts = dict(loader=cfg.loader, game_version=cfg.minecraft_version, allow_beta=args.allow_beta)
    try:
        with console.status(t("cli.querying")):
            try:
                results = resolve_all(mods, curseforge=curseforge, modrinth=modrinth, **opts)
            except CurseForgeAuthError as exc:
                console.print(f"[yellow]{escape(t('cli.key_rejected_fallback', error=exc))}[/]")
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

        with console.status(t("cli.checking_deps")):
            finder = DependencyFinder(curseforge, modrinth, **opts)
            plan = plan_with_dependencies(results, selected, finder)
    except ApiError as exc:
        console.print(f"[red]{escape(t('cli.network_error', error=exc))}[/]")
        return 1

    print_report(shown, console, plan=plan, show_up_to_date=not args.hide_up_to_date)
    for r in skipped:
        console.print(f"[yellow]{escape(t('cli.skipped_duplicate', name=r.name))}[/]")

    if not args.apply:
        console.print(f"[dim]{t('cli.dry_run')}[/]")
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
        console.print(t("cli.nothing"))
        return 0

    pids = running(mods_dir.parent)
    if pids:
        console.print(f"[bold red]{escape(t('cli.minecraft_open', pids=', '.join(map(str, pids))))}[/]")
        return 1

    n_install = sum(1 for r in items if r.kind == INSTALL)
    n_update = len(items) - n_install
    console.print("\n" + plan_summary(n_update, n_install) + ".")
    if n_update:
        console.print(t("cli.backup_where", path=escape(str(backup_root(mods_dir) / t("cli.date_placeholder")))))
    if not assume_yes:
        # escape(): para rich, "[S/n]" sería una etiqueta de formato y desaparecería.
        answer = (ask or console.input)(escape(t("cli.confirm")) + " ")
        if not is_yes(answer):
            console.print(t("cli.cancelled"))
            return 0

    with console.status(t("cli.downloading")) as status:
        backup_dir, outcomes = apply_updates(
            items,
            mods_dir,
            modrinth_session=modrinth.session,
            curseforge_session=curseforge.session if curseforge else None,
            progress=lambda r: status.update(t("cli.downloading_mod", name=escape(r.name))),
        )

    ok = [o for o in outcomes if o.ok]
    failed = [o for o in outcomes if not o.ok]
    for o in failed:
        console.print(f"[red]{escape(t('cli.failed_line', name=o.resolution.name, message=o.message))}[/]")
    installed = sum(1 for o in ok if o.resolution.kind == INSTALL)
    console.print(t("cli.result", updated=len(ok) - installed, installed=installed, failed=len(failed)))
    console.print(t("cli.backup_at", path=escape(str(backup_dir))))
    if ok:
        removed = prune_backups(mods_dir, keep_backups)
        if removed:
            console.print(f"[dim]{t('cli.pruned', count=len(removed), keep=keep_backups)}[/]")
    return 1 if failed else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
