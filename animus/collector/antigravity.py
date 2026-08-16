"""Google Antigravity memory collector.

Antigravity has two local faces:

* **CLI** (``agy``) -> ``~/.gemini/antigravity/``
* **IDE** (desktop/VS Code fork) -> ``~/.gemini/antigravity-ide/``

Both share the same directory layout:

* ``conversations/<uuid>.db`` — SQLite database with protobuf-encoded
  trajectory steps and metadata. We read the ``steps`` and ``gen_metadata``
  tables as opaque binary blobs, decode what we can as text, and emit one
  memory per conversation turn. The exact protobuf schema is internal to
  Google, so this collector is intentionally defensive: it extracts
  human-readable text snippets and treats the rest as searchable raw bytes.
* ``brain/<uuid>/{scratch,.system_generated,.user_uploaded}`` — persistent
  memory files that the agent reads across sessions. We index each as an
  ``antigravity_memory``.
* ``config/projects/<project>.json`` — workspace/project metadata. We index
  these as ``antigravity_knowledge`` so search can surface project context.
* ``~/.gemini/GEMINI.md`` — global identity / rules file for Antigravity.
  Indexed as ``antigravity_memory`` when present.
* ``.antigravity/mcp.json`` inside each workspace — MCP server registration
  for the project. Indexed as ``antigravity_knowledge``.

The collector mirrors the existing Claude/Copilot collectors: best-effort,
never crashes the sync, and caps individual records at 256 KB.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import AnimusConfig
from .models import Memory, MemoryType

logger = logging.getLogger("animus.collector.antigravity")

_MAX_TURN_BYTES = 256_000
_MAX_PROTO_TEXT_BYTES = 50_000  # Cap extracted protobuf text per turn


class AntigravityCollector:
    """Collects memories from Google Antigravity local state."""

    def __init__(self, config: AnimusConfig):
        self.config = config
        self.agy_dir = config.antigravity_data_dir

    # ── Public entrypoint ────────────────────────────────────────────────

    def collect_all(self) -> list[Memory]:
        memories: list[Memory] = []
        if not self.agy_dir.exists():
            return memories

        for app_name in ("antigravity", "antigravity-ide"):
            app_dir = self.agy_dir / app_name
            if not app_dir.is_dir():
                continue
            source_label = app_name  # "antigravity" or "antigravity-ide"

            if self.config.collect_antigravity_chat:
                try:
                    memories.extend(self._collect_conversations(app_dir, source_label))
                except Exception:
                    logger.debug("Failed Antigravity conversations in %s", app_dir, exc_info=True)

            if self.config.collect_antigravity_memory:
                try:
                    memories.extend(self._collect_brain_files(app_dir, source_label))
                except Exception:
                    logger.debug("Failed Antigravity brain in %s", app_dir, exc_info=True)

            if self.config.collect_antigravity_knowledge:
                try:
                    memories.extend(self._collect_project_context(app_dir, source_label))
                except Exception:
                    logger.debug("Failed Antigravity project context in %s", app_dir, exc_info=True)

        # Global GEMINI.md — only once, regardless of CLI vs IDE
        if self.config.collect_antigravity_memory:
            try:
                memories.extend(self._collect_global_gemini_md())
            except Exception:
                logger.debug("Failed global GEMINI.md", exc_info=True)

        # Workspace-level .antigravity/mcp.json
        if self.config.collect_antigravity_knowledge:
            try:
                memories.extend(self._collect_workspace_mcp_configs())
            except Exception:
                logger.debug("Failed workspace .antigravity/mcp.json", exc_info=True)

        return memories

    # ── Conversations (SQLite protobuf blobs) ────────────────────────────

    def _collect_conversations(self, app_dir: Path, source_label: str) -> list[Memory]:
        memories: list[Memory] = []
        conv_dir = app_dir / "conversations"
        if not conv_dir.is_dir():
            return memories

        for db_file in conv_dir.glob("*.db"):
            if not db_file.is_file():
                continue
            try:
                memories.extend(self._parse_conversation_db(db_file, source_label))
            except Exception:
                logger.debug("Failed conversation db %s", db_file, exc_info=True)
        return memories

    def _parse_conversation_db(self, db_path: Path, source_label: str) -> list[Memory]:
        """Read the SQLite conversation db and emit one memory per step."""
        memories: list[Memory] = []
        conversation_id = db_path.stem

        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        except sqlite3.Error:
            return memories

        try:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = {r["name"] for r in cursor.fetchall()}
            if "steps" not in tables:
                return memories

            # Try to enrich with project name from gen_metadata when available
            workspace = self._resolve_workspace_for_conversation(conn, conversation_id, source_label)

            cursor.execute(
                "SELECT idx, step_type, status, metadata, step_payload, step_format FROM steps ORDER BY idx"
            )
            for row in cursor.fetchall():
                text, meta = self._extract_text_from_step_row(dict(row))
                if not text.strip():
                    continue

                title = text[:80].replace("\n", " ")
                memories.append(
                    Memory(
                        type=MemoryType.ANTIGRAVITY_CHAT,
                        source_node=self.config.node_id,
                        source_path=str(db_path),
                        workspace=workspace,
                        title=f"antigravity:{title}",
                        content=text[:_MAX_TURN_BYTES],
                        metadata={
                            "source": source_label,
                            "conversation_id": conversation_id,
                            "step_idx": row["idx"],
                            "step_type": row["step_type"],
                            "step_status": row["status"],
                            "step_format": row["step_format"],
                            **meta,
                        },
                        sequence=row["idx"],
                        tags=[source_label],
                    )
                )
        finally:
            conn.close()

        return memories

    def _resolve_workspace_for_conversation(
        self, conn: sqlite3.Connection, conversation_id: str, source_label: str
    ) -> str:
        """Best-effort resolve a workspace label for a conversation.

        Antigravity stores a JSON index in ``~/.gemini/antigravity-cli/cache/last_conversations.json``
        that maps absolute workspace paths to the most recently active conversation id.
        We also scan ``config/projects/*.json`` for conversation id references.
        """
        # 1. Try the CLI cache file (works for both CLI and IDE if shared)
        cache_file = self.agy_dir / "antigravity-cli" / "cache" / "last_conversations.json"
        if cache_file.exists():
            try:
                data = json.loads(cache_file.read_text(encoding="utf-8"))
                for path, cid in data.items():
                    if cid == conversation_id:
                        return Path(path).name or path
            except (json.JSONDecodeError, OSError):
                pass

        # 2. Try to find a matching project config
        projects_dir = self.agy_dir / "config" / "projects"
        if projects_dir.is_dir():
            for proj_file in projects_dir.glob("*.json"):
                try:
                    data = json.loads(proj_file.read_text(encoding="utf-8"))
                    if data.get("conversation_id") == conversation_id or conversation_id in str(data):
                        return proj_file.stem
                except (json.JSONDecodeError, OSError):
                    continue

        return source_label

    def _extract_text_from_step_row(self, row: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        """Pull human-readable text from a protobuf step row.

        Antigravity encodes step payloads as protobuf binaries. We don't have the
        official descriptors, so we:
        1. scan all binary blobs for UTF-8 text runs,
        2. join the longer runs,
        3. collapse repeated whitespace.
        This is lossy but keeps the memory searchable.
        """
        chunks: list[str] = []
        meta: dict[str, Any] = {}

        for key in ("metadata", "step_payload", "permissions", "task_details", "render_info"):
            blob = row.get(key)
            if isinstance(blob, bytes) and blob:
                text = self._safe_utf8_text(blob)
                if text:
                    chunks.append(text)

        combined = "\n\n".join(chunks)
        # Clean up protobuf artifacts: lots of short control chars / repeated newlines
        combined = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]+", " ", combined)
        combined = re.sub(r"\n{3,}", "\n\n", combined)
        combined = re.sub(r" {2,}", " ", combined)
        return combined.strip()[:_MAX_PROTO_TEXT_BYTES], meta

    @staticmethod
    def _safe_utf8_text(blob: bytes) -> str:
        """Decode a protobuf blob, keeping only coherent UTF-8 text runs."""
        text = blob.decode("utf-8", errors="ignore")
        # Protobuf leaves a lot of single printable chars; keep sequences of at least 4 chars
        runs = re.findall(r"[\x20-\x7E\xA0-\xFF]{4,}", text)
        # Filter out hex-ish / base64-ish noise
        filtered = []
        for run in runs:
            if len(re.findall(r"[a-f0-9A-F]{8,}", run)) == 1 and len(run) < 20:
                continue  # likely a UUID/hash
            if re.fullmatch(r"[A-Za-z0-9+/=]{20,}", run):
                continue  # likely base64 blob
            filtered.append(run)
        return " ".join(filtered)

    # ── Brain / memory files ─────────────────────────────────────────────

    def _collect_brain_files(self, app_dir: Path, source_label: str) -> list[Memory]:
        memories: list[Memory] = []
        brain_dir = app_dir / "brain"
        if not brain_dir.is_dir():
            return memories

        for conv_brain in brain_dir.iterdir():
            if not conv_brain.is_dir():
                continue
            conversation_id = conv_brain.name
            for mem_file in conv_brain.iterdir():
                if not mem_file.is_file():
                    continue
                try:
                    content = mem_file.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                if not content.strip():
                    continue
                mem = Memory(
                    type=MemoryType.ANTIGRAVITY_MEMORY,
                    source_node=self.config.node_id,
                    source_path=str(mem_file),
                    workspace=self._workspace_from_conversation_id(conversation_id),
                    title=f"antigravity-memory:{mem_file.name}",
                    content=content[:_MAX_TURN_BYTES],
                    metadata={
                        "source": source_label,
                        "conversation_id": conversation_id,
                        "memory_file": mem_file.name,
                    },
                    tags=[source_label, "brain"],
                )
                memories.append(mem)
        return memories

    def _collect_global_gemini_md(self) -> list[Memory]:
        memories: list[Memory] = []
        for path in (
            self.agy_dir / "GEMINI.md",
            self.agy_dir / "antigravity" / "GEMINI.md",
            self.agy_dir / "config" / "GEMINI.md",
        ):
            if not path.is_file():
                continue
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if not content.strip():
                continue
            memories.append(
                Memory(
                    type=MemoryType.ANTIGRAVITY_MEMORY,
                    source_node=self.config.node_id,
                    source_path=str(path),
                    workspace="",
                    title="GEMINI.md (global identity)",
                    content=content[:_MAX_TURN_BYTES],
                    metadata={
                        "source": "antigravity-global",
                        "memory_file": "GEMINI.md",
                    },
                    tags=["antigravity", "gemini-md", "identity"],
                )
            )
        return memories

    def _workspace_from_conversation_id(self, conversation_id: str) -> str:
        """Try to resolve a workspace name from a conversation id via CLI cache."""
        cache_file = self.agy_dir / "antigravity-cli" / "cache" / "last_conversations.json"
        if cache_file.exists():
            try:
                data = json.loads(cache_file.read_text(encoding="utf-8"))
                for path, cid in data.items():
                    if cid == conversation_id:
                        return Path(path).name or path
            except (json.JSONDecodeError, OSError):
                pass
        return ""

    # ── Project / knowledge context ──────────────────────────────────────

    def _collect_project_context(self, app_dir: Path, source_label: str) -> list[Memory]:
        memories: list[Memory] = []
        projects_dir = app_dir / "config" / "projects"
        if not projects_dir.is_dir():
            return memories

        for proj_file in projects_dir.glob("*.json"):
            try:
                content = proj_file.read_text(encoding="utf-8", errors="replace")
                data = json.loads(content)
            except (json.JSONDecodeError, OSError):
                continue

            title = data.get("name") or proj_file.stem
            text_body = content
            # If the project file has a free-form description / notes, prefer it
            notes = data.get("notes") or data.get("description") or ""
            if notes:
                text_body = f"{notes}\n\n{content}"

            memories.append(
                Memory(
                    type=MemoryType.ANTIGRAVITY_KNOWLEDGE,
                    source_node=self.config.node_id,
                    source_path=str(proj_file),
                    workspace=proj_file.stem,
                    title=f"antigravity-project:{title}",
                    content=text_body[:_MAX_TURN_BYTES],
                    metadata={
                        "source": source_label,
                        "project": proj_file.stem,
                        **{k: v for k, v in data.items() if isinstance(v, (str, int, bool, float))},
                    },
                    tags=[source_label, "project"],
                )
            )
        return memories

    def _collect_workspace_mcp_configs(self) -> list[Memory]:
        """Collect ``.antigravity/mcp.json`` files from known workspaces."""
        memories: list[Memory] = []
        workspace_roots = self._find_workspace_roots()
        for root in workspace_roots:
            mcp_file = root / ".antigravity" / "mcp.json"
            if not mcp_file.is_file():
                continue
            try:
                content = mcp_file.read_text(encoding="utf-8", errors="replace")
                data = json.loads(content)
            except (json.JSONDecodeError, OSError):
                continue
            servers = list(data.get("mcpServers", {}).keys())
            memories.append(
                Memory(
                    type=MemoryType.ANTIGRAVITY_KNOWLEDGE,
                    source_node=self.config.node_id,
                    source_path=str(mcp_file),
                    workspace=root.name,
                    title=".antigravity/mcp.json",
                    content=content[:_MAX_TURN_BYTES],
                    metadata={
                        "source": "antigravity-workspace",
                        "mcp_servers": servers,
                    },
                    tags=["antigravity", "mcp"],
                )
            )
        return memories

    def _find_workspace_roots(self) -> list[Path]:
        """Discover workspace roots from VS Code storage (same as CopilotCollector)."""
        roots = []
        vscode_storage = self.config.vscode_user_dir / "workspaceStorage"
        if vscode_storage.exists():
            for ws_dir in vscode_storage.iterdir():
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
                        continue
        return roots
