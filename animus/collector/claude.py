"""Claude Code memory collector — extracts memories from ~/.claude/.

Claude Code stores per-project state under ``~/.claude/projects/<encoded-cwd>/``:

* ``<session-uuid>.jsonl`` — append-only transcripts of every user/assistant
  turn (one JSON object per line). Each record carries ``type``, ``message``
  (with ``role`` and ``content`` — a list of ``{type: text|tool_use|...}``
  parts), ``cwd``, ``sessionId``, ``timestamp`` and a chat-thread ``uuid``.

* ``memory/MEMORY.md`` + ``memory/<slug>.md`` — the auto-memory store. Each
  ``.md`` file uses YAML frontmatter with ``name``, ``description`` and
  ``metadata.type`` (one of ``user``, ``feedback``, ``project``, ``reference``).
  ``MEMORY.md`` is the index that points at the others.

The directory name under ``projects/`` is Claude Code's URL-encoded cwd
(``/`` → ``-``; ``/root/foo`` → ``-root-foo``). We best-effort decode it so
the workspace label stays human-readable.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import AnimusConfig
from .models import Memory, MemoryType

logger = logging.getLogger("animus.collector.claude")

# Cap individual transcript turns at 256 KB so a 1 MB file body in a tool
# call doesn't blow the memory record (the model is sized at 512 KB max).
_MAX_TURN_BYTES = 256_000
# Cap session-title derivation at this many chars from the first user prompt.
_TITLE_CHARS = 120


def _decode_project_dir(name: str) -> str:
    """Best-effort decode of Claude's project dir name back to a cwd label.

    Claude encodes the cwd by replacing every ``/`` with ``-`` (so ``/`` itself
    becomes ``-`` and ``/root/foo`` becomes ``-root-foo``). We can't recover
    real ``-`` characters that were already in the path, but the typical case
    (``/root/repo/project``) round-trips cleanly enough to be useful.
    """
    if not name or name == "-":
        return "/"
    if name.startswith("-"):
        return "/" + name[1:].replace("-", "/")
    return name


def _flatten_content(content: Any) -> tuple[str, list[dict]]:
    """Pull plain text + tool calls out of a Claude message ``content`` field.

    Returns ``(text, tool_calls)`` where ``tool_calls`` is a list of
    ``{name, input}`` dicts. Claude Code uses Anthropic's structured content
    parts (``[{type: "text", text: ...}, {type: "tool_use", name, input}, ...]``).
    """
    if content is None:
        return "", []
    if isinstance(content, str):
        return content, []
    if not isinstance(content, list):
        return str(content), []

    texts: list[str] = []
    tools: list[dict] = []
    for part in content:
        if not isinstance(part, dict):
            texts.append(str(part))
            continue
        ptype = part.get("type")
        if ptype == "text":
            texts.append(part.get("text", ""))
        elif ptype == "tool_use":
            tools.append({
                "name": part.get("name", "tool"),
                "input": part.get("input"),
            })
        elif ptype == "tool_result":
            # Tool results are echoed back into the user role; carry them as
            # text so search still hits the output bodies.
            tr = part.get("content")
            if isinstance(tr, list):
                tr_text, _ = _flatten_content(tr)
                texts.append(tr_text)
            elif isinstance(tr, str):
                texts.append(tr)
        elif ptype == "thinking":
            # Skip reasoning — it's already absent on most models and
            # indexing it adds noise without much retrieval value.
            continue
    return "\n".join(t for t in texts if t).strip(), tools


def _format_tool_blocks(tools: list[dict]) -> str:
    """Render tool calls as fenced JSON so search still hits arguments."""
    if not tools:
        return ""
    blocks = []
    for tc in tools:
        name = tc.get("name") or "tool"
        args = tc.get("input")
        try:
            args_json = json.dumps(args, ensure_ascii=False, indent=2)
        except (TypeError, ValueError):
            args_json = str(args)
        blocks.append(f"\n\n**🔧 Tool call: `{name}`**\n\n```json\n{args_json}\n```")
    return "".join(blocks)


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Strip Claude memory YAML frontmatter and return ``(meta, body)``.

    The frontmatter is a small fixed subset (``name``, ``description``,
    ``metadata.type``) so a regex-based parser is enough — we keep this
    collector dependency-free of PyYAML.
    """
    if not text.startswith("---"):
        return {}, text
    m = re.match(r"^---\r?\n(.*?)\r?\n---\r?\n?(.*)$", text, re.DOTALL)
    if not m:
        return {}, text
    fm_block, body = m.group(1), m.group(2)
    meta: dict[str, Any] = {}
    current_parent: dict[str, Any] | None = None
    for line in fm_block.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        # Detect "key:" with no value (start of a sub-block, e.g. ``metadata:``)
        bare = re.match(r"^(\w[\w-]*):\s*$", line)
        if bare:
            current_parent = {}
            meta[bare.group(1)] = current_parent
            continue
        # Indented key: value -> nest under current_parent
        indented = re.match(r"^\s+(\w[\w-]*):\s*(.+?)\s*$", line)
        if indented and current_parent is not None:
            current_parent[indented.group(1)] = indented.group(2).strip().strip('"').strip("'")
            continue
        # Top-level key: value
        flat = re.match(r"^(\w[\w-]*):\s*(.+?)\s*$", line)
        if flat:
            current_parent = None
            meta[flat.group(1)] = flat.group(2).strip().strip('"').strip("'")
    return meta, body.lstrip("\n")


