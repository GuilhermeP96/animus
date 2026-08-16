"""GitHub Copilot CLI memory collector — extracts memories from ~/.copilot/.

The Copilot CLI (the terminal agent) keeps its local state under
``~/.copilot/``:

* ``session-store.db`` — SQLite (WAL) with the durable conversation store:

  - ``sessions(id, cwd, repository, branch, summary, created_at, updated_at)``
  - ``turns(session_id, turn_index, user_message, assistant_response, timestamp)``
  - ``checkpoints(session_id, checkpoint_number, title, overview, work_done,
    technical_details, important_files, next_steps, created_at)``

  We emit one ``copilot_cli_chat`` memory per turn and one per checkpoint.
  The db is opened read-only (``mode=ro``) so a running CLI is never
  disturbed; any lock/schema surprise just yields zero memories.

* ``command-history-state.json`` is intentionally skipped — every prompt
  there is already a turn in ``session-store.db``.

Per-session ``session-state/<id>/`` dirs (events.jsonl, rewind snapshots)
duplicate the same turns at higher granularity and are skipped for the
same reason.

The collector mirrors the Claude/Antigravity collectors: best-effort,
never crashes the sync cycle, caps individual records at 256 KB.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from ..config import AnimusConfig
from .models import Memory, MemoryType

logger = logging.getLogger("animus.collector.copilot_cli")

_MAX_TURN_BYTES = 256_000
_TITLE_CHARS = 120


def _parse_ts(value: Any) -> datetime:
    """Parse the CLI's timestamp text (``datetime('now')`` → UTC naïve)."""
    if not value:
        return datetime.now(timezone.utc)
    text = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            dt = datetime.strptime(text, fmt)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return datetime.now(timezone.utc)


class CopilotCliCollector:
    """Collects genetic memories from GitHub Copilot CLI local state."""

    def __init__(self, config: AnimusConfig):
        self.config = config
        self.cli_dir = Path(config.copilot_cli_data_dir)

    # ── Public entrypoint ────────────────────────────────────────────────

    def collect_all(self) -> list[Memory]:
        if not self.config.collect_copilot_cli_chat:
            return []
        if not self.cli_dir.is_dir():
            return []
        try:
            return self._collect_session_store(self.cli_dir / "session-store.db")
        except Exception:
            logger.debug("Failed Copilot CLI session-store", exc_info=True)
            return []

    # ── session-store.db ─────────────────────────────────────────────────

    def _collect_session_store(self, db_path: Path) -> list[Memory]:
        memories: list[Memory] = []
        if not db_path.is_file():
            return memories

        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        except sqlite3.Error:
            return memories

        try:
            conn.row_factory = sqlite3.Row
            tables = {
                r["name"]
                for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            if "sessions" not in tables or "turns" not in tables:
                return memories

            sessions = self._load_sessions(conn)
            memories.extend(self._collect_turns(conn, db_path, sessions))
            if "checkpoints" in tables:
                memories.extend(self._collect_checkpoints(conn, db_path, sessions))
        except sqlite3.Error:
            logger.debug("Copilot CLI session-store read error", exc_info=True)
        finally:
            conn.close()

        return memories

    def _load_sessions(self, conn: sqlite3.Connection) -> dict[str, dict[str, Any]]:
        sessions: dict[str, dict[str, Any]] = {}
        for row in conn.execute(
            "SELECT id, cwd, repository, branch, summary, created_at FROM sessions"
        ):
            sessions[row["id"]] = dict(row)
        return sessions

    def _workspace_label(self, session: dict[str, Any]) -> str:
        cwd = session.get("cwd") or ""
        if cwd:
            return Path(cwd).name or cwd
        repo = session.get("repository") or ""
        return repo.rstrip("/").rsplit("/", 1)[-1] if repo else "copilot-cli"

    def _session_title(self, session: dict[str, Any], fallback: str) -> str:
        summary = (session.get("summary") or "").strip()
        if summary:
            return summary[:_TITLE_CHARS]
        return fallback[:_TITLE_CHARS]

    def _collect_turns(
        self,
        conn: sqlite3.Connection,
        db_path: Path,
        sessions: dict[str, dict[str, Any]],
    ) -> list[Memory]:
        memories: list[Memory] = []
        first_prompt: dict[str, str] = {}

        rows = conn.execute(
            "SELECT session_id, turn_index, user_message, assistant_response, timestamp "
            "FROM turns ORDER BY session_id, turn_index"
        )
        for row in rows:
            user = (row["user_message"] or "").strip()
            assistant = (row["assistant_response"] or "").strip()
            if not user and not assistant:
                continue

            sid = row["session_id"]
            if user and sid not in first_prompt:
                first_prompt[sid] = user

            session = sessions.get(sid, {})
            workspace = self._workspace_label(session)
            parts = []
            if user:
                parts.append(f"user: {user}")
            if assistant:
                parts.append(f"assistant: {assistant}")
            body = "\n\n".join(parts)

            title_src = user or assistant
            memories.append(
                Memory(
                    type=MemoryType.COPILOT_CLI_CHAT,
                    source_node=self.config.node_id,
                    source_path=str(db_path),
                    workspace=workspace,
                    title=f"copilot-cli:{title_src[:80].replace(chr(10), ' ')}",
                    content=body[:_MAX_TURN_BYTES],
                    timestamp=_parse_ts(row["timestamp"]),
                    metadata={
                        "source": "copilot-cli",
                        "session": sid,
                        "session_title": self._session_title(session, first_prompt.get(sid, "")),
                        "turn": row["turn_index"],
                        "cwd": session.get("cwd"),
                        "repository": session.get("repository"),
                        "git_branch": session.get("branch"),
                    },
                    sequence=row["turn_index"] or 0,
                    tags=["copilot-cli"],
                )
            )
        return memories

    def _collect_checkpoints(
        self,
        conn: sqlite3.Connection,
        db_path: Path,
        sessions: dict[str, dict[str, Any]],
    ) -> list[Memory]:
        memories: list[Memory] = []
        rows = conn.execute(
            "SELECT session_id, checkpoint_number, title, overview, work_done, "
            "technical_details, important_files, next_steps, created_at "
            "FROM checkpoints ORDER BY session_id, checkpoint_number"
        )
        for row in rows:
            sid = row["session_id"]
            session = sessions.get(sid, {})
            sections = []
            for label, key in (
                ("Overview", "overview"),
                ("Work done", "work_done"),
                ("Technical details", "technical_details"),
                ("Important files", "important_files"),
                ("Next steps", "next_steps"),
            ):
                value = (row[key] or "").strip()
                if value:
                    sections.append(f"## {label}\n{value}")
            body = "\n\n".join(sections)
            if not body:
                continue

            title = (row["title"] or "").strip() or f"checkpoint {row['checkpoint_number']}"
            memories.append(
                Memory(
                    type=MemoryType.COPILOT_CLI_CHAT,
                    source_node=self.config.node_id,
                    source_path=str(db_path),
                    workspace=self._workspace_label(session),
                    title=f"copilot-cli:checkpoint:{title[:80]}",
                    content=body[:_MAX_TURN_BYTES],
                    timestamp=_parse_ts(row["created_at"]),
                    metadata={
                        "source": "copilot-cli",
                        "kind": "checkpoint",
                        "session": sid,
                        "session_title": self._session_title(session, title),
                        "checkpoint": row["checkpoint_number"],
                        "cwd": session.get("cwd"),
                        "repository": session.get("repository"),
                        "git_branch": session.get("branch"),
                    },
                    sequence=row["checkpoint_number"] or 0,
                    tags=["copilot-cli", "checkpoint"],
                )
            )
        return memories
