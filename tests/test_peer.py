"""Tests for animus.network.peer — AnimusPeer client."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from animus.collector.models import Memory, MemoryType
from animus.config import AnimusConfig
from animus.indexer.engine import IndexEngine
from animus.network.peer import AnimusPeer, effective_update_check_interval


@pytest.mark.parametrize(
    "configured,expected", [(1, 60), (60, 60), (300, 300), (900, 900), (21_600, 900)]
)
def test_effective_update_check_interval(configured, expected):
    assert effective_update_check_interval(configured) == expected


@pytest.fixture
def peer(config):
    """Create an AnimusPeer with a temp config."""
    p = AnimusPeer(config)
    yield p
    p.engine.close()


class TestCollectAndIndex:
    @pytest.mark.asyncio
    async def test_collect_and_index_returns_count(self, peer):
        # No VS Code data in temp dir → 0 new memories
        count = await peer.collect_and_index()
        assert count == 0

    @pytest.mark.asyncio
    async def test_collect_indexes_memories(self, peer):
        """Hand-index a memory, then verify stats."""
        mem = Memory(
            type=MemoryType.COPILOT_CHAT,
            source_node=peer.config.node_id,
            content="Test memory for peer",
            title="peer-test",
        )
        assert peer.engine.index_memory(mem)
        stats = peer.engine.get_stats()
        assert stats["total_memories"] == 1


class TestSyncToHub:
    @pytest.mark.asyncio
    async def test_no_hub_returns_zero(self, peer):
        peer.config.hub_url = ""
        result = await peer.sync_to_hub()
        assert result == 0

    @pytest.mark.asyncio
    async def test_no_unsynced_returns_zero(self, config):
        config.hub_url = "http://localhost:9999"
        p = AnimusPeer(config)
        result = await p.sync_to_hub()
        assert result == 0
        p.engine.close()


class TestPullFromHub:
    @pytest.mark.asyncio
    async def test_no_hub_returns_zero(self, peer):
        peer.config.hub_url = ""
        result = await peer.pull_from_hub()
        assert result == 0


class TestRemoteSearch:
    @pytest.mark.asyncio
    async def test_no_hub_returns_empty(self, peer):
        peer.config.hub_url = ""
        results = await peer.remote_search("test")
        assert results == []


class TestDaemon:
    @pytest.mark.asyncio
    async def test_stop_flag(self, peer):
        peer._running = True
        peer.stop()
        assert peer._running is False
