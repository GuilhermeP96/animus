"""Animus configuration management."""

from __future__ import annotations

import json
import logging
import os
import platform
import shutil
from pathlib import Path
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings


def _default_data_dir() -> Path:
    system = platform.system()
    if system == "Windows":
        # NOTE: We deliberately avoid %APPDATA% / %LOCALAPPDATA% on
        # Windows. When Animus runs under the Microsoft Store Python
        # (PythonSoftwareFoundation.Python.*), AppX storage
        # virtualization silently redirects writes under those roots
        # to the package's LocalCache, which is invisible to other
        # shells/tools and breaks the "config-set saved but file
        # missing" debugging loop. The user profile root is not
        # virtualized, so .animus/ there is stable across all
        # interpreters.
        base = Path.home() / ".animus"
        return base
    elif system == "Darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "animus"


def _legacy_data_dirs() -> list[Path]:
    """Older data_dir locations to migrate from on first run.

    Order matters: the first one that exists and contains a
    config.json wins.
    """
    out: list[Path] = []
    if platform.system() != "Windows":
        return out

    # Pre-0.4.5 default
    appdata = os.environ.get("APPDATA")
    if appdata:
        out.append(Path(appdata) / "animus")

    # AppX-virtualized variants (Microsoft Store Python redirects
    # %APPDATA% writes to LocalCache\Roaming under the package).
    localappdata = os.environ.get("LOCALAPPDATA")
    if localappdata:
        packages = Path(localappdata) / "Packages"
        if packages.is_dir():
            for pkg in packages.glob(
                "PythonSoftwareFoundation.Python.*/LocalCache/Roaming/animus"
            ):
                out.append(pkg)

    return out


def _migrate_legacy_data_dir(src: Path, dst: Path) -> None:
    """Copy a legacy data_dir into the new location.

    Idempotent: only files missing at the destination are copied.
    Logs a warning so the user notices the migration.
    """
    log = logging.getLogger("animus.config")
    log.warning("Migrating Animus data from legacy path %s -> %s", src, dst)
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        target = dst / item.name
        if target.exists():
            continue
        try:
            if item.is_dir():
                shutil.copytree(item, target)
            else:
                shutil.copy2(item, target)
        except OSError as exc:
            log.error("Failed to migrate %s: %s", item, exc)

    # Rewrite the migrated config.json so its data_dir points at the
    # new location instead of the legacy one we just copied from.
    cfg_file = dst / "config.json"
    if cfg_file.exists():
        try:
            data = json.loads(cfg_file.read_text(encoding="utf-8"))
            data["data_dir"] = str(dst)
            cfg_file.write_text(
                json.dumps(data, indent=2, default=str), encoding="utf-8"
            )
        except (OSError, json.JSONDecodeError) as exc:
            log.error("Failed to rewrite data_dir in migrated config: %s", exc)


def _default_vscode_dir() -> Path:
    system = platform.system()
    if system == "Windows":
        return Path(os.environ.get("APPDATA", "")) / "Code" / "User"
    elif system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "Code" / "User"
    else:
        return Path.home() / ".config" / "Code" / "User"


def _default_claude_dir() -> Path:
    """Claude Code's data root — same shape on every OS."""
    return Path.home() / ".claude"


def _default_antigravity_dir() -> Path:
    """Google Antigravity's data root — same shape on every OS."""
    return Path.home() / ".gemini"


def _default_copilot_cli_dir() -> Path:
    """GitHub Copilot CLI's data root — same shape on every OS."""
    return Path.home() / ".copilot"


