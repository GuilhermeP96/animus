"""Tests for animus.indexer.engine."""

import pytest

from animus.collector.models import Memory, MemoryType
from animus.indexer.engine import IndexEngine


class TestIndexEngine:
    def test_init_creates_tables(self, engine):
        """Schema should be created on first access."""
        tables = engine.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        table_names = {t["name"] for t in tables}
        assert "memories" in table_names
        assert "memories_fts" in table_names
        assert "sync_state" in table_names

    def test_index_memory_returns_true_for_new(self, engine, sample_memory):
        result = engine.index_memory(sample_memory)
        assert result is True

    def test_index_memory_returns_false_for_duplicate(self, engine, sample_memory):
        engine.index_memory(sample_memory)
        result = engine.index_memory(sample_memory)
        assert result is False

    def test_index_batch(self, engine, sample_memories):
        count = engine.index_batch(sample_memories)
        assert count == len(sample_memories)

    def test_index_batch_deduplicates(self, engine, sample_memories):
        engine.index_batch(sample_memories)
        count = engine.index_batch(sample_memories)
        assert count == 0

    def test_search_by_keyword(self, populated_engine):
        results = populated_engine.search("Docker")
        assert len(results) > 0
        found_content = " ".join(r["content"] for r in results)
        assert "docker" in found_content.lower() or "Docker" in found_content

    def test_search_by_type_filter(self, populated_engine):
        results = populated_engine.search("python", mem_type="copilot_chat")
        for r in results:
            assert r["type"] == "copilot_chat"

    def test_search_by_workspace_filter(self, populated_engine):
        results = populated_engine.search("Django", workspace="aura-erp")
        for r in results:
            assert r["workspace"] == "aura-erp"

    def test_search_no_results(self, populated_engine):
        results = populated_engine.search("xyznonexistentterm123")
        assert results == []

    def test_search_with_limit(self, populated_engine):
        results = populated_engine.search("python", limit=1)
        assert len(results) <= 1

    def test_get_stats(self, populated_engine):
        stats = populated_engine.get_stats()
        assert stats["total_memories"] > 0
        assert stats["unique_nodes"] > 0
        assert "by_type" in stats
        assert "unsynced" in stats

    def test_get_recent(self, populated_engine):
        recent = populated_engine.get_recent(5)
        assert len(recent) > 0
        assert len(recent) <= 5

    def test_get_unsynced(self, populated_engine):
        unsynced = populated_engine.get_unsynced()
        assert len(unsynced) > 0

    def test_mark_synced(self, populated_engine):
        unsynced = populated_engine.get_unsynced()
        ids_to_sync = [m["id"] for m in unsynced[:2]]
        populated_engine.mark_synced(ids_to_sync)

        still_unsynced = populated_engine.get_unsynced()
        synced_ids = {m["id"] for m in still_unsynced}
        for sid in ids_to_sync:
            assert sid not in synced_ids

    def test_close_and_reopen(self, config, sample_memory):
        eng = IndexEngine(config.db_path)
        eng.index_memory(sample_memory)
        eng.close()

        eng2 = IndexEngine(config.db_path)
        stats = eng2.get_stats()
        assert stats["total_memories"] >= 1
        eng2.close()

    def test_fts_search_special_chars(self, populated_engine):
        """FTS should handle special characters without crashing."""
        results = populated_engine.search("error: can't find module")
        # Should not raise, even with special chars
        assert isinstance(results, list)

    def test_get_stats_empty_db(self, engine):
        stats = engine.get_stats()
        assert stats["total_memories"] == 0
        assert stats["unique_nodes"] == 0
