"""Animus CLI — Leap of Faith into your memories."""

from __future__ import annotations

import asyncio
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

# Ensure UTF-8 stdout/stderr on Windows so emoji/box-drawing glyphs in the
# Rich output don't crash the CLI on the default cp1252 console codepage
# (e.g. ``UnicodeEncodeError: 'charmap' codec can't encode '\U0001f985'``).
if sys.platform == "win32":
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except Exception:
            pass

import typer
from rich.console import Console
from rich.table import Table

from .config import AnimusConfig

app = typer.Typer(
    name="animus",
    help="🦅 Animus — AI Memory Synchronization Network",
    no_args_is_help=True,
)
console = Console()


def _setup_logging(verbose: bool = False, log_file: Optional[Path] = None) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    fmt = "%(asctime)s [%(name)s] %(levelname)s: %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"

    handlers: list[logging.Handler] = []
    if log_file is not None:
        # Rotate at ~5MB, keep last 5 — plenty for "what did the daemon do
        # last week" spelunking, never enough to fill a disk.
        log_file = Path(log_file).expanduser()
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(
            RotatingFileHandler(
                log_file, maxBytes=5_000_000, backupCount=5, encoding="utf-8",
            )
        )
    else:
        handlers.append(logging.StreamHandler())

    logging.basicConfig(
        level=level,
        format=fmt,
        datefmt=datefmt,
        handlers=handlers,
        force=True,
    )


# ═══════════════════════════════════════════════════════════════
#  Init / Config
# ═══════════════════════════════════════════════════════════════

@app.command()
def init():
    """Initialize Animus on this machine — enter the Animus for the first time."""
    config = AnimusConfig.load()
    config.save()
    console.print("\n[bold green]⟁[/] Animus initialized")
    console.print(f"  Node ID:   [cyan]{config.node_id}[/]")
    console.print(f"  Node Name: [cyan]{config.node_name}[/]")
    console.print(f"  Data dir:  [dim]{config.data_dir}[/]")
    console.print(f"  Config:    [dim]{config.config_path}[/]")
    console.print("\n  Run [bold]animus collect[/] to start gathering memories.")


@app.command()
def config_show():
    """Show current configuration."""
    cfg = AnimusConfig.load()
    table = Table(title="Animus Configuration")
    table.add_column("Key", style="cyan")
    table.add_column("Value")
    for key, val in cfg.model_dump().items():
        display = str(val)
        if "secret" in key.lower() or "token" in key.lower() or "key" in key.lower():
            display = "***" if val else "(empty)"
        table.add_row(key, display)
    console.print(table)


@app.command()
def config_set(key: str, value: str):
    """Set a configuration value."""
    cfg = AnimusConfig.load()
    if not hasattr(cfg, key):
        console.print(f"[red]Unknown config key:[/] {key}")
        raise typer.Exit(1)
    current = getattr(cfg, key)
    if isinstance(current, bool):
        setattr(cfg, key, value.lower() in ("true", "1", "yes"))
    elif isinstance(current, int):
        setattr(cfg, key, int(value))
    elif isinstance(current, Path):
        setattr(cfg, key, Path(value))
    else:
        setattr(cfg, key, value)
    cfg.save()
    console.print(f"[green]✓[/] {key} = {value}")


# ═══════════════════════════════════════════════════════════════
#  Collect
# ═══════════════════════════════════════════════════════════════

obsidian_app = typer.Typer(
    name="obsidian",
    help="Manage the experimental, opt-in Obsidian knowledge layer.",
    no_args_is_help=True,
)
app.add_typer(obsidian_app, name="obsidian")


@obsidian_app.command("vault-add")
def obsidian_vault_add(
    name: str,
    path: Path,
    enable_collection: bool = typer.Option(False, "--enable-collection"),
    allow_export: bool = typer.Option(False, "--allow-export"),
):
    """Register a local vault; collection and export remain explicit opt-ins."""
    from .config import ObsidianVaultConfig

    cfg = AnimusConfig.load()
    root = path.expanduser().resolve()
    if not root.is_dir():
        console.print(f"[red]Vault path does not exist or is not a directory:[/] {root}")
        raise typer.Exit(1)
    if any(v.name == name or v.path.expanduser().resolve() == root for v in cfg.obsidian_vaults):
        console.print("[red]A vault with this name or path is already configured.[/]")
        raise typer.Exit(1)
    cfg.obsidian_vaults.append(ObsidianVaultConfig(
        name=name, path=root, export_enabled=allow_export,
    ))
    if enable_collection:
        cfg.collect_obsidian = True
    cfg.save()
    from .obsidian import initialize_vault

    initialize_vault(cfg.obsidian_vaults[-1])
    console.print(f"[green]OK[/] Vault '{name}' registered at {root}")
    console.print(f"  collection={cfg.collect_obsidian} export={allow_export}")


