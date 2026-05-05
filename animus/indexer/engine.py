"""Index engine — SQLite FTS5 full-text search for memories."""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ..collector.models import Memory, MemoryType
from .parser import extract_searchable_text, extract_tags

logger = logging.getLogger("animus.indexer")

# Maximum time (in seconds) for a single FTS query before interruption.
_FTS_QUERY_TIMEOUT_SECONDS = 5
# Progress handler callback interval (SQLite VM instructions between checks).
_PROGRESS_HANDLER_INTERVAL = 10_000


class IndexEngine:
    """SQLite FTS5-based memory index — Eagle Vision."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._conn: Optional[sqlite3.Connection] = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._init_schema()
        return self._conn

    def _init_schema(self) -> None:
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS memories (
                id          TEXT PRIMARY KEY,
                type        TEXT NOT NULL,
                source_node TEXT NOT NULL,
                source_path TEXT DEFAULT '',
                workspace   TEXT DEFAULT '',
                timestamp   TEXT NOT NULL,
                title       TEXT DEFAULT '',
                content     TEXT NOT NULL,
                metadata    TEXT DEFAULT '{}',
                tags        TEXT DEFAULT '[]',
                sequence    INTEGER DEFAULT 0,
                synced      INTEGER DEFAULT 0,
                created_at  TEXT DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_memories_type ON memories(type);
            CREATE INDEX IF NOT EXISTS idx_memories_node ON memories(source_node);
            CREATE INDEX IF NOT EXISTS idx_memories_workspace ON memories(workspace);
            CREATE INDEX IF NOT EXISTS idx_memories_synced ON memories(synced);

            CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
                title, content, tags, workspace,
                content='memories',
                content_rowid='rowid',
                tokenize='porter unicode61'
            );

            -- Triggers to keep FTS in sync
            CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
                INSERT INTO memories_fts(rowid, title, content, tags, workspace)
                VALUES (new.rowid, new.title, new.content, new.tags, new.workspace);
            END;

            CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
                INSERT INTO memories_fts(memories_fts, rowid, title, content, tags, workspace)
                VALUES ('delete', old.rowid, old.title, old.content, old.tags, old.workspace);
            END;

            CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
                INSERT INTO memories_fts(memories_fts, rowid, title, content, tags, workspace)
                VALUES ('delete', old.rowid, old.title, old.content, old.tags, old.workspace);
                INSERT INTO memories_fts(rowid, title, content, tags, workspace)
                VALUES (new.rowid, new.title, new.content, new.tags, new.workspace);
            END;

            -- Sync state tracking
            CREATE TABLE IF NOT EXISTS sync_state (
                node_id     TEXT PRIMARY KEY,
                last_sync   TEXT,
                last_mem_id TEXT DEFAULT '',
                mem_count   INTEGER DEFAULT 0
            );
        """)

    def index_memory(self, memory: Memory, *, synced: bool = False) -> bool:
        """Index a single memory. Returns True if new, False if duplicate.

        Pass ``synced=True`` when the memory was received from a peer (i.e.
        on the hub side) — there is nowhere else to push it to, so it must
        not be reported as ``Pending`` in the UI.
        """
        # Auto-extract tags
        memory.tags = extract_tags(memory)
        # Clean content for search
        searchable = extract_searchable_text(memory)

        with self._lock:
            try:
                cursor = self.conn.execute(
                    """INSERT OR IGNORE INTO memories
                       (id, type, source_node, source_path, workspace, timestamp,
                        title, content, metadata, tags, sequence, synced)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        memory.id,
                        memory.type.value,
                        memory.source_node,
                        memory.source_path,
                        memory.workspace,
                        memory.timestamp.isoformat(),
                        memory.title,
                        searchable,
                        json.dumps(memory.metadata),
                        json.dumps(memory.tags),
                        memory.sequence,
                        1 if synced else 0,
                    ),
                )
                self.conn.commit()
                return cursor.rowcount > 0
            except sqlite3.IntegrityError:
                return False

    def index_batch(self, memories: list[Memory], *, synced: bool = False) -> int:
        """Index a batch of memories. Returns count of new memories.

        Pass ``synced=True`` on the hub-side ingest path so received
        memories don't appear as ``Pending`` in the admin UI.
        """
        new_count = 0
        for mem in memories:
            if self.index_memory(mem, synced=synced):
                new_count += 1
        return new_count

    @staticmethod
    def _build_fts_query(query: str) -> str:
        """Convert a natural-language query into a safe FTS5 MATCH expression.

        FTS5 has a small DSL where ``"`` introduces a phrase, ``-`` is NOT,
        ``*`` is a prefix, and unquoted tokens are AND'd together. Naively
        wrapping the user input in quotes (the previous behaviour) forced
        contiguous-phrase matching, so multi-word queries like
        ``"animus peer installer kit"`` returned zero hits even when each
        word existed in the index — which broke RAG recall completely.

        This helper:
        * strips FTS metacharacters,
        * tokenizes on whitespace and keeps tokens >=2 chars,
        * for a single token: returns it as a prefix (``token*``),
        * for multiple tokens: joins them with ``OR`` so any term matches
          (FTS5 ranking still surfaces the rows that match the most).

        If the cleaned query has no usable tokens, returns an empty string
        — callers should fall back to a non-FTS path.
        """
        import re as _re

        if not query or not query.strip():
            return ""

        # Remove characters that have meaning in the FTS5 query syntax.
        cleaned = _re.sub(r'[\"\*\^\(\)\-\:\+]', " ", query)
        # Tokenize and keep only alphanumeric/underscore characters per token —
        # FTS5 unicode61 tokenizer ignores other punctuation but the MATCH
        # parser itself rejects bare apostrophes/commas/etc.
        raw_tokens = cleaned.split()
        tokens = []
        for t in raw_tokens:
            tok = _re.sub(r"[^\w]", "", t, flags=_re.UNICODE)
            if len(tok) >= 2:
                tokens.append(tok)
        # Drop very common English/Portuguese stopwords that flood results
        stopwords = {
            "the", "and", "for", "with", "from", "this", "that", "are",
            "was", "were", "have", "has", "had", "but", "not", "can",
            "is", "of", "in", "on", "at", "to", "by", "be", "or", "an",
            "as", "it", "if", "do", "so", "we", "you", "your",
            "como", "para", "com", "uma", "que", "dos", "das", "por",
            "ele", "ela", "isso", "isto", "nao", "tem",
        }
        tokens = [t for t in tokens if t.lower() not in stopwords]

        if not tokens:
            return ""

        # Cap tokens to keep MATCH expression compact
        tokens = tokens[:16]

        if len(tokens) == 1:
            return f"{tokens[0]}*"

        # OR-of-terms — broader than the previous phrase match while still
        # letting FTS5's BM25 ranker prioritize records matching more terms.
        return " OR ".join(tokens)

    def search(
        self,
        query: str,
        *,
        mem_type: Optional[str] = None,
        workspace: Optional[str] = None,
        node: Optional[str] = None,
        tags: Optional[list[str]] = None,
        limit: int = 20,
    ) -> list[dict]:
        """Full-text search across all memories — Eagle Vision."""
        # Clamp limit to prevent excessive result sets
        limit = min(max(1, limit), 200)

        match_expr = self._build_fts_query(query)
        if not match_expr:
            return []

        conditions = []
        params: list = []

        # FTS query
        base_sql = """
            SELECT m.*, rank
            FROM memories_fts fts
            JOIN memories m ON m.rowid = fts.rowid
            WHERE memories_fts MATCH ?
        """
        params.append(match_expr)

        if mem_type:
            conditions.append("m.type = ?")
            params.append(mem_type)
        if workspace:
            conditions.append("m.workspace = ?")
            params.append(workspace)
        if node:
            conditions.append("m.source_node = ?")
            params.append(node)

        if conditions:
            base_sql += " AND " + " AND ".join(conditions)

        base_sql += " ORDER BY rank LIMIT ?"
        params.append(limit)

        with self._lock:
            # Install a progress handler to enforce a query time limit.
            # The callback is invoked every _PROGRESS_HANDLER_INTERVAL VM
            # instructions; returning non-zero aborts the running statement.
            import time as _time
            deadline = _time.monotonic() + _FTS_QUERY_TIMEOUT_SECONDS

            def _timeout_handler() -> int:
                return 1 if _time.monotonic() > deadline else 0

            self.conn.set_progress_handler(_timeout_handler, _PROGRESS_HANDLER_INTERVAL)
            try:
                rows = self.conn.execute(base_sql, params).fetchall()
                return [dict(r) for r in rows]
            except sqlite3.OperationalError as exc:
                if "interrupt" in str(exc).lower():
                    logger.warning("FTS query timed out after %ds: %s", _FTS_QUERY_TIMEOUT_SECONDS, query[:100])
                    return []
                raise
            finally:
                self.conn.set_progress_handler(None, 0)

    def get_unsynced(self, limit: int = 100) -> list[dict]:
        """Get memories not yet synced to hub."""
        with self._lock:
            rows = self.conn.execute(
                "SELECT * FROM memories WHERE synced = 0 ORDER BY timestamp LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    def mark_synced(self, memory_ids: list[str]) -> None:
        """Mark memories as synced."""
        with self._lock:
            placeholders = ",".join("?" for _ in memory_ids)
            self.conn.execute(
                f"UPDATE memories SET synced = 1 WHERE id IN ({placeholders})",
                memory_ids,
            )
            self.conn.commit()

    def get_stats(self) -> dict:
        """Get index statistics."""
        with self._lock:
            row = self.conn.execute(
                """SELECT
                    COUNT(*) as total,
                    COUNT(DISTINCT source_node) as nodes,
                    COUNT(DISTINCT workspace) as workspaces,
                    SUM(CASE WHEN synced = 0 THEN 1 ELSE 0 END) as unsynced
                   FROM memories"""
            ).fetchone()
            type_counts = self.conn.execute(
                "SELECT type, COUNT(*) as cnt FROM memories GROUP BY type"
            ).fetchall()
            return {
                "total_memories": row["total"],
                "unique_nodes": row["nodes"],
                "unique_workspaces": row["workspaces"],
                "unsynced": row["unsynced"],
                "by_type": {r["type"]: r["cnt"] for r in type_counts},
            }

    def get_recent(self, limit: int = 20) -> list[dict]:
        """Get most recent memories."""
        with self._lock:
            rows = self.conn.execute(
                "SELECT * FROM memories ORDER BY timestamp DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(r) for r in rows]

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None
