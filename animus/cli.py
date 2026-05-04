"""Animus CLI — Leap of Faith into your memories."""

from __future__ import annotations

import asyncio
import json
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
    help="🦅 Animus — Copilot Memory Synchronization Network",
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
    console.print(f"\n[bold green]⟁[/] Animus initialized")
    console.print(f"  Node ID:   [cyan]{config.node_id}[/]")
    console.print(f"  Node Name: [cyan]{config.node_name}[/]")
    console.print(f"  Data dir:  [dim]{config.data_dir}[/]")
    console.print(f"  Config:    [dim]{config.config_path}[/]")
    console.print(f"\n  Run [bold]animus collect[/] to start gathering memories.")


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

@app.command()
def collect(verbose: bool = False):
    """Collect memories from Copilot interactions — Desynchronize."""
    _setup_logging(verbose)
    config = AnimusConfig.load()

    from .collector.copilot import CopilotCollector
    from .indexer.engine import IndexEngine

    collector = CopilotCollector(config)
    engine = IndexEngine(config.db_path)

    console.print("[bold]⟁ Entering the Animus...[/]\n")

    memories = collector.collect_all()
    new_count = engine.index_batch(memories)

    console.print(f"  Memories found:  [cyan]{len(memories)}[/]")
    console.print(f"  New indexed:     [green]{new_count}[/]")

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
    """Run the Animus Hub server — Abstergo mode."""
    _setup_logging(verbose)
    import uvicorn

    console.print(f"[bold]⟁ Animus Hub (Abstergo) starting...[/]")
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

    console.print(f"[bold]⟁ Installing Animus service[/]")
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
            console.print(f"  [green]✓ Tunnel active[/]")
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
    console.print(f"  Copilot will auto-include this as workspace context.")
    injector.close()


if __name__ == "__main__":
    app()
