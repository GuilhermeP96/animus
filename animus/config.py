"""Animus configuration management."""

from __future__ import annotations

import json
import os
import platform
from pathlib import Path
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings


def _default_data_dir() -> Path:
    system = platform.system()
    if system == "Windows":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif system == "Darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "animus"


def _default_vscode_dir() -> Path:
    system = platform.system()
    if system == "Windows":
        return Path(os.environ.get("APPDATA", "")) / "Code" / "User"
    elif system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "Code" / "User"
    else:
        return Path.home() / ".config" / "Code" / "User"


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

    # ── Indexer ──
    fts_enabled: bool = True
    vector_enabled: bool = False

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
            cfg.save()
        if not cfg.node_name:
            cfg.node_name = platform.node()
        return cfg
