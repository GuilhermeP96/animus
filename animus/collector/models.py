"""Memory data models — the DNA of Animus."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator

_MAX_CONTENT_SIZE = 512 * 1024  # 512 KB


class MemoryType(str, Enum):
    """Types of genetic memories."""

    COPILOT_CHAT = "copilot_chat"          # Chat conversations
    COPILOT_DEBUG = "copilot_debug"        # Debug/session logs
    COPILOT_INLINE = "copilot_inline"      # Inline completions context
    WORKSPACE_MEMORY = "workspace_memory"  # .instructions.md, copilot-instructions
    MCP_KNOWLEDGE = "mcp_knowledge"        # MCP memory server knowledge graph
    SESSION_NOTE = "session_note"          # /memories/session/ files
    USER_NOTE = "user_note"               # /memories/ persistent notes
    REPO_NOTE = "repo_note"               # /memories/repo/ files
    PROMPT_FILE = "prompt_file"           # .prompt.md files
    AGENT_FILE = "agent_file"             # .agent.md files
    CLAUDE_CHAT = "claude_chat"           # Claude Code session transcripts (.jsonl turns)
    CLAUDE_MEMORY = "claude_memory"       # Claude Code auto-memory .md files (frontmatter typed)


class Memory(BaseModel):
    """A single genetic memory — one interaction/artifact captured."""

    id: str = Field(default="", description="SHA-256 hash of content")
    type: MemoryType
    source_node: str = Field(description="Node ID that captured this memory")
    source_path: str = Field(default="", description="Original file path")
    workspace: str = Field(default="", description="Workspace/project name")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    title: str = ""
    content: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    sequence: int = 0  # Position within a conversation/session

    @field_validator("content")
    @classmethod
    def validate_content_size(cls, v: str) -> str:
        if len(v) > _MAX_CONTENT_SIZE:
            return v[:_MAX_CONTENT_SIZE]
        return v

    def model_post_init(self, __context: Any) -> None:
        if not self.id and self.content:
            raw = f"{self.type}:{self.source_path}:{self.content}"
            self.id = hashlib.sha256(raw.encode()).hexdigest()[:16]


class MemoryBatch(BaseModel):
    """A batch of memories for sync."""

    node_id: str
    node_name: str
    memories: list[Memory]
    batch_timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class SyncState(BaseModel):
    """Tracks what has been synced."""

    node_id: str
    last_sync: Optional[datetime] = None
    last_memory_id: str = ""
    memory_count: int = 0
