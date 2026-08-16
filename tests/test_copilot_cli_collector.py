"""Tests for animus.collector.copilot_cli."""

from __future__ import annotations

import sqlite3

import pytest

from animus.collector.copilot_cli import CopilotCliCollector
from animus.collector.models import MemoryType
from animus.config import AnimusConfig


@pytest.fixture
def cli_config(tmp_path):
    """Config with an isolated Copilot CLI data dir."""
    cfg = AnimusConfig(
        node_id="test-node",
        node_name="test-machine",
        data_dir=tmp_path / "data",
        vscode_user_dir=tmp_path / "vscode",
        claude_data_dir=tmp_path / "claude",
        antigravity_data_dir=tmp_path / "gemini",
        copilot_cli_data_dir=tmp_path / "copilot",
        server_secret="secret",
        hub_url="",
    )
    cfg.ensure_dirs()
    return cfg


def _make_session_store(db_path):
    """Create a minimal session-store.db with the real CLI schema."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE sessions (
            id TEXT PRIMARY KEY,
            cwd TEXT,
            repository TEXT,
            branch TEXT,
            summary TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE turns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL REFERENCES sessions(id),
            turn_index INTEGER NOT NULL,
            user_message TEXT,
            assistant_response TEXT,
            timestamp TEXT DEFAULT (datetime('now')),
            UNIQUE(session_id, turn_index)
        );
        CREATE TABLE checkpoints (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL REFERENCES sessions(id),
            checkpoint_number INTEGER NOT NULL,
            title TEXT,
            overview TEXT,
            history TEXT,
            work_done TEXT,
            technical_details TEXT,
            important_files TEXT,
            next_steps TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            UNIQUE(session_id, checkpoint_number)
        );
        """
    )
    conn.execute(
        "INSERT INTO sessions (id, cwd, repository, branch, summary, created_at) "
        "VALUES ('sess-1', '/home/user/proj', 'user/proj', 'main', 'Fix the bug', '2026-08-01 10:00:00')"
    )
    conn.execute(
        "INSERT INTO turns (session_id, turn_index, user_message, assistant_response, timestamp) "
        "VALUES ('sess-1', 0, 'Why is the test failing?', 'Because the fixture is wrong.', '2026-08-01 10:01:00')"
    )
    conn.execute(
        "INSERT INTO turns (session_id, turn_index, user_message, assistant_response, timestamp) "
        "VALUES ('sess-1', 1, '', '   ', '2026-08-01 10:02:00')"
    )
    conn.execute(
        "INSERT INTO checkpoints (session_id, checkpoint_number, title, overview, work_done, created_at) "
        "VALUES ('sess-1', 1, 'Bug fixed', 'Fixed the failing test.', 'Adjusted the fixture.', '2026-08-01 10:05:00')"
    )
    conn.commit()
    conn.close()


class TestCopilotCliCollector:
    def test_init(self, cli_config):
        collector = CopilotCliCollector(cli_config)
        assert collector.config == cli_config
        assert collector.cli_dir == cli_config.copilot_cli_data_dir

    def test_collect_all_empty(self, cli_config):
        collector = CopilotCliCollector(cli_config)
        assert collector.collect_all() == []

    def test_collect_turns_and_checkpoints(self, cli_config):
        _make_session_store(cli_config.copilot_cli_data_dir / "session-store.db")

        collector = CopilotCliCollector(cli_config)
        memories = collector.collect_all()

        # 1 real turn (the blank one is skipped) + 1 checkpoint
        assert len(memories) == 2
        assert all(m.type == MemoryType.COPILOT_CLI_CHAT for m in memories)

        turn = next(m for m in memories if m.metadata.get("kind") != "checkpoint")
        assert "Why is the test failing?" in turn.content
        assert "Because the fixture is wrong." in turn.content
        assert turn.workspace == "proj"
        assert turn.metadata["session"] == "sess-1"
        assert turn.metadata["session_title"] == "Fix the bug"
        assert turn.metadata["git_branch"] == "main"
        assert "copilot-cli" in turn.tags

        checkpoint = next(m for m in memories if m.metadata.get("kind") == "checkpoint")
        assert "Fixed the failing test." in checkpoint.content
        assert "Adjusted the fixture." in checkpoint.content
        assert "checkpoint" in checkpoint.tags

    def test_collect_disabled(self, cli_config):
        _make_session_store(cli_config.copilot_cli_data_dir / "session-store.db")
        cli_config.collect_copilot_cli_chat = False

        collector = CopilotCliCollector(cli_config)
        assert collector.collect_all() == []

    def test_missing_tables_returns_empty(self, cli_config):
        db_path = cli_config.copilot_cli_data_dir / "session-store.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE unrelated (id INTEGER)")
        conn.commit()
        conn.close()

        collector = CopilotCliCollector(cli_config)
        assert collector.collect_all() == []

    def test_corrupt_db_returns_empty(self, cli_config):
        db_path = cli_config.copilot_cli_data_dir / "session-store.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        db_path.write_bytes(b"not a sqlite database at all")

        collector = CopilotCliCollector(cli_config)
        assert collector.collect_all() == []
