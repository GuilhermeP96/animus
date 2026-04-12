"""Copilot memory collector — extracts memories from VS Code Copilot data."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator

from ..config import AnimusConfig
from .models import Memory, MemoryType

logger = logging.getLogger("animus.collector")


class CopilotCollector:
    """Collects genetic memories from GitHub Copilot interactions.

    Scans:
    - Copilot chat debug logs (JSON lines)
    - Copilot chat history (workspace storage)
    - Session/user/repo memory files
    - Workspace instruction files
    - Prompt and agent files
    """

    def __init__(self, config: AnimusConfig):
        self.config = config
        self.vscode_dir = config.vscode_user_dir
        self.workspace_storage = self.vscode_dir / "workspaceStorage"

    def collect_all(self) -> list[Memory]:
        memories: list[Memory] = []
        if self.config.collect_copilot_logs:
            memories.extend(self._collect_debug_logs())
        if self.config.collect_copilot_chat:
            memories.extend(self._collect_chat_history())
        if self.config.collect_workspace_memories:
            memories.extend(self._collect_workspace_memories())
        if self.config.collect_mcp_memory:
            memories.extend(self._collect_mcp_memory())
        return memories

    # ── Debug Logs ──

    def _collect_debug_logs(self) -> list[Memory]:
        """Scan Copilot chat debug-logs directories."""
        memories = []
        if not self.workspace_storage.exists():
            return memories

        for ws_dir in self.workspace_storage.iterdir():
            if not ws_dir.is_dir():
                continue
            debug_dir = ws_dir / "GitHub.copilot-chat" / "debug-logs"
            if not debug_dir.exists():
                continue
            for log_file in debug_dir.glob("*"):
                if log_file.is_file() and log_file.stat().st_size > 0:
                    try:
                        memories.extend(self._parse_debug_log(log_file, ws_dir.name))
                    except Exception:
                        logger.debug("Failed to parse debug log %s", log_file, exc_info=True)
                        continue
        return memories

    def _parse_debug_log(self, path: Path, workspace_id: str) -> list[Memory]:
        """Parse a Copilot debug log file."""
        memories = []
        content = path.read_text(encoding="utf-8", errors="replace")

        # Try JSON lines format
        for i, line in enumerate(content.splitlines()):
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                mem = Memory(
                    type=MemoryType.COPILOT_DEBUG,
                    source_node=self.config.node_id,
                    source_path=str(path),
                    workspace=workspace_id,
                    title=data.get("type", data.get("event", f"log-{i}")),
                    content=line,
                    metadata={"log_file": path.name, "line": i},
                    sequence=i,
                )
                memories.append(mem)
            except json.JSONDecodeError:
                # Plain text log line
                if len(line) > 20:
                    mem = Memory(
                        type=MemoryType.COPILOT_DEBUG,
                        source_node=self.config.node_id,
                        source_path=str(path),
                        workspace=workspace_id,
                        title=f"debug-{path.stem}-{i}",
                        content=line,
                        metadata={"log_file": path.name, "line": i},
                        sequence=i,
                    )
                    memories.append(mem)
        return memories

    # ── Chat History ──

    def _collect_chat_history(self) -> list[Memory]:
        """Collect Copilot chat conversation history."""
        memories = []
        if not self.workspace_storage.exists():
            return memories

        for ws_dir in self.workspace_storage.iterdir():
            if not ws_dir.is_dir():
                continue
            # Chat history can be in various formats
            copilot_dir = ws_dir / "GitHub.copilot-chat"
            if not copilot_dir.exists():
                continue

            for chat_file in copilot_dir.rglob("*.json"):
                try:
                    memories.extend(self._parse_chat_file(chat_file, ws_dir.name))
                except Exception:
                    logger.debug("Failed to parse chat file %s", chat_file, exc_info=True)
                    continue
        return memories

    def _parse_chat_file(self, path: Path, workspace_id: str) -> list[Memory]:
        """Parse a chat history JSON file."""
        memories = []
        content = path.read_text(encoding="utf-8", errors="replace")
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            return memories

        # Handle array of messages
        messages = data if isinstance(data, list) else data.get("messages", [])
        if isinstance(data, dict) and not messages:
            # Single conversation object
            mem = Memory(
                type=MemoryType.COPILOT_CHAT,
                source_node=self.config.node_id,
                source_path=str(path),
                workspace=workspace_id,
                title=data.get("title", path.stem),
                content=content[:50000],  # Cap at 50KB
                metadata={"file": path.name},
            )
            memories.append(mem)
            return memories

        for i, msg in enumerate(messages):
            if not isinstance(msg, dict):
                continue
            text = msg.get("content", msg.get("text", msg.get("message", "")))
            if not text:
                continue
            role = msg.get("role", msg.get("author", "unknown"))
            mem = Memory(
                type=MemoryType.COPILOT_CHAT,
                source_node=self.config.node_id,
                source_path=str(path),
                workspace=workspace_id,
                title=f"{role}: {text[:80]}",
                content=text,
                metadata={
                    "role": role,
                    "file": path.name,
                    "turn": i,
                },
                sequence=i,
            )
            memories.append(mem)
        return memories

    # ── Workspace Memories ──

    def _collect_workspace_memories(self) -> list[Memory]:
        """Collect instruction files, prompts, agents, memory files."""
        memories = []
        scan_roots = self._find_workspace_roots()
        for root in scan_roots:
            memories.extend(self._scan_workspace(root))
        return memories

    def _find_workspace_roots(self) -> list[Path]:
        """Discover workspace roots from VS Code storage."""
        roots = []
        # Use workspaceStorage to find workspace paths
        if self.workspace_storage.exists():
            for ws_dir in self.workspace_storage.iterdir():
                ws_json = ws_dir / "workspace.json"
                if ws_json.exists():
                    try:
                        data = json.loads(ws_json.read_text(encoding="utf-8"))
                        folder = data.get("folder", "")
                        if folder.startswith("file:///"):
                            path = Path(folder[8:]) if folder[9:10] == ":" else Path(folder[7:])
                            if path.exists():
                                roots.append(path)
                    except (json.JSONDecodeError, OSError):
                        logger.debug("Failed to parse workspace.json in %s", ws_dir, exc_info=True)
                        continue
        return roots

    def _scan_workspace(self, root: Path) -> Generator[Memory, None, None]:
        """Scan a workspace for copilot-related files."""
        workspace_name = root.name
        patterns = {
            MemoryType.WORKSPACE_MEMORY: [
                ".github/copilot-instructions.md",
                ".instructions.md",
                "CLAUDE.md",
            ],
            MemoryType.PROMPT_FILE: list(root.glob(".github/prompts/*.prompt.md")),
            MemoryType.AGENT_FILE: list(root.glob(".github/agents/*.agent.md")),
        }

        # Static files
        for mem_type, files in patterns.items():
            for f in files:
                path = f if isinstance(f, Path) else root / f
                if path.exists() and path.is_file():
                    try:
                        content = path.read_text(encoding="utf-8", errors="replace")
                        yield Memory(
                            type=mem_type,
                            source_node=self.config.node_id,
                            source_path=str(path),
                            workspace=workspace_name,
                            title=path.name,
                            content=content[:100000],
                            metadata={"workspace_root": str(root)},
                        )
                    except OSError:
                        continue

        # Memory files (/memories/ pattern within workspace)
        for mem_dir_name in ["memories", ".memories"]:
            mem_dir = root / mem_dir_name
            if mem_dir.exists():
                for md_file in mem_dir.rglob("*.md"):
                    try:
                        content = md_file.read_text(encoding="utf-8", errors="replace")
                        rel = md_file.relative_to(mem_dir)
                        if "session" in str(rel):
                            mt = MemoryType.SESSION_NOTE
                        elif "repo" in str(rel):
                            mt = MemoryType.REPO_NOTE
                        else:
                            mt = MemoryType.USER_NOTE
                        yield Memory(
                            type=mt,
                            source_node=self.config.node_id,
                            source_path=str(md_file),
                            workspace=workspace_name,
                            title=md_file.stem,
                            content=content,
                            metadata={"relative": str(rel)},
                        )
                    except OSError:
                        continue

    # ── MCP Memory ──

    def _collect_mcp_memory(self) -> list[Memory]:
        """Collect from MCP memory server knowledge graph if available."""
        memories = []
        # MCP memory server typically stores in a JSON file
        possible_paths = [
            self.config.data_dir.parent / "mcp-memory" / "memory.json",
            Path.home() / ".mcp" / "memory.json",
            Path.home() / ".local" / "share" / "mcp-memory" / "memory.json",
        ]
        for p in possible_paths:
            if p.exists():
                try:
                    data = json.loads(p.read_text(encoding="utf-8"))
                    entities = data.get("entities", [])
                    for entity in entities:
                        content_parts = []
                        if "observations" in entity:
                            content_parts.extend(entity["observations"])
                        name = entity.get("name", "unknown")
                        mem = Memory(
                            type=MemoryType.MCP_KNOWLEDGE,
                            source_node=self.config.node_id,
                            source_path=str(p),
                            title=name,
                            content="\n".join(content_parts) if content_parts else json.dumps(entity),
                            metadata={
                                "entity_type": entity.get("entityType", ""),
                                "relations": entity.get("relations", []),
                            },
                            tags=[entity.get("entityType", "")],
                        )
                        memories.append(mem)
                except (json.JSONDecodeError, OSError):
                    continue
        return memories
