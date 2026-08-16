"""Tests for animus.collector.antigravity."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from animus.collector.antigravity import AntigravityCollector
from animus.collector.models import MemoryType
from animus.config import AnimusConfig


@pytest.fixture
def agy_config(tmp_path):
    """Config with isolated Antigravity + VS Code dirs."""
    cfg = AnimusConfig(
        node_id="test-node",
        node_name="test-machine",
        data_dir=tmp_path / "data",
        vscode_user_dir=tmp_path / "vscode",
        claude_data_dir=tmp_path / "claude",
        antigravity_data_dir=tmp_path / "gemini",
        server_secret="secret",
        hub_url="",
    )
    cfg.ensure_dirs()
    return cfg


class TestAntigravityCollector:
    def test_init(self, agy_config):
        collector = AntigravityCollector(agy_config)
        assert collector.config == agy_config
        assert collector.agy_dir == agy_config.antigravity_data_dir

    def test_collect_all_empty(self, agy_config):
        collector = AntigravityCollector(agy_config)
        assert collector.collect_all() == []

    def test_collect_brain_files(self, agy_config):
        brain_file = (
            agy_config.antigravity_data_dir
            / "antigravity"
            / "brain"
            / "conv-1"
            / "scratch"
        )
        brain_file.parent.mkdir(parents=True)
        brain_file.write_text("# Session scratchpad\nUse FastAPI for the API.", encoding="utf-8")

        collector = AntigravityCollector(agy_config)
        memories = collector.collect_all()
        assert len(memories) == 1
        assert memories[0].type == MemoryType.ANTIGRAVITY_MEMORY
        assert "FastAPI" in memories[0].content

    def test_collect_global_gemini_md(self, agy_config):
        gemini_md = agy_config.antigravity_data_dir / "GEMINI.md"
        gemini_md.parent.mkdir(parents=True, exist_ok=True)
        gemini_md.write_text("# Global rules\nAlways write tests.", encoding="utf-8")

        collector = AntigravityCollector(agy_config)
        memories = collector.collect_all()
        assert len(memories) == 1
        assert memories[0].type == MemoryType.ANTIGRAVITY_MEMORY
        assert memories[0].title == "GEMINI.md (global identity)"

    def test_collect_project_context(self, agy_config):
        proj_file = (
            agy_config.antigravity_data_dir
            / "antigravity"
            / "config"
            / "projects"
            / "outside-of-project.json"
        )
        proj_file.parent.mkdir(parents=True)
        proj_file.write_text(
            json.dumps({"name": "outside", "conversation_id": "conv-xyz"}),
            encoding="utf-8",
        )

        collector = AntigravityCollector(agy_config)
        memories = collector.collect_all()
        assert len(memories) == 1
        assert memories[0].type == MemoryType.ANTIGRAVITY_KNOWLEDGE
        assert "outside" in memories[0].title

    def test_collect_workspace_mcp_config(self, agy_config):
        ws_root = agy_config.antigravity_data_dir / "my-workspace"
        ws_root.mkdir(parents=True)
        (ws_root / ".git").mkdir()

        # Fake VS Code workspace storage pointing at this folder
        ws_id = agy_config.vscode_user_dir / "workspaceStorage" / "ws-123"
        ws_id.mkdir(parents=True)
        (ws_id / "workspace.json").write_text(
            json.dumps({"folder": ws_root.as_uri()}),
            encoding="utf-8",
        )

        mcp_file = ws_root / ".antigravity" / "mcp.json"
        mcp_file.parent.mkdir(parents=True)
        mcp_file.write_text(
            json.dumps({"mcpServers": {"memory": {"command": "npx"}}}),
            encoding="utf-8",
        )

        collector = AntigravityCollector(agy_config)
        memories = collector.collect_all()
        assert len(memories) == 1
        assert memories[0].type == MemoryType.ANTIGRAVITY_KNOWLEDGE
        assert "memory" in memories[0].metadata["mcp_servers"]

    def test_collect_conversation_db(self, agy_config):
        db_path = (
            agy_config.antigravity_data_dir
            / "antigravity"
            / "conversations"
            / "conv-abc.db"
        )
        db_path.parent.mkdir(parents=True)
        conn = sqlite3.connect(str(db_path))
        conn.executescript(
            """
            CREATE TABLE steps (
                idx INTEGER PRIMARY KEY,
                step_type INTEGER DEFAULT 0,
                status INTEGER DEFAULT 0,
                metadata BLOB,
                step_payload BLOB,
                step_format INTEGER DEFAULT 0
            );
            """
        )
        payload = b"\x08\x0e\x12\x18Hello from Antigravity chat"
        conn.execute(
            "INSERT INTO steps (idx, step_type, status, step_payload) VALUES (?, ?, ?, ?)",
            (0, 1, 3, payload),
        )
        conn.commit()
        conn.close()

        collector = AntigravityCollector(agy_config)
        memories = collector.collect_all()
        chat_mems = [m for m in memories if m.type == MemoryType.ANTIGRAVITY_CHAT]
        assert len(chat_mems) == 1
        assert "Hello from Antigravity chat" in chat_mems[0].content

    def test_collector_respects_config_flags(self, agy_config):
        agy_config.collect_antigravity_chat = False
        agy_config.collect_antigravity_memory = False
        agy_config.collect_antigravity_knowledge = False

        gemini_md = agy_config.antigravity_data_dir / "GEMINI.md"
        gemini_md.parent.mkdir(parents=True, exist_ok=True)
        gemini_md.write_text("x", encoding="utf-8")
        collector = AntigravityCollector(agy_config)
        assert collector.collect_all() == []

    def test_safe_utf8_text_filters_noise(self, agy_config):
        collector = AntigravityCollector(agy_config)
        assert collector._safe_utf8_text(b"abc") == ""
        assert collector._safe_utf8_text(b"Hello world test") == "Hello world test"
        assert collector._safe_utf8_text(b"deadbeef12345678") == ""
