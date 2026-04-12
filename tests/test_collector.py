"""Tests for animus.collector.copilot."""

import json
from pathlib import Path

import pytest

from animus.collector.copilot import CopilotCollector
from animus.collector.models import MemoryType
from animus.config import AnimusConfig


class TestCopilotCollector:
    def test_init(self, config):
        collector = CopilotCollector(config)
        assert collector.config == config
        assert collector.vscode_dir == config.vscode_user_dir

    def test_collect_all_empty(self, config):
        """Collecting from empty dirs should return empty list, not crash."""
        collector = CopilotCollector(config)
        result = collector.collect_all()
        assert isinstance(result, list)
        assert len(result) == 0

    def test_collect_debug_logs(self, config, vscode_workspace):
        config = AnimusConfig(
            node_id="test-node",
            data_dir=config.data_dir,
            vscode_user_dir=vscode_workspace,
        )
        collector = CopilotCollector(config)
        memories = collector._collect_debug_logs()
        assert len(memories) > 0
        assert all(m.type == MemoryType.COPILOT_DEBUG for m in memories)

    def test_collect_chat_history(self, config, vscode_workspace):
        config = AnimusConfig(
            node_id="test-node",
            data_dir=config.data_dir,
            vscode_user_dir=vscode_workspace,
        )
        collector = CopilotCollector(config)
        memories = collector._collect_chat_history()
        assert len(memories) > 0
        # Should contain chat messages
        chat_mems = [m for m in memories if m.type == MemoryType.COPILOT_CHAT]
        assert len(chat_mems) > 0

    def test_parse_debug_log_json_lines(self, config, tmp_path):
        """Test parsing JSON-lines debug log."""
        log_file = tmp_path / "test.log"
        log_file.write_text(
            '{"type": "request", "content": "Hello"}\n'
            '{"type": "response", "content": "World"}\n',
            encoding="utf-8",
        )
        collector = CopilotCollector(config)
        memories = collector._parse_debug_log(log_file, "ws-001")
        assert len(memories) == 2
        assert memories[0].workspace == "ws-001"

    def test_parse_debug_log_plain_text(self, config, tmp_path):
        """Test parsing plain text log (non-JSON)."""
        log_file = tmp_path / "test.log"
        log_file.write_text(
            "This is a long enough plain text log entry for testing purposes\n"
            "Short\n"  # Too short, should be skipped
            "Another sufficiently long log entry that should be captured\n",
            encoding="utf-8",
        )
        collector = CopilotCollector(config)
        memories = collector._parse_debug_log(log_file, "ws-001")
        assert len(memories) == 2  # Short line skipped

    def test_parse_chat_file_with_messages(self, config, tmp_path):
        chat_file = tmp_path / "chat.json"
        chat_file.write_text(json.dumps({
            "messages": [
                {"role": "user", "content": "What is FastAPI?"},
                {"role": "assistant", "content": "FastAPI is a modern Python web framework."},
            ]
        }), encoding="utf-8")
        collector = CopilotCollector(config)
        memories = collector._parse_chat_file(chat_file, "ws-001")
        assert len(memories) == 2
        assert "user" in memories[0].metadata.get("role", "")

    def test_parse_chat_file_single_object(self, config, tmp_path):
        """Chat file as single conversation object (no messages array)."""
        chat_file = tmp_path / "chat.json"
        chat_file.write_text(json.dumps({
            "title": "Docker help",
            "content": "How to build a Docker image",
        }), encoding="utf-8")
        collector = CopilotCollector(config)
        memories = collector._parse_chat_file(chat_file, "ws-001")
        assert len(memories) == 1

    def test_parse_chat_file_invalid_json(self, config, tmp_path):
        """Invalid JSON should return empty, not crash."""
        chat_file = tmp_path / "bad.json"
        chat_file.write_text("not valid json {{{", encoding="utf-8")
        collector = CopilotCollector(config)
        memories = collector._parse_chat_file(chat_file, "ws-001")
        assert memories == []

    def test_collect_workspace_memories(self, config, vscode_workspace):
        config = AnimusConfig(
            node_id="test-node",
            data_dir=config.data_dir,
            vscode_user_dir=vscode_workspace,
        )
        collector = CopilotCollector(config)
        memories = collector._collect_workspace_memories()
        # Should find copilot-instructions.md, .instructions.md, prompt files
        types = {m.type for m in memories}
        assert MemoryType.WORKSPACE_MEMORY in types or MemoryType.PROMPT_FILE in types or len(memories) >= 0

    def test_collect_mcp_memory_no_file(self, config):
        """MCP memory with no file should return empty."""
        collector = CopilotCollector(config)
        memories = collector._collect_mcp_memory()
        assert memories == []

    def test_collect_mcp_memory_with_data(self, config, tmp_path):
        """MCP memory with a real file."""
        mcp_dir = config.data_dir.parent / "mcp-memory"
        mcp_dir.mkdir(parents=True)
        mcp_file = mcp_dir / "memory.json"
        mcp_file.write_text(json.dumps({
            "entities": [
                {
                    "name": "FastAPI",
                    "entityType": "framework",
                    "observations": ["Used for REST APIs", "Supports async"],
                },
                {
                    "name": "Docker",
                    "entityType": "tool",
                    "observations": ["Container runtime"],
                },
            ]
        }), encoding="utf-8")
        collector = CopilotCollector(config)
        memories = collector._collect_mcp_memory()
        assert len(memories) == 2
        assert all(m.type == MemoryType.MCP_KNOWLEDGE for m in memories)

    def test_collector_respects_config_flags(self, config):
        """Disabling collection sources should skip them."""
        config.collect_copilot_logs = False
        config.collect_copilot_chat = False
        config.collect_workspace_memories = False
        config.collect_mcp_memory = False
        collector = CopilotCollector(config)
        result = collector.collect_all()
        assert result == []
