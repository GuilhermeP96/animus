"""Memory parser — decodes different memory formats into indexed content."""

from __future__ import annotations

import json
import re
from typing import Any

from ..collector.models import Memory, MemoryType


def extract_searchable_text(memory: Memory) -> str:
    """Extract clean searchable text from a memory."""
    content = memory.content

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
    """Auto-extract tags from memory content."""
    tags = list(memory.tags)
    text = memory.content.lower()

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
