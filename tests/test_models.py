"""Tests for animus.collector.models."""

from datetime import datetime, timezone

import pytest

from animus.collector.models import Memory, MemoryBatch, MemoryType, SyncState


class TestMemoryType:
    def test_all_types_exist(self):
        expected = [
            "copilot_chat", "copilot_debug", "copilot_inline",
            "workspace_memory", "mcp_knowledge", "session_note",
            "user_note", "repo_note", "prompt_file", "agent_file",
        ]
        actual = [t.value for t in MemoryType]
        for e in expected:
            assert e in actual, f"Missing MemoryType: {e}"

    def test_type_is_string(self):
        assert isinstance(MemoryType.COPILOT_CHAT.value, str)
        assert MemoryType.COPILOT_CHAT == "copilot_chat"


class TestMemory:
    def test_auto_id_generation(self):
        mem = Memory(
            type=MemoryType.COPILOT_CHAT,
            source_node="node-1",
            content="test content",
        )
        assert mem.id  # Should be auto-generated
        assert len(mem.id) == 16  # SHA-256 truncated to 16 chars

    def test_same_content_same_id(self):
        kwargs = dict(
            type=MemoryType.COPILOT_CHAT,
            source_node="node-1",
            source_path="/test",
            content="identical content",
        )
        m1 = Memory(**kwargs)
        m2 = Memory(**kwargs)
        assert m1.id == m2.id

    def test_different_content_different_id(self):
        base = dict(type=MemoryType.COPILOT_CHAT, source_node="node-1")
        m1 = Memory(**base, content="content A")
        m2 = Memory(**base, content="content B")
        assert m1.id != m2.id

    def test_empty_content_no_id(self):
        mem = Memory(
            type=MemoryType.COPILOT_CHAT,
            source_node="node-1",
            content="",
        )
        assert mem.id == ""

    def test_default_timestamp(self):
        mem = Memory(
            type=MemoryType.COPILOT_CHAT,
            source_node="node-1",
            content="test",
        )
        assert mem.timestamp is not None
        assert mem.timestamp.tzinfo is not None

    def test_metadata_default(self):
        mem = Memory(
            type=MemoryType.COPILOT_CHAT,
            source_node="node-1",
            content="test",
        )
        assert mem.metadata == {}
        assert mem.tags == []

    def test_serialization_roundtrip(self, sample_memory):
        data = sample_memory.model_dump(mode="json")
        restored = Memory(**data)
        assert restored.id == sample_memory.id
        assert restored.type == sample_memory.type
        assert restored.content == sample_memory.content


class TestMemoryBatch:
    def test_creation(self, sample_memories):
        batch = MemoryBatch(
            node_id="node-1",
            node_name="test",
            memories=sample_memories,
        )
        assert len(batch.memories) == len(sample_memories)
        assert batch.batch_timestamp is not None

    def test_empty_batch(self):
        batch = MemoryBatch(
            node_id="node-1",
            node_name="test",
            memories=[],
        )
        assert len(batch.memories) == 0


class TestSyncState:
    def test_defaults(self):
        state = SyncState(node_id="node-1")
        assert state.last_sync is None
        assert state.last_memory_id == ""
        assert state.memory_count == 0
