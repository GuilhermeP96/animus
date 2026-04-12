"""Index engine — SQLite FTS5 full-text search for memories."""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ..collector.models import Memory, MemoryType
from .parser import extract_searchable_text, extract_tags

logger = logging.getLogger("animus.indexer")


class IndexEngine:
    """SQLite FTS5-based memory index — Eagle Vision."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path))
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

    def index_memory(self, memory: Memory) -> bool:
        """Index a single memory. Returns True if new, False if duplicate."""
        # Auto-extract tags
        memory.tags = extract_tags(memory)
        # Clean content for search
        searchable = extract_searchable_text(memory)

        try:
            self.conn.execute(
                """INSERT OR IGNORE INTO memories
                   (id, type, source_node, source_path, workspace, timestamp,
                    title, content, metadata, tags, sequence)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                ),
            )
            self.conn.commit()
            return self.conn.total_changes > 0
        except sqlite3.IntegrityError:
            return False

    def index_batch(self, memories: list[Memory]) -> int:
        """Index a batch of memories. Returns count of new memories."""
        new_count = 0
        for mem in memories:
            if self.index_memory(mem):
                new_count += 1
        return new_count

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
        conditions = []
        params: list = []

        # FTS query
        base_sql = """
            SELECT m.*, rank
            FROM memories_fts fts
            JOIN memories m ON m.rowid = fts.rowid
            WHERE memories_fts MATCH ?
        """
        # Escape FTS special chars
        safe_query = query.replace('"', '""')
        params.append(f'"{safe_query}"')

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

        rows = self.conn.execute(base_sql, params).fetchall()
        return [dict(r) for r in rows]

    def get_unsynced(self, limit: int = 100) -> list[dict]:
        """Get memories not yet synced to hub."""
        rows = self.conn.execute(
            "SELECT * FROM memories WHERE synced = 0 ORDER BY timestamp LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def mark_synced(self, memory_ids: list[str]) -> None:
        """Mark memories as synced."""
        placeholders = ",".join("?" for _ in memory_ids)
        self.conn.execute(
            f"UPDATE memories SET synced = 1 WHERE id IN ({placeholders})",
            memory_ids,
        )
        self.conn.commit()

    def get_stats(self) -> dict:
        """Get index statistics."""
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
        rows = self.conn.execute(
            "SELECT * FROM memories ORDER BY timestamp DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None