class AnimusConfig(BaseSettings):
    """Core Animus configuration."""

    model_config = {"env_prefix": "ANIMUS_", "env_file": ".env"}

    # ── Identity ──
    node_id: str = Field(default="", description="Unique node ID (auto-generated if empty)")
    node_name: str = Field(default="", description="Human-friendly node name")
    node_role: str = Field(default="peer", description="Role: peer | hub")

    # ── Paths ──
    data_dir: Path = Field(default_factory=_default_data_dir)
    vscode_user_dir: Path = Field(default_factory=_default_vscode_dir)
    claude_data_dir: Path = Field(
        default_factory=_default_claude_dir,
        description="Claude Code data root (~/.claude). Holds projects/<enc>/<session>.jsonl and projects/<enc>/memory/*.md.",
    )

    # ── Hub Connection ──
    hub_url: str = Field(default="", description="Hub server URL (wss://...)")
    hub_token: str = Field(default="", description="Auth token for hub")

    # ── Server (when running as hub) ──
    server_host: str = "0.0.0.0"
    server_port: int = 8314
    server_secret: str = Field(default="", description="Shared secret for peer auth")

    # ── Tunnel ──
    tunnel_mode: str = Field(
        default="none",
        description="Tunnel: none | ssh | chisel | cloudflared",
    )
    tunnel_ssh_host: str = ""
    tunnel_ssh_user: str = ""
    tunnel_ssh_key: str = ""
    tunnel_ssh_port: int = 22
    tunnel_remote_port: int = 8314

    # ── Collector ──
    collect_interval_seconds: int = 300
    collect_copilot_logs: bool = True
    collect_copilot_chat: bool = True
    collect_workspace_memories: bool = True
    collect_mcp_memory: bool = True
    collect_claude_chat: bool = True       # Claude Code session transcripts
    collect_claude_memory: bool = True     # Claude Code auto-memory .md files
    collect_copilot_cli_chat: bool = True  # GitHub Copilot CLI session turns/checkpoints
    collect_antigravity_chat: bool = True      # Antigravity CLI/IDE conversation turns
    collect_antigravity_memory: bool = True    # Antigravity brain / GEMINI.md memory files
    collect_antigravity_knowledge: bool = True # Antigravity .antigravity project context

    # ── Antigravity paths ──
    antigravity_data_dir: Path = Field(
        default_factory=_default_antigravity_dir,
        description="Antigravity data root (~/.gemini). Holds antigravity/conversations/*.db, brain/, config/projects/, etc.",
    )

    # ── Copilot CLI paths ──
    copilot_cli_data_dir: Path = Field(
        default_factory=_default_copilot_cli_dir,
        description="GitHub Copilot CLI data root (~/.copilot). Holds session-store.db, session-state/, logs, etc.",
    )

    # ── Indexer ──
    fts_enabled: bool = True
    vector_enabled: bool = False

    # ── Self-update ──
    auto_update_enabled: bool = True
    # How often the daemon asks the hub "anything new?". Defaults to 6h —
    # short enough that a release rolls out within a workday, long enough
    # that a chatty daemon doesn't hammer the hub.
    update_check_interval_seconds: int = 21_600
    update_allow_pre: bool = False  # opt-in to ``--pre`` releases

    @property
    def db_path(self) -> Path:
        return self.data_dir / "animus.db"

    @property
    def index_path(self) -> Path:
        return self.data_dir / "index"

    @property
    def config_path(self) -> Path:
        return self.data_dir / "config.json"

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.index_path.mkdir(parents=True, exist_ok=True)

    def save(self) -> None:
        self.ensure_dirs()
        data = self.model_dump(mode="json")
        # Convert Path objects to strings for JSON
        for k, v in data.items():
            if isinstance(v, Path):
                data[k] = str(v)
        self.config_path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "AnimusConfig":
        from pydantic import ValidationError

        cfg = cls()
        file = path or cfg.config_path

        # One-shot migration from legacy data_dirs (pre-0.4.5 default
        # of %APPDATA%\animus and AppX-virtualized variants under
        # Microsoft Store Python). Only triggered when the new
        # location has no config yet.
        if path is None and not file.exists():
            for legacy in _legacy_data_dirs():
                if legacy == cfg.data_dir:
                    continue
                if (legacy / "config.json").exists():
                    _migrate_legacy_data_dir(legacy, cfg.data_dir)
                    break

        if file.exists():
            data = json.loads(file.read_text(encoding="utf-8"))
            try:
                cfg = cls(**data)
            except ValidationError as exc:
                import logging
                logging.getLogger("animus.config").warning(
                    "Config validation errors in %s — using defaults for invalid fields:\n%s",
                    file,
                    exc,
                )
                # Partial load: drop unknown/invalid keys and retry
                valid_fields = set(cls.model_fields)
                cleaned = {k: v for k, v in data.items() if k in valid_fields}
                try:
                    cfg = cls(**cleaned)
                except ValidationError:
                    cfg = cls()  # ultimate fallback
        if not cfg.node_id:
            import uuid

            cfg.node_id = str(uuid.uuid4())[:12]
            # Only persist when load() was called without an explicit
            # path. Otherwise the auto-save would clobber the user's
            # real ~/.animus/config.json with defaults whenever a test
            # (or any caller) points load() at a sandbox file. Tests
            # were doing this and silently wiping live peer configs.
            if path is None:
                cfg.save()
        if not cfg.node_name:
            cfg.node_name = platform.node()
        return cfg
