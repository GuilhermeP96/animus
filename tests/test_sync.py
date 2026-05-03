"""Tests for animus.network.sync."""

import json

import pytest

from animus.collector.models import Memory, MemoryBatch, MemoryType
from animus.network.sync import SyncProtocol


class TestHandshake:
    def test_produces_valid_json(self):
        raw = SyncProtocol.handshake("node-1", "test-machine")
        data = json.loads(raw)
        assert data["type"] == "HANDSHAKE"
        assert data["node_id"] == "node-1"
        assert data["node_name"] == "test-machine"
        assert "version" in data
        assert "timestamp" in data

    def test_default_capabilities(self):
        data = json.loads(SyncProtocol.handshake("n1", "m1"))
        assert "push" in data["capabilities"]
        assert "pull" in data["capabilities"]
        assert "query" in data["capabilities"]

    def test_custom_capabilities(self):
        data = json.loads(SyncProtocol.handshake("n1", "m1", ["push"]))
        assert data["capabilities"] == ["push"]


class TestPush:
    def test_produces_valid_json(self, sample_memories):
        batch = MemoryBatch(
            node_id="test-node",
            node_name="test-machine",
            memories=sample_memories,
        )
        raw = SyncProtocol.push(batch)
        data = json.loads(raw)
        assert data["type"] == "PUSH"
        assert data["count"] == len(sample_memories)
        assert len(data["memories"]) == len(sample_memories)

    def test_memory_roundtrip(self, sample_memory):
        batch = MemoryBatch(
            node_id="n1", node_name="m1", memories=[sample_memory]
        )
        raw = SyncProtocol.push(batch)
        data = json.loads(raw)
        restored, skipped = SyncProtocol.memories_from_push(data)
        assert len(restored) == 1
        assert skipped == 0
        assert restored[0].id == sample_memory.id
        assert restored[0].content == sample_memory.content


class TestPull:
    def test_produces_valid_json(self):
        raw = SyncProtocol.pull("node-1", since="2024-01-01T00:00:00Z", limit=50)
        data = json.loads(raw)
        assert data["type"] == "PULL"
        assert data["node_id"] == "node-1"
        assert data["since"] == "2024-01-01T00:00:00Z"
        assert data["limit"] == 50

    def test_pull_no_since(self):
        data = json.loads(SyncProtocol.pull("node-1"))
        assert data["since"] is None


class TestAck:
    def test_produces_valid_json(self):
        raw = SyncProtocol.ack("PUSH", 5, ["id1", "id2"])
        data = json.loads(raw)
        assert data["type"] == "ACK"
        assert data["ack_for"] == "PUSH"
        assert data["count"] == 5
        assert data["memory_ids"] == ["id1", "id2"]


class TestQuery:
    def test_produces_valid_json(self):
        raw = SyncProtocol.query("node-1", "FastAPI deploy", {"workspace": "aura"})
        data = json.loads(raw)
        assert data["type"] == "QUERY"
        assert data["query"] == "FastAPI deploy"
        assert data["filters"]["workspace"] == "aura"


class TestResult:
    def test_produces_valid_json(self):
        raw = SyncProtocol.result([{"id": "1", "content": "test"}], "q1")
        data = json.loads(raw)
        assert data["type"] == "RESULT"
        assert data["count"] == 1
        assert data["query"] == "q1"


class TestHeartbeat:
    def test_produces_valid_json(self):
        raw = SyncProtocol.heartbeat("node-1", {"memories": 42})
        data = json.loads(raw)
        assert data["type"] == "HEARTBEAT"
        assert data["stats"]["memories"] == 42


class TestParse:
    def test_valid_message(self):
        raw = SyncProtocol.handshake("n1", "m1")
        data = SyncProtocol.parse(raw)
        assert data["type"] == "HANDSHAKE"

    def test_invalid_json_raises(self):
        with pytest.raises(ValueError, match="Invalid JSON"):
            SyncProtocol.parse("not json {{{")

    def test_missing_type_raises(self):
        with pytest.raises(ValueError, match="Invalid message"):
            SyncProtocol.parse('{"foo": "bar"}')

    def test_non_dict_raises(self):
        with pytest.raises(ValueError, match="Invalid message"):
            SyncProtocol.parse("[1, 2, 3]")


class TestMemoriesFromPush:
    def test_empty_push(self):
        memories, skipped = SyncProtocol.memories_from_push({"memories": []})
        assert memories == []
        assert skipped == 0

    def test_malformed_memory_skipped(self):
        data = {"memories": [{"bad": "data"}, {"also": "bad"}]}
        memories, skipped = SyncProtocol.memories_from_push(data)
        assert len(memories) == 0
        assert skipped == 2

    def test_no_memories_key(self):
        memories, skipped = SyncProtocol.memories_from_push({})
        assert memories == []
        assert skipped == 0

    def test_metadata_and_tags_decoded_from_json_strings(self):
        """Hub reads SQLite rows where metadata/tags are TEXT — pull responses
        keep them as JSON strings. memories_from_push must transparently decode
        them so Memory(...) doesn't raise validation errors."""
        data = {
            "memories": [
                {
                    "id": "abc123",
                    "type": "copilot_chat",
                    "source_node": "n1",
                    "content": "hello",
                    "metadata": '{"source": "transcript", "turn": 7}',
                    "tags": '["chat", "copilot"]',
                }
            ]
        }
        memories, skipped = SyncProtocol.memories_from_push(data)
        assert skipped == 0
        assert len(memories) == 1
        m = memories[0]
        assert m.metadata == {"source": "transcript", "turn": 7}
        assert m.tags == ["chat", "copilot"]

    def test_empty_string_metadata_tags_become_defaults(self):
        data = {
            "memories": [
                {
                    "id": "d1",
                    "type": "copilot_chat",
                    "source_node": "n1",
                    "content": "x",
                    "metadata": "",
                    "tags": "",
                }
            ]
        }
        memories, skipped = SyncProtocol.memories_from_push(data)
        assert skipped == 0
        assert memories[0].metadata == {}
        assert memories[0].tags == []

    def test_null_metadata_tags_become_defaults(self):
        data = {
            "memories": [
                {
                    "id": "d2",
                    "type": "copilot_chat",
                    "source_node": "n1",
                    "content": "x",
                    "metadata": None,
                    "tags": None,
                }
            ]
        }
        memories, skipped = SyncProtocol.memories_from_push(data)
        assert skipped == 0
        assert memories[0].metadata == {}
        assert memories[0].tags == []