@obsidian_app.command("vault-remove")
def obsidian_vault_remove(name: str):
    """Remove vault configuration without deleting notes or indexed history."""
    cfg = AnimusConfig.load()
    remaining = [vault for vault in cfg.obsidian_vaults if vault.name != name]
    if len(remaining) == len(cfg.obsidian_vaults):
        console.print(f"[red]Unknown vault:[/] {name}")
        raise typer.Exit(1)
    cfg.obsidian_vaults = remaining
    cfg.save()
    console.print(f"[green]OK[/] Vault '{name}' removed; files were preserved.")


@obsidian_app.command("vault-set")
def obsidian_vault_set(
    name: str,
    enabled: Optional[bool] = typer.Option(None, "--enabled/--disabled"),
    export: Optional[bool] = typer.Option(None, "--export/--no-export"),
):
    """Enable/disable one vault and its export permission."""
    cfg = AnimusConfig.load()
    vault = next((item for item in cfg.obsidian_vaults if item.name == name), None)
    if vault is None:
        console.print(f"[red]Unknown vault:[/] {name}")
        raise typer.Exit(1)
    if enabled is not None:
        vault.enabled = enabled
    if export is not None:
        vault.export_enabled = export
    cfg.save()
    console.print(f"[green]OK[/] {name}: enabled={vault.enabled} export={vault.export_enabled}")


@obsidian_app.command("status")
def obsidian_status():
    """Show vault availability, permissions, and indexed note counts."""
    from .collector.models import MemoryType
    from .indexer.engine import IndexEngine

    cfg = AnimusConfig.load()
    engine = IndexEngine(cfg.db_path)
    table = Table(title=f"Obsidian (collection={'on' if cfg.collect_obsidian else 'off'})")
    for heading in ("Vault", "Path", "Available", "Collect", "Export", "Indexed"):
        table.add_column(heading)
    for vault in cfg.obsidian_vaults:
        count = engine.conn.execute(
            "SELECT COUNT(*) FROM memories WHERE type = ? AND json_extract(metadata, '$.vault') = ? "
            "AND COALESCE(json_extract(metadata, '$.missing'), 0) = 0",
            (MemoryType.OBSIDIAN_NOTE.value, vault.name),
        ).fetchone()[0]
        table.add_row(
            vault.name, str(vault.path), str(vault.path.expanduser().is_dir()),
            str(cfg.collect_obsidian and vault.enabled), str(vault.export_enabled), str(count),
        )
    console.print(table)
    engine.close()


@obsidian_app.command("collect")
def obsidian_collect():
    """Collect only configured Obsidian vaults."""
    from .collector.obsidian import ObsidianCollector
    from .indexer.engine import IndexEngine

    cfg = AnimusConfig.load()
    collector = ObsidianCollector(cfg)
    engine = IndexEngine(cfg.db_path)
    memories = collector.collect_all()
    changed = engine.index_batch(memories)
    missing = sum(
        engine.mark_obsidian_missing(vault, cfg.node_id, active)
        for vault, active in collector.seen_by_vault.items()
    )
    engine.close()
    console.print(
        f"Found={len(memories)} new/updated={changed} missing={missing} "
        f"warnings={len(collector.diagnostics)}"
    )


def _obsidian_selection(engine, memory_ids: Optional[list[str]], query: str,
                        mem_type: str, session: str, tags: str, limit: int) -> list[str]:
    selected = list(memory_ids or [])
    if query or mem_type or session or tags:
        rows = engine.select_memories(
            query=query, mem_type=mem_type or None, session=session,
            tags=[tag.strip() for tag in tags.split(",") if tag.strip()] or None,
            limit=limit,
        )
        selected.extend(row["id"] for row in rows)
    return list(dict.fromkeys(selected))


