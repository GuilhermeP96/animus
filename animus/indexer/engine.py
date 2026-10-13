"""Index engine — SQLite FTS5 full-text search for memories."""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
import copy
from contextlib import closing
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
_STATS_TTL_SECONDS = 30.0
_STATS_QUERY_TIMEOUT_SECONDS = 2.0
_STATS_BUSY_TIMEOUT_SECONDS = 0.25


class StatsUnavailable(RuntimeError):
    """Safe bounded statistics failure; never include SQLite data or SQL."""

    def __init__(self, reason: str):
        super().__init__("Index statistics temporarily unavailable")
        self.reason = reason

    def payload(self) -> dict:
        return {"stats_status": "unavailable", "stats_degraded": True,
                "stats_reason": self.reason, "stats_age_seconds": None,
                "stats_collected_at": None, "stats_retry_after_seconds": 30,
                "total_memories": None, "unique_nodes": None,
                "unique_workspaces": None, "unsynced": None, "by_type": {}}


class IndexEngine:
    """SQLite FTS5-based memory index — Eagle Vision."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._conn: Optional[sqlite3.Connection] = None
        self._stats_cache: dict | None = None
        self._stats_empty_cached_at = 0.0
        self._stats_lock = threading.Lock()
        self._stats_generation = 0
        self._stats_last_error: str | None = None
        self._stats_retry_at = 0.0

    @property
    def _stats_cached_at(self) -> float:
        snapshot = self._stats_cache
        return snapshot['_cached_monotonic'] if snapshot else self._stats_empty_cached_at

    @_stats_cached_at.setter
    def _stats_cached_at(self, value: float) -> None:
        # Compatibility for fixture-clock controls. Production publishes the
        # timestamp, generation and counts in one atomic snapshot assignment.
        snapshot = self._stats_cache
        if snapshot is not None:
            self._stats_cache = {**snapshot, '_cached_monotonic': value}
        else:
            self._stats_empty_cached_at = value

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

        metadata_json = json.dumps(memory.metadata, default=str)
        tags_json = json.dumps(memory.tags)

        with self._lock:
            try:
                if memory.type == MemoryType.OBSIDIAN_NOTE:
                    # Local collection is authoritative over any projected
                    # remote row. Synced updates may revise a row only when
                    # it originated on that same source node; this lets the
                    # hub/other peers receive note edits without clobbering
                    # a local vault that happens to use the same name/path.
                    authority = "" if not synced else "memories.source_node = excluded.source_node AND "
                    cursor = self.conn.execute(
                        f"""INSERT INTO memories
                           (id, type, source_node, source_path, workspace, timestamp,
                            title, content, metadata, tags, sequence, synced)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                           ON CONFLICT(id) DO UPDATE SET
                            source_node=excluded.source_node,
                            source_path=excluded.source_path,
                            workspace=excluded.workspace,
                            timestamp=excluded.timestamp,
                            title=excluded.title,
                            content=excluded.content,
                            metadata=excluded.metadata,
                            tags=excluded.tags,
                            sequence=excluded.sequence,
                            synced=excluded.synced
                           WHERE {authority}(memories.content != excluded.content
                              OR memories.metadata != excluded.metadata
                              OR memories.title != excluded.title
                              OR memories.tags != excluded.tags)""",
                        (
                            memory.id, memory.type.value, memory.source_node,
                            memory.source_path, memory.workspace, memory.timestamp.isoformat(),
                            memory.title, searchable, metadata_json, tags_json,
                            memory.sequence, 1 if synced else 0,
                        ),
                    )
                else:
                    cursor = self.conn.execute(
                        """INSERT OR IGNORE INTO memories
                       (id, type, source_node, source_path, workspace, timestamp,
                        title, content, metadata, tags, sequence, synced)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            memory.id, memory.type.value, memory.source_node,
                            memory.source_path, memory.workspace, memory.timestamp.isoformat(),
                            memory.title, searchable, metadata_json, tags_json,
                            memory.sequence, 1 if synced else 0,
                        ),
                    )
                self.conn.commit()
                if cursor.rowcount > 0:
                    self._stats_generation += 1
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

        conditions = ["COALESCE(json_extract(m.metadata, '$.missing'), 0) = 0"]
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

    def get_memory(self, memory_id: str) -> Optional[dict]:
        """Return one memory by exact id."""
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM memories WHERE id = ?", (memory_id,)
            ).fetchone()
            return dict(row) if row else None

    def select_memories(
        self,
        *,
        query: str = "",
        mem_type: Optional[str] = None,
        session: str = "",
        tags: Optional[list[str]] = None,
        limit: int = 50,
    ) -> list[dict]:
        """Select export candidates using the MVP's supported selectors."""
        if query:
            rows = self.search(query, mem_type=mem_type, tags=tags, limit=limit)
        else:
            sql = "SELECT * FROM memories WHERE COALESCE(json_extract(metadata, '$.missing'), 0) = 0"
            params: list = []
            if mem_type:
                sql += " AND type = ?"
                params.append(mem_type)
            if session:
                sql += " AND json_extract(metadata, '$.session') = ?"
                params.append(session)
            sql += " ORDER BY timestamp DESC LIMIT ?"
            params.append(min(max(1, limit), 200))
            with self._lock:
                rows = [dict(r) for r in self.conn.execute(sql, params).fetchall()]
        if tags:
            wanted = {tag.lower() for tag in tags}
            rows = [
                row for row in rows
                if wanted.issubset({str(tag).lower() for tag in json.loads(row.get("tags") or "[]")})
            ]
        return rows

    def mark_obsidian_missing(self, vault: str, source_node: str, active_ids: set[str]) -> int:
        """Mark vanished local notes without deleting their synchronized history."""
        with self._lock:
            rows = self.conn.execute(
                "SELECT id, metadata FROM memories WHERE type = ? AND source_node = ? "
                "AND json_extract(metadata, '$.vault') = ?",
                (MemoryType.OBSIDIAN_NOTE.value, source_node, vault),
            ).fetchall()
            changed = 0
            for row in rows:
                if row["id"] in active_ids:
                    continue
                metadata = json.loads(row["metadata"] or "{}")
                if metadata.get("missing"):
                    continue
                metadata["missing"] = True
                self.conn.execute(
                    "UPDATE memories SET metadata = ?, synced = 0 WHERE id = ?",
                    (json.dumps(metadata, default=str), row["id"]),
                )
                changed += 1
            self.conn.commit()
            if changed:
                self._stats_generation += 1
            return changed

    def mark_synced(self, memory_ids: list[str]) -> None:
        """Mark memories as synced."""
        with self._lock:
            placeholders = ",".join("?" for _ in memory_ids)
            self.conn.execute(
                f"UPDATE memories SET synced = 1 WHERE id IN ({placeholders})",
                memory_ids,
            )
            self.conn.commit()
            self._stats_generation += 1

    def delete_memory(self, memory_id: str) -> None:
        with self._lock:
            self.conn.execute('DELETE FROM memories WHERE id = ?', (memory_id,))
            self.conn.commit()
            self._stats_generation += 1

    def check_health(self) -> None:
        """Read the real DB without waiting for the index writer/count lock."""
        uri = self.db_path.resolve().as_uri() + '?mode=ro'
        with closing(sqlite3.connect(uri, uri=True, timeout=0.25)) as connection:
            # Connectivity alone can report an empty/wrong database as ready.
            # Preparing this bounded query also proves the required table exists.
            connection.execute('SELECT 1 FROM memories LIMIT 1').fetchone()

    def cached_stats(self) -> dict | None:
        """Last known snapshot, with truthful age/status; never run a query."""
        cached = self._stats_cache
        if cached is None:
            return None
        age = max(0.0, time.monotonic() - cached['_cached_monotonic'])
        changed = cached['_index_generation'] != self._stats_generation
        stale = age >= _STATS_TTL_SECONDS or changed or bool(self._stats_last_error)
        result = copy.deepcopy(cached)
        result.pop('_cached_monotonic')
        result.pop('_index_generation')
        result.update(stats_age_seconds=round(age, 3),
                      stats_status='stale' if stale else 'fresh',
                      stats_degraded=stale,
                      stats_reason=self._stats_last_error or ('index_changed' if changed else ('ttl_expired' if stale else None)),
                      stats_retry_after_seconds=max(0, int(self._stats_retry_at - time.monotonic() + 0.999)))
        return result

    def stats_view(self) -> dict:
        """Noncritical UI/CLI/MCP counts may be unavailable, never fake zero."""
        try:
            return self.get_stats()
        except StatsUnavailable as exc:
            return exc.payload()

    def _stats_failure(self, reason: str) -> dict:
        self._stats_last_error = reason
        self._stats_retry_at = time.monotonic() + _STATS_TTL_SECONDS
        cached = self.cached_stats()
        if cached is not None:
            return cached
        raise StatsUnavailable(reason) from None

    def get_stats(self) -> dict:
        """Readonly covering-index snapshot, bounded budget and single-flight TTL.

        Keep last known counts after writes/failures. Reads never use the writer
        connection or install a progress handler on another thread's SQLite.
        A failed refresh backs off for 30s rather than repeating expensive scans.
        """
        now = time.monotonic()
        cached = self.cached_stats()
        if now < self._stats_retry_at:
            if cached is not None:
                return cached
            raise StatsUnavailable(self._stats_last_error or 'refresh_busy')
        # Writes flag the snapshot stale but do not cause a scan per ingestion.
        if cached is not None and now - self._stats_cached_at < _STATS_TTL_SECONDS:
            return cached
        if not self._stats_lock.acquire(blocking=False):
            if cached is not None:
                cached.update(stats_status='stale', stats_degraded=True, stats_reason='refresh_busy')
                return cached
            raise StatsUnavailable('refresh_busy')
        try:
            cached = self.cached_stats()
            if cached is not None and time.monotonic() - self._stats_cached_at < _STATS_TTL_SECONDS:
                return cached
            # Preserve lazy empty-local-index behavior. Existing databases are
            # never opened writable, migrated or created by the statistics read.
            if not self.db_path.exists():
                if not self._lock.acquire(timeout=_STATS_BUSY_TIMEOUT_SECONDS):
                    return self._stats_failure('database_busy')
                try:
                    try:
                        _ = self.conn
                    except (sqlite3.Error, OSError):
                        return self._stats_failure('database_unavailable')
                finally:
                    self._lock.release()
            generation = self._stats_generation
            collected_at = datetime.now(timezone.utc).isoformat()
            collected_monotonic = time.monotonic()
            deadline = collected_monotonic + _STATS_QUERY_TIMEOUT_SECONDS
            try:
                uri = self.db_path.resolve().as_uri() + '?mode=ro'
                # The transaction pins a consistent snapshot across all counts.
                # Explicit covering indexes do not load large memory content.
                with closing(sqlite3.connect(uri, uri=True, timeout=_STATS_BUSY_TIMEOUT_SECONDS)) as connection:
                    connection.row_factory = sqlite3.Row
                    connection.execute('PRAGMA query_only=ON')
                    connection.execute('PRAGMA cache_size=-512')
                    connection.set_progress_handler(lambda: int(time.monotonic() >= deadline), _PROGRESS_HANDLER_INTERVAL)
                    try:
                        connection.execute('BEGIN')
                        total = connection.execute('SELECT COUNT(*) FROM memories INDEXED BY idx_memories_synced').fetchone()[0]
                        nodes = connection.execute('SELECT COUNT(DISTINCT source_node) FROM memories INDEXED BY idx_memories_node').fetchone()[0]
                        spaces = connection.execute('SELECT COUNT(DISTINCT workspace) FROM memories INDEXED BY idx_memories_workspace').fetchone()[0]
                        unsynced = connection.execute('SELECT COUNT(*) FROM memories INDEXED BY idx_memories_synced WHERE synced = 0').fetchone()[0]
                        types = connection.execute('SELECT type, COUNT(*) AS cnt FROM memories INDEXED BY idx_memories_type GROUP BY type').fetchall()
                        connection.rollback()
                    finally:
                        connection.set_progress_handler(None, 0)
            except (sqlite3.Error, OSError) as exc:
                code = getattr(exc, 'sqlite_errorcode', None)
                reason = ('query_timeout' if code == sqlite3.SQLITE_INTERRUPT else
                          'database_busy' if code in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED) else
                          'database_unavailable')
                return self._stats_failure(reason)
            self._stats_cache = {
                'total_memories': total, 'unique_nodes': nodes, 'unique_workspaces': spaces,
                'unsynced': unsynced, 'by_type': {r['type']: r['cnt'] for r in types},
                'stats_collected_at': collected_at,
                '_cached_monotonic': collected_monotonic, '_index_generation': generation,
            }
            self._stats_last_error = None
            self._stats_retry_at = 0.0
            return self.cached_stats()
        finally:
            self._stats_lock.release()

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
            self._stats_cache = None
            self._stats_generation += 1
