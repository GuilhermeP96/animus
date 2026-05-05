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
            memories.extend(self._collect_transcripts())
        if self.config.collect_workspace_memories:
            memories.extend(self._collect_workspace_memories())
            memories.extend(self._collect_memory_tool())
        if self.config.collect_mcp_memory:
            memories.extend(self._collect_mcp_memory())
        return memories

    # ── Debug Logs ──

    def _collect_debug_logs(self) -> list[Memory]:
        """Scan Copilot chat debug-logs directories (including subdirectories)."""
        memories = []
        if not self.workspace_storage.exists():
            return memories

        for ws_dir in self.workspace_storage.iterdir():
            if not ws_dir.is_dir():
                continue
            debug_dir = ws_dir / "GitHub.copilot-chat" / "debug-logs"
            if not debug_dir.exists():
                continue
            # Use rglob to find files inside session subdirectories
            for log_file in debug_dir.rglob("*"):
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

    def _collect_transcripts(self) -> list[Memory]:
        """Collect Copilot chat transcripts (.jsonl files in transcripts/ dirs)."""
        memories = []
        if not self.workspace_storage.exists():
            return memories

        for ws_dir in self.workspace_storage.iterdir():
            if not ws_dir.is_dir():
                continue
            transcripts_dir = ws_dir / "GitHub.copilot-chat" / "transcripts"
            if not transcripts_dir.exists():
                continue
            for jsonl_file in transcripts_dir.glob("*.jsonl"):
                if not jsonl_file.is_file() or jsonl_file.stat().st_size == 0:
                    continue
                try:
                    content = jsonl_file.read_text(encoding="utf-8", errors="replace")
                    for i, line in enumerate(content.splitlines()):
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            data = json.loads(line)
                            # Transcripts use a nested {"type": ..., "data": {...}} envelope.
                            # The actual message lives under data["data"]; older / non-envelope
                            # rows put it at the top level. Probe both, in order.
                            payload = data.get("data") if isinstance(data.get("data"), dict) else data
                            role = (
                                data.get("type")
                                or payload.get("role")
                                or payload.get("type")
                                or "unknown"
                            )
                            text = (
                                payload.get("content")
                                or payload.get("text")
                                or payload.get("message")
                                or data.get("content")
                                or data.get("text")
                                or data.get("message")
                                or ""
                            )
                            # Some payloads store content as a list of parts
                            # (Anthropic / Copilot agent style: [{type:"text", text:"..."}, ...]).
                            if isinstance(text, list):
                                text = "\n".join(
                                    p.get("text", "") if isinstance(p, dict) else str(p)
                                    for p in text
                                ).strip()
                            elif not isinstance(text, str):
                                text = str(text) if text is not None else ""
                            # Skip envelope-only events with no human-readable body.
                            if not text and role in {"session.start", "session.end", "ping"}:
                                continue
                            title_text = (text[:80] if text else role or f"turn-{i}")
                            mem = Memory(
                                type=MemoryType.COPILOT_CHAT,
                                source_node=self.config.node_id,
                                source_path=str(jsonl_file),
                                workspace=ws_dir.name,
                                title=f"transcript:{role}:{title_text}",
                                content=text if text else line[:50000],
                                metadata={
                                    "source": "transcript",
                                    "session": jsonl_file.stem,
                                    "role": role,
                                    "turn": i,
                                },
                                sequence=i,
                            )
                            memories.append(mem)
                        except json.JSONDecodeError:
                            continue
                except Exception:
                    logger.debug("Failed to parse transcript %s", jsonl_file, exc_info=True)
        return memories

    def _collect_memory_tool(self) -> list[Memory]:
        """Collect Copilot memory-tool .md files from all workspace storages."""
        memories = []
        if not self.workspace_storage.exists():
            return memories

        for ws_dir in self.workspace_storage.iterdir():
            if not ws_dir.is_dir():
                continue
            memory_tool_dir = ws_dir / "GitHub.copilot-chat" / "memory-tool"
            if not memory_tool_dir.exists():
                continue
            for md_file in memory_tool_dir.rglob("*.md"):
                try:
                    content = md_file.read_text(encoding="utf-8", errors="replace")
                    rel = md_file.relative_to(memory_tool_dir)
                    # Classify by path
                    rel_str = str(rel)
                    if "/repo/" in rel_str or rel_str.startswith("memories/repo/"):
                        mt = MemoryType.REPO_NOTE
                    elif "/session/" in rel_str or rel_str.startswith("memories/session/"):
                        mt = MemoryType.SESSION_NOTE
                    else:
                        mt = MemoryType.USER_NOTE
                    mem = Memory(
                        type=mt,
                        source_node=self.config.node_id,
                        source_path=str(md_file),
                        workspace=ws_dir.name,
                        title=md_file.stem,
                        content=content,
                        metadata={
                            "source": "memory-tool",
                            "relative": rel_str,
                            "workspace_id": ws_dir.name,
                        },
                    )
                    memories.append(mem)
                except OSError:
                    continue
        return memories

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
