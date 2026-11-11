"""Memory parser — decodes different memory formats into indexed content."""

from __future__ import annotations

import json
import re
from typing import Any

from ..collector.models import Memory, MemoryType


def extract_searchable_text(memory: Memory) -> str:
    """Extract clean searchable text from a memory."""
    content = memory.content
    if memory.type == MemoryType.OBSIDIAN_NOTE:
        # The memory payload is also the sync payload. FTS5 can tokenize Markdown
        # directly; flattening it here irreversibly loses diagrams, code and tables.
        return content

    if memory.type in (MemoryType.COPILOT_DEBUG, MemoryType.COPILOT_CHAT):
        content = _clean_log_content(content)
    elif memory.type == MemoryType.CLAUDE_CHAT:
        # Claude turns are already cleaned by the collector; keep markdown.
        pass
    elif memory.type in (
        MemoryType.WORKSPACE_MEMORY,
        MemoryType.SESSION_NOTE,
        MemoryType.USER_NOTE,
        MemoryType.REPO_NOTE,
        MemoryType.PROMPT_FILE,
        MemoryType.AGENT_FILE,
        MemoryType.CLAUDE_MEMORY,
    ):
        content = _clean_markdown(content)
    elif memory.type == MemoryType.MCP_KNOWLEDGE:
        content = _clean_knowledge_graph(content)

    return content.strip()


def extract_tags(memory: Memory) -> list[str]:
    """Auto-extract tags from memory content.

    We also stamp an origin tag (``claude`` / ``copilot``) on every memory.
    The Neural Map's session ↔ session edges require ≥2 shared tags, and
    without an origin tag a Claude session and a Copilot session that talk
    about the same topic only share one language tag — they'd never get
    cross-linked even though they're clearly about the same thing.
    """
    tags = list(memory.tags)
    text = memory.content.lower()

    # Origin tag — derived from MemoryType so the rule stays in one place.
    if memory.type in (MemoryType.CLAUDE_CHAT, MemoryType.CLAUDE_MEMORY):
        tags.append("claude")
    elif memory.type in (
        MemoryType.COPILOT_CHAT,
        MemoryType.COPILOT_DEBUG,
        MemoryType.COPILOT_INLINE,
        MemoryType.COPILOT_CLI_CHAT,
    ):
        tags.append("copilot")

    # Detect programming languages
    lang_patterns = {
        "python": r"\b(python|\.py|django|fastapi|flask)\b",
        "javascript": r"\b(javascript|\.js|node|react|vue|angular)\b",
        "typescript": r"\b(typescript|\.ts|\.tsx)\b",
        "rust": r"\b(rust|cargo|\.rs)\b",
        "docker": r"\b(docker|dockerfile|compose)\b",
        "sql": r"\b(sql|postgres|sqlite|mysql)\b",
        "git": r"\b(git|commit|branch|merge|push)\b",
    }
    for tag, pattern in lang_patterns.items():
        if re.search(pattern, text):
            tags.append(tag)

    # Detect topics
    topic_patterns = {
        "debug": r"\b(error|bug|fix|debug|traceback|exception)\b",
        "deploy": r"\b(deploy|ci/cd|pipeline|production|staging)\b",
        "security": r"\b(security|auth|token|encrypt|password|owasp)\b",
        "api": r"\b(api|endpoint|rest|graphql|grpc)\b",
        "test": r"\b(test|pytest|unittest|mock|assert)\b",
    }
    for tag, pattern in topic_patterns.items():
        if re.search(pattern, text):
            tags.append(tag)

    return list(set(tags))


def _clean_log_content(content: str) -> str:
    """Clean log/JSON content for indexing."""
    try:
        data = json.loads(content)
        parts = []
        for key in ("content", "text", "message", "type", "event", "title"):
            if key in data and isinstance(data[key], str):
                parts.append(data[key])
        return " ".join(parts) if parts else content
    except (json.JSONDecodeError, TypeError):
        return content


def _clean_markdown(content: str) -> str:
    """Clean markdown for indexing — keep text, strip formatting."""
    # Remove YAML frontmatter
    content = re.sub(r"^---\n.*?\n---\n", "", content, flags=re.DOTALL)
    # Remove code blocks but keep inline code
    content = re.sub(r"```[\s\S]*?```", " [code] ", content)
    # Remove HTML tags
    content = re.sub(r"<[^>]+>", " ", content)
    # Simplify multiple whitespace
    content = re.sub(r"\s+", " ", content)
    return content


def _clean_knowledge_graph(content: str) -> str:
    """Clean MCP knowledge graph entities."""
    try:
        data = json.loads(content)
        if isinstance(data, dict):
            parts = [data.get("name", ""), data.get("entityType", "")]
            parts.extend(data.get("observations", []))
            return " ".join(str(p) for p in parts if p)
    except (json.JSONDecodeError, TypeError):
        pass
    return content