class ClaudeCollector:
    """Collects memories from Claude Code's local state.

    Two sources:

    * Transcripts (``~/.claude/projects/<enc>/<session>.jsonl``) — one
      :class:`Memory` per user/assistant turn, tagged with a derived
      ``session_title`` so the Neural Map can label sessions by topic
      instead of by opaque UUID.

    * Auto-memory files (``~/.claude/projects/<enc>/memory/<slug>.md``) —
      one :class:`Memory` per file, with ``memory_kind`` (user/feedback/
      project/reference) and ``theme`` (the human description) carried in
      metadata.
    """

    def __init__(self, config: AnimusConfig):
        self.config = config
        self.claude_dir = config.claude_data_dir
        self.projects_dir = self.claude_dir / "projects"

    def collect_all(self) -> list[Memory]:
        memories: list[Memory] = []
        if not self.projects_dir.exists():
            return memories

        for proj_dir in self.projects_dir.iterdir():
            if not proj_dir.is_dir():
                continue
            if self.config.collect_claude_chat:
                try:
                    memories.extend(self._collect_session_transcripts(proj_dir))
                except Exception:
                    logger.debug(
                        "Failed transcripts in %s", proj_dir, exc_info=True
                    )
            if self.config.collect_claude_memory:
                try:
                    memories.extend(self._collect_memory_files(proj_dir))
                except Exception:
                    logger.debug(
                        "Failed memory files in %s", proj_dir, exc_info=True
                    )
        return memories

    # ── Transcripts ──────────────────────────────────────────────────────

    def _collect_session_transcripts(self, proj_dir: Path) -> list[Memory]:
        memories: list[Memory] = []
        workspace = _decode_project_dir(proj_dir.name)

        for jsonl in proj_dir.glob("*.jsonl"):
            if not jsonl.is_file() or jsonl.stat().st_size == 0:
                continue
            try:
                memories.extend(self._parse_transcript(jsonl, workspace))
            except Exception:
                logger.debug("Failed transcript %s", jsonl, exc_info=True)
        return memories

    def _parse_transcript(self, path: Path, workspace: str) -> list[Memory]:
        memories: list[Memory] = []
        session_id = path.stem  # filename = UUID
        session_title = ""
        # Workspace can be lossy when decoded from the dir name (Claude maps
        # both ``/`` and ``-`` to ``-``). Override with the first record's
        # ``cwd`` when present — it's the lossless source of truth.
        resolved_workspace = workspace

        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return memories

        seq = 0
        for raw_line in content.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(data, dict):
                continue
            rec_type = data.get("type")
            # Pick the cwd off the first record that has one — it's the
            # authoritative workspace label (the directory name is lossy).
            cwd = data.get("cwd")
            if cwd and resolved_workspace == workspace:
                resolved_workspace = cwd
            # Skip queue-operation / housekeeping records that have no payload.
            if rec_type not in {"user", "assistant"}:
                continue

            msg = data.get("message") or {}
            if not isinstance(msg, dict):
                continue
            role = msg.get("role") or rec_type
            text, tools = _flatten_content(msg.get("content"))
            body = (text or "") + _format_tool_blocks(tools)
            if not body.strip():
                continue

            # Capture the first user prompt as the session's title — that's
            # how a human remembers the chat ("the one where I asked about X").
            if not session_title and role == "user":
                # First user text becomes the session label.
                head = (text or body).strip().splitlines()[0] if (text or body).strip() else ""
                session_title = head[:_TITLE_CHARS]

            ts = data.get("timestamp")
            try:
                timestamp = (
                    datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    if isinstance(ts, str)
                    else datetime.now(timezone.utc)
                )
            except ValueError:
                timestamp = datetime.now(timezone.utc)

            title_text = (text[:80] if text else (role or f"turn-{seq}"))
            mem = Memory(
                type=MemoryType.CLAUDE_CHAT,
                source_node=self.config.node_id,
                source_path=str(path),
                workspace=resolved_workspace,
                title=f"claude:{role}:{title_text}",
                content=body[:_MAX_TURN_BYTES],
                timestamp=timestamp,
                metadata={
                    "source": "claude-transcript",
                    "session": session_id,
                    "session_title": session_title,
                    "role": role,
                    "model": msg.get("model"),
                    "cwd": data.get("cwd"),
                    "git_branch": data.get("gitBranch"),
                    "turn": seq,
                    "tool_calls": [t["name"] for t in tools],
                },
                sequence=seq,
            )
            memories.append(mem)
            seq += 1

        # Second pass: backfill session_title on early turns where we hadn't
        # seen a user message yet (transcripts very occasionally start with
        # an assistant turn or a system event).
        if session_title:
            for m in memories:
                if not m.metadata.get("session_title"):
                    m.metadata["session_title"] = session_title

        return memories

    # ── Memory files ─────────────────────────────────────────────────────

    def _collect_memory_files(self, proj_dir: Path) -> list[Memory]:
        memories: list[Memory] = []
        mem_dir = proj_dir / "memory"
        if not mem_dir.is_dir():
            return memories

        workspace = _decode_project_dir(proj_dir.name)

        for md_file in mem_dir.rglob("*.md"):
            try:
                text = md_file.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue

            fm, body = _parse_frontmatter(text)
            inner_meta = fm.get("metadata") if isinstance(fm.get("metadata"), dict) else {}
            memory_kind = (inner_meta.get("type") or "").strip().lower()
            theme = (fm.get("description") or "").strip()
            mem_name = (fm.get("name") or md_file.stem).strip()

            is_index = md_file.name == "MEMORY.md"
            title = mem_name
            if is_index:
                title = "MEMORY.md (index)"
                memory_kind = memory_kind or "index"

            try:
                mtime = datetime.fromtimestamp(
                    md_file.stat().st_mtime, tz=timezone.utc
                )
            except OSError:
                mtime = datetime.now(timezone.utc)

            mem = Memory(
                type=MemoryType.CLAUDE_MEMORY,
                source_node=self.config.node_id,
                source_path=str(md_file),
                workspace=workspace,
                title=title,
                content=body or text,
                timestamp=mtime,
                metadata={
                    "source": "claude-memory",
                    "is_index": is_index,
                    "memory_kind": memory_kind or "unknown",
                    "theme": theme,
                    "name": mem_name,
                    "frontmatter": fm,
                },
                tags=[t for t in [memory_kind, "claude-memory"] if t],
            )
            memories.append(mem)
        return memories