@obsidian_app.command("export")
def obsidian_export(
    vault: str = typer.Option(..., "--vault"),
    memory_ids: Optional[list[str]] = typer.Option(None, "--id"),
    query: str = typer.Option("", "--query"),
    mem_type: str = typer.Option("", "--type"),
    session: str = typer.Option("", "--session"),
    tags: str = typer.Option("", "--tags", help="Comma-separated required tags"),
    limit: int = typer.Option(50, "--limit"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    folder: str = typer.Option(".animus/exported", "--folder"),
):
    """Export memories selected by ID, query, type, session, or tags."""
    from .indexer.engine import IndexEngine
    from .obsidian import ObsidianManager

    cfg = AnimusConfig.load()
    engine = IndexEngine(cfg.db_path)
    selected = _obsidian_selection(engine, memory_ids, query, mem_type, session, tags, limit)
    if not selected:
        console.print("[red]No memories selected.[/]")
        engine.close()
        raise typer.Exit(1)
    try:
        result = ObsidianManager(cfg, engine).export(
            vault, selected, dry_run=dry_run, destination_folder=folder
        )
        console.print_json(data=result.to_dict())
    finally:
        engine.close()


@obsidian_app.command("organize")
def obsidian_organize(
    vault: str = typer.Option(..., "--vault"),
    memory_ids: Optional[list[str]] = typer.Option(None, "--id"),
    query: str = typer.Option("", "--query"),
    apply_changes: bool = typer.Option(False, "--apply"),
    approve: bool = typer.Option(False, "--approve"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    actor: str = typer.Option("cli-agent", "--actor"),
    reason: str = typer.Option("organize memories", "--reason"),
):
    """Propose first, or apply an explicitly approved managed organization."""
    from .indexer.engine import IndexEngine
    from .obsidian import ObsidianManager

    cfg = AnimusConfig.load()
    engine = IndexEngine(cfg.db_path)
    selected = _obsidian_selection(engine, memory_ids, query, "", "", "", 50)
    manager = ObsidianManager(cfg, engine)
    try:
        proposal = manager.propose_organization(vault, selected, actor=actor, reason=reason)
        if not apply_changes:
            console.print_json(data=proposal)
            return
        result = manager.apply_organization(proposal, approved=approve, dry_run=dry_run)
        console.print_json(data={"request_id": proposal["request_id"], **result.to_dict()})
    finally:
        engine.close()


@obsidian_app.command("rollback")
def obsidian_rollback(vault: str = typer.Option(..., "--vault")):
    """Restore the last updated managed note from its audit backup."""
    from .indexer.engine import IndexEngine
    from .obsidian import ObsidianManager

    cfg = AnimusConfig.load()
    engine = IndexEngine(cfg.db_path)
    try:
        path = ObsidianManager(cfg, engine).rollback_last(vault)
        console.print(f"[green]OK[/] Restored {path}")
    finally:
        engine.close()


@obsidian_app.command("catalog")
def obsidian_catalog(
    vault: str = typer.Option(..., "--vault"),
    install_style: bool = typer.Option(False, "--install-style"),
):
    """Build project maps, dashboard, Canvas, guide, and curated metadata."""
    from .indexer.engine import IndexEngine
    from .obsidian import ObsidianManager

    cfg = AnimusConfig.load()
    engine = IndexEngine(cfg.db_path)
    try:
        console.print_json(
            data=ObsidianManager(cfg, engine).build_catalog(
                vault, install_style=install_style
            )
        )
    finally:
        engine.close()


@obsidian_app.command("dataset")
def obsidian_dataset(
    vault: str = typer.Option(..., "--vault"),
    kind: str = typer.Option("rag", "--kind", help="rag or sft"),
    apply: bool = typer.Option(False, "--apply", help="Write JSONL and manifest"),
    include_internal: bool = typer.Option(False, "--include-internal"),
):
    """Build a gated RAG or supervised fine-tuning dataset."""
    from .indexer.engine import IndexEngine
    from .obsidian import ObsidianManager

    cfg = AnimusConfig.load()
    engine = IndexEngine(cfg.db_path)
    try:
        console.print_json(
            data=ObsidianManager(cfg, engine).export_dataset(
                vault, kind=kind, dry_run=not apply,
                include_internal=include_internal, actor="cli-dataset-curator",
            )
        )
    except (ValueError, PermissionError) as exc:
        console.print(f"[red]Error:[/] {exc}")
        raise typer.Exit(1)
    finally:
        engine.close()


@obsidian_app.command("search")
def obsidian_search(
    query: str = typer.Argument(...),
    vault: str = typer.Option(..., "--vault"),
    project: str = typer.Option("", "--project"),
    include_candidates: bool = typer.Option(False, "--include-candidates"),
    limit: int = typer.Option(10, "--limit", min=1, max=50),
):
    """Search verified knowledge, optionally including flagged candidates."""
    from .indexer.engine import IndexEngine
    from .obsidian import ObsidianManager

    cfg = AnimusConfig.load()
    engine = IndexEngine(cfg.db_path)
    try:
        console.print_json(
            data=ObsidianManager(cfg, engine).search_knowledge(
                vault, query, project=project,
                include_candidates=include_candidates, limit=limit,
            )
        )
    except (ValueError, PermissionError) as exc:
        console.print(f"[red]Error:[/] {exc}")
        raise typer.Exit(1)
    finally:
        engine.close()


@app.command()
def collect(verbose: bool = False):
    """Collect memories from Copilot + Copilot CLI + Claude Code + Antigravity interactions — Desynchronize."""
    _setup_logging(verbose)
    config = AnimusConfig.load()

    from .collector.antigravity import AntigravityCollector
    from .collector.claude import ClaudeCollector
    from .collector.copilot import CopilotCollector
    from .collector.copilot_cli import CopilotCliCollector
    from .collector.obsidian import ObsidianCollector
    from .indexer.engine import IndexEngine

    collector = CopilotCollector(config)
    claude_collector = ClaudeCollector(config)
    antigravity_collector = AntigravityCollector(config)
    copilot_cli_collector = CopilotCliCollector(config)
    obsidian_collector = ObsidianCollector(config)
    engine = IndexEngine(config.db_path)

    console.print("[bold]⟁ Entering the Animus...[/]\n")

    memories = collector.collect_all()
    memories.extend(claude_collector.collect_all())
    memories.extend(antigravity_collector.collect_all())
    memories.extend(copilot_cli_collector.collect_all())
    memories.extend(obsidian_collector.collect_all())
    new_count = engine.index_batch(memories)
    missing_count = sum(
        engine.mark_obsidian_missing(vault, config.node_id, active_ids)
        for vault, active_ids in obsidian_collector.seen_by_vault.items()
    )

    console.print(f"  Memories found:  [cyan]{len(memories)}[/]")
    console.print(f"  New indexed:     [green]{new_count}[/]")
    if missing_count:
        console.print(f"  Notes missing:   [yellow]{missing_count}[/]")
    if obsidian_collector.diagnostics:
        console.print(f"  Vault warnings:  [yellow]{len(obsidian_collector.diagnostics)}[/]")

    stats = engine.get_stats()
    console.print(f"  Total in index:  [bold]{stats['total_memories']}[/]")

    if stats["by_type"]:
        console.print("\n  [dim]By type:[/]")
        for t, c in sorted(stats["by_type"].items()):
            console.print(f"    {t}: {c}")

    engine.close()
    console.print("\n[green]✓ Synchronization complete.[/]")


# ═══════════════════════════════════════════════════════════════
#  Search — Eagle Vision
# ═══════════════════════════════════════════════════════════════

@app.command()
def search(
    query: str,
    mem_type: str = typer.Option(None, "--type", "-t", help="Filter by memory type"),
    workspace: str = typer.Option(None, "--workspace", "-w", help="Filter by workspace"),
    limit: int = typer.Option(20, "--limit", "-n"),
    remote: bool = typer.Option(False, "--remote", "-r", help="Also search hub"),
):
    """Search memories — Eagle Vision."""
    config = AnimusConfig.load()
    from .indexer.engine import IndexEngine

    engine = IndexEngine(config.db_path)

    console.print(f"[bold]🦅 Eagle Vision:[/] {query}\n")

    results = engine.search(query, mem_type=mem_type, workspace=workspace, limit=limit)

    if remote and config.hub_url:
        from .network.peer import AnimusPeer
        peer = AnimusPeer(config)
        remote_results = asyncio.run(peer.remote_search(query))
        results.extend(remote_results)

    if not results:
        console.print("[dim]No memories found.[/]")
        engine.close()
        return

    table = Table(show_header=True)
    table.add_column("#", style="dim", width=4)
    table.add_column("Type", style="cyan", width=16)
    table.add_column("Title", width=40)
    table.add_column("Workspace", style="green", width=15)
    table.add_column("Node", style="yellow", width=10)

    for i, r in enumerate(results, 1):
        table.add_row(
            str(i),
            r.get("type", "?"),
            (r.get("title", "") or "")[:40],
            (r.get("workspace", "") or "")[:15],
            (r.get("source_node", "") or "")[:10],
        )

    console.print(table)
    console.print(f"\n[dim]{len(results)} results[/]")
    engine.close()


# ═══════════════════════════════════════════════════════════════
#  Sync
# ═══════════════════════════════════════════════════════════════

@app.command()
def sync(verbose: bool = False):
    """Sync memories with the hub — Brotherhood link."""
    _setup_logging(verbose)
    config = AnimusConfig.load()

    if not config.hub_url:
        console.print("[red]No hub configured.[/] Run: animus config set hub_url <URL>")
        raise typer.Exit(1)

    from .network.peer import AnimusPeer

    peer = AnimusPeer(config)

    console.print(f"[bold]⟁ Syncing with hub:[/] {config.hub_url}\n")

    pushed = asyncio.run(peer.sync_to_hub())
    pulled = asyncio.run(peer.pull_from_hub())

    console.print(f"  Pushed: [cyan]{pushed}[/] memories")
    console.print(f"  Pulled: [green]{pulled}[/] memories")
    console.print("\n[green]✓ Sync complete.[/]")


# ═══════════════════════════════════════════════════════════════
#  Stats
# ═══════════════════════════════════════════════════════════════

@app.command()
def stats():
    """Show memory statistics."""
    config = AnimusConfig.load()
    from .indexer.engine import IndexEngine

    engine = IndexEngine(config.db_path)
    s = engine.get_stats()

    console.print("\n[bold]⟁ Animus Memory Bank[/]\n")
    console.print(f"  Total memories:    [bold cyan]{s['total_memories']}[/]")
    console.print(f"  Unique nodes:      [green]{s['unique_nodes']}[/]")
    console.print(f"  Workspaces:        [green]{s['unique_workspaces']}[/]")
    console.print(f"  Pending sync:      [yellow]{s['unsynced']}[/]")

    if s["by_type"]:
        console.print("\n  [dim]Memory types:[/]")
        for t, c in sorted(s["by_type"].items(), key=lambda x: x[1], reverse=True):
            bar = "█" * min(c, 40)
            console.print(f"    {t:20s} {c:5d}  [cyan]{bar}[/]")

    engine.close()


# ═══════════════════════════════════════════════════════════════
#  Serve (Hub mode)
# ═══════════════════════════════════════════════════════════════

@app.command()
def serve(
    host: str = typer.Option("0.0.0.0", "--host"),
    port: int = typer.Option(8314, "--port"),
    verbose: bool = False,
):
    """Run the Animus Hub server — central hub mode."""
    _setup_logging(verbose)
    import uvicorn

    console.print("[bold]⟁ Animus Hub starting...[/]")
    console.print(f"  Listening: {host}:{port}")
    console.print(f"  Docs:      http://{host}:{port}/docs\n")

    uvicorn.run(
        "animus.server.app:app",
        host=host,
        port=port,
        log_level="debug" if verbose else "info",
    )


# ═══════════════════════════════════════════════════════════════
#  Daemon (Peer mode)
# ═══════════════════════════════════════════════════════════════

@app.command()
def daemon(
    verbose: bool = False,
    log_file: Optional[Path] = typer.Option(
        None,
        "--log-file",
        help=(
            "Append daemon logs to this file (with rotation). When set the "
            "daemon also stops printing to stdout — useful when supervised "
            "by Scheduled Task / systemd / launchd."
        ),
    ),
):
    """Run as a background daemon — continuous collect + sync."""
    _setup_logging(verbose, log_file=log_file)
    config = AnimusConfig.load()

    from .network.peer import AnimusPeer

    peer = AnimusPeer(config)

    # Use logger so the message lands in --log-file too; console.print only
    # speaks to stdout and is invisible under a service manager.
    log = logging.getLogger("animus.daemon")
    log.info("Animus Daemon starting")
    log.info("  Node:     %s (%s)", config.node_id, config.node_name)
    log.info("  Interval: %ss", config.collect_interval_seconds)
    if config.hub_url:
        log.info("  Hub:      %s", config.hub_url)

    try:
        asyncio.run(peer.run_daemon())
    except KeyboardInterrupt:
        peer.stop()
        log.info("Animus daemon stopped (KeyboardInterrupt).")


# ═══════════════════════════════════════════════════════════════
#  Self-update
# ═══════════════════════════════════════════════════════════════


@app.command("self-update")
def self_update_cmd(
    check: bool = typer.Option(
        False, "--check",
        help="Just probe the hub and print the latest version — don't install.",
    ),
    force: bool = typer.Option(
        False, "--force",
        help="Re-install even if the hub's version isn't newer than ours.",
    ),
    no_restart: bool = typer.Option(
        False, "--no-restart",
        help="Install the new version but don't re-exec — useful from scripts.",
    ),
    verbose: bool = False,
):
    """Pull the latest Animus release from the hub and re-exec into it."""
    _setup_logging(verbose)
    from . import __version__
    from .network.updater import (
        apply_update, fetch_latest, is_newer, restart_in_place,
        update_is_deferred,
    )

    config = AnimusConfig.load()

    console.print(f"[bold]⟁ Current version:[/] {__version__}")
    if not config.hub_url:
        console.print("[red]No hub_url configured — nothing to check against.[/]")
        raise typer.Exit(2)

    info = fetch_latest(config)
    if info is None or not info.latest:
        console.print("[red]Failed to fetch latest version from hub.[/]")
        raise typer.Exit(3)

    console.print(f"  Hub latest:    [cyan]{info.latest}[/]  (channel={info.channel})")
    if info.notes:
        console.print(f"  Notes:         [dim]{info.notes[:200]}[/]")

    newer = is_newer(info.latest, __version__)
    if check:
        console.print("[yellow]up-to-date[/]" if not newer else "[green]update available[/]")
        return
    if not (force or newer):
        console.print("[green]✓ Already up-to-date.[/]")
        return

    ok = apply_update(info, allow_pre=config.update_allow_pre)
    if not ok:
        raise typer.Exit(4)
    deferred = update_is_deferred()
    if deferred:
        console.print(f"[green]✓ Update to v{info.latest} staged.[/]")
    else:
        console.print(f"[green]✓ Updated to v{info.latest}[/]")
    if not no_restart or deferred:
        if no_restart and deferred:
            console.print("[yellow]Windows must exit briefly to release executable locks.[/]")
        console.print("[dim]Restarting…[/]")
        restart_in_place()


# ═══════════════════════════════════════════════════════════════
#  Service (install daemon as a OS-level service)
# ═══════════════════════════════════════════════════════════════

service_app = typer.Typer(
    name="service",
    help="Install/manage the Animus daemon as an OS service (Scheduled Task / systemd / launchd).",
    no_args_is_help=True,
)
app.add_typer(service_app, name="service")


def _print_service(info) -> None:
    icon = "[green]●[/]" if info.running else ("[yellow]○[/]" if info.installed else "[red]✗[/]")
    console.print(f"  {icon} platform:  {info.platform}")
    console.print(f"     installed: {info.installed}")
    console.print(f"     running:   {info.running}")
    if info.detail:
        console.print(f"     detail:    {info.detail}")


@service_app.command("install")
def service_install(
    log_file: Optional[Path] = typer.Option(
        None, "--log-file",
        help="Where the daemon should append its log (default: <data_dir>/daemon.log).",
    ),
    animus_exe: Optional[Path] = typer.Option(
        None, "--animus-exe",
        help="Override the path to the animus executable (default: current venv).",
    ),
):
    """Register the Animus daemon to start automatically on this machine."""
    from . import service as svc

    config = AnimusConfig.load()
    config.ensure_dirs()

    exe = animus_exe or svc.default_animus_exe()
    log = log_file or svc.default_log_path(config.data_dir)

    console.print("[bold]⟁ Installing Animus service[/]")
    console.print(f"  exe:     {exe}")
    console.print(f"  logs:    {log}")
    console.print()
    info = svc.install(exe, log)
    _print_service(info)
    if not info.installed:
        raise typer.Exit(1)


@service_app.command("uninstall")
def service_uninstall():
    """Remove the Animus daemon from the OS service manager."""
    from . import service as svc

    info = svc.uninstall()
    _print_service(info)


@service_app.command("status")
def service_status(json_out: bool = typer.Option(False, "--json")):
    """Show whether the Animus service is installed and running."""
    from . import service as svc

    info = svc.status()
    if json_out:
        console.print_json(data=info.to_dict())
        return
    _print_service(info)


@service_app.command("start")
def service_start():
    """Start the Animus service (no-op if already running)."""
    from . import service as svc
    _print_service(svc.start())


@service_app.command("stop")
def service_stop():
    """Stop the Animus service (next logon/boot will start it again)."""
    from . import service as svc
    _print_service(svc.stop())


@service_app.command("logs")
def service_logs(
    tail: int = typer.Option(40, "--tail", "-n", help="Lines to show."),
    follow: bool = typer.Option(False, "--follow", "-f", help="Stream new lines."),
):
    """Print the daemon log file (default location: <data_dir>/daemon.log)."""
    import time
    from . import service as svc

    config = AnimusConfig.load()
    log = svc.default_log_path(config.data_dir)
    if not log.exists():
        console.print(f"[yellow]No log file at {log}[/]")
        console.print(
            "  Run [bold]animus service install[/] or "
            "[bold]animus daemon --log-file <path>[/] first."
        )
        raise typer.Exit(1)

    lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
    for line in lines[-tail:]:
        print(line)

    if follow:
        try:
            with log.open("r", encoding="utf-8", errors="replace") as fh:
                fh.seek(0, 2)  # end
                while True:
                    line = fh.readline()
                    if not line:
                        time.sleep(0.5)
                        continue
                    print(line.rstrip())
        except KeyboardInterrupt:
            return


# ═══════════════════════════════════════════════════════════════
#  Tunnel
# ═══════════════════════════════════════════════════════════════

@app.command()
def tunnel(
    mode: str = typer.Argument(help="Tunnel mode: ssh | chisel | cloudflared"),
    verbose: bool = False,
):
    """Start a secure tunnel to the hub."""
    _setup_logging(verbose)
    config = AnimusConfig.load()
    config.tunnel_mode = mode

    from .network.tunnel import TunnelManager

    tm = TunnelManager(config)
    console.print(f"[bold]⟁ Starting {mode} tunnel...[/]")

    try:
        info = asyncio.run(tm.start())
        if info:
            console.print("  [green]✓ Tunnel active[/]")
            console.print(f"  Mode:   {info.mode}")
            console.print(f"  Local:  localhost:{info.local_port}")
            console.print(f"  Remote: {info.remote_host}:{info.remote_port}")
            console.print(f"  PID:    {info.pid}")
            console.print("\n  Press Ctrl+C to stop.")
            # Keep running
            asyncio.run(asyncio.sleep(86400 * 365))
    except KeyboardInterrupt:
        asyncio.run(tm.stop())
        console.print("\n[yellow]⟁ Tunnel stopped.[/]")
    except RuntimeError as e:
        console.print(f"[red]✗ {e}[/]")
        raise typer.Exit(1)


# ═══════════════════════════════════════════════════════════════
#  MCP Server
# ═══════════════════════════════════════════════════════════════

@app.command()
def mcp(verbose: bool = False):
    """Run the Animus MCP Server (stdio) — for VS Code integration."""
    import logging as _logging

    _logging.basicConfig(
        level=_logging.DEBUG if verbose else _logging.INFO,
        format="%(asctime)s [%(name)s] %(message)s",
        stream=sys.stderr,
    )
    from .mcp import AnimusMCPServer

    server = AnimusMCPServer()
    server.run()


# ═══════════════════════════════════════════════════════════════
#  Context Generation
# ═══════════════════════════════════════════════════════════════

@app.command()
def context(
    workspace: str = typer.Argument(default=".", help="Workspace root path"),
):
    """Generate .animus-context.md for a workspace — inject memories into Copilot."""
    config = AnimusConfig.load()
    from .mcp.active import ActiveContextInjector

    injector = ActiveContextInjector(config)
    root = Path(workspace).resolve()

    console.print(f"[bold]⟁ Generating context for:[/] {root.name}\n")
    ctx_file = injector.write_workspace_context(root)
    console.print(f"  [green]✓[/] Written: {ctx_file}")
    console.print("  Copilot will auto-include this as workspace context.")
    injector.close()


if __name__ == "__main__":
    app()
