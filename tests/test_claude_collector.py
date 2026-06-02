"""Tests for animus.collector.claude — Claude Code memory collector."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from animus.collector.claude import (
    ClaudeCollector,
    _decode_project_dir,
    _flatten_content,
    _parse_frontmatter,
)
from animus.collector.models import MemoryType
from animus.config import AnimusConfig


# ── pure helpers ─────────────────────────────────────────────────────────


class TestDecodeProjectDir:
    def test_root(self):
        assert _decode_project_dir("-") == "/"

    def test_absolute_path(self):
        assert _decode_project_dir("-root-foo-bar") == "/root/foo/bar"

    def test_bare(self):
        assert _decode_project_dir("project") == "project"

    def test_empty(self):
        assert _decode_project_dir("") == "/"


class TestFlattenContent:
    def test_string(self):
        text, tools = _flatten_content("hello world")
        assert text == "hello world"
        assert tools == []

    def test_text_part(self):
        text, tools = _flatten_content([{"type": "text", "text": "Hi"}])
        assert text == "Hi"
        assert tools == []

    def test_tool_use(self):
        text, tools = _flatten_content([
            {"type": "text", "text": "Reading"},
            {"type": "tool_use", "name": "Read", "input": {"file_path": "/tmp/a"}},
        ])
        assert text == "Reading"
        assert tools == [{"name": "Read", "input": {"file_path": "/tmp/a"}}]

    def test_thinking_is_skipped(self):
        text, tools = _flatten_content([
            {"type": "thinking", "thinking": "secret reasoning"},
            {"type": "text", "text": "answer"},
        ])
        assert text == "answer"

    def test_tool_result_nested(self):
        text, _ = _flatten_content([
            {"type": "tool_result", "content": [{"type": "text", "text": "output"}]}
        ])
        assert "output" in text


class TestParseFrontmatter:
    def test_no_frontmatter(self):
        meta, body = _parse_frontmatter("just a body")
        assert meta == {}
        assert body == "just a body"

    def test_simple(self):
        meta, body = _parse_frontmatter(
            "---\nname: foo\ndescription: a thing\n---\nbody\n"
        )
        assert meta["name"] == "foo"
        assert meta["description"] == "a thing"
        assert body.strip() == "body"

    def test_nested_metadata(self):
        meta, _ = _parse_frontmatter(
            "---\n"
            "name: feedback-tests\n"
            "description: don't mock the DB\n"
            "metadata:\n"
            "  type: feedback\n"
            "---\n"
            "rule body\n"
        )
        assert meta["name"] == "feedback-tests"
        assert isinstance(meta["metadata"], dict)
        assert meta["metadata"]["type"] == "feedback"

    def test_quoted_values(self):
        meta, _ = _parse_frontmatter(
            '---\nname: "with-quotes"\ndescription: \'single\'\n---\nbody'
        )
        assert meta["name"] == "with-quotes"
        assert meta["description"] == "single"


# ── filesystem fixtures ──────────────────────────────────────────────────


@pytest.fixture
def claude_workspace(tmp_path):
    """Build a fake ``~/.claude`` tree with one project, one transcript and
    a small memory store."""
    claude = tmp_path / "claude"
    proj = claude / "projects" / "-home-repo-vps-hub"
    proj.mkdir(parents=True)

    # Two-turn transcript: user then assistant with a tool call.
    session_id = "11111111-2222-3333-4444-555555555555"
    transcript = proj / f"{session_id}.jsonl"
    lines = [
        json.dumps({"type": "queue-operation", "operation": "enqueue"}),
        json.dumps({
            "type": "user",
            "message": {
                "role": "user",
                "content": [
                    {"type": "text", "text": "How do I deploy the panel?"},
                ],
            },
            "timestamp": "2026-05-02T10:00:00.000Z",
            "cwd": "/home/repo/vps-hub",
            "sessionId": session_id,
            "gitBranch": "main",
        }),
        json.dumps({
            "type": "assistant",
            "message": {
                "role": "assistant",
                "model": "claude-opus-4-7",
                "content": [
                    {"type": "text", "text": "Use scripts/deploy.sh."},
                    {"type": "tool_use", "name": "Bash",
                     "input": {"command": "./scripts/deploy.sh panel"}},
                ],
            },
            "timestamp": "2026-05-02T10:00:05.000Z",
            "cwd": "/home/repo/vps-hub",
            "sessionId": session_id,
        }),
    ]
    transcript.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # Memory store
    mem_dir = proj / "memory"
    mem_dir.mkdir()
    (mem_dir / "MEMORY.md").write_text(
        "- [VPS Hub overview](vps-hub-overview.md) — orquestrador raiz\n",
        encoding="utf-8",
    )
    (mem_dir / "vps-hub-overview.md").write_text(
        "---\n"
        "name: vps-hub-overview\n"
        "description: orquestrador raiz em /home/repo/vps-hub\n"
        "metadata:\n"
        "  type: project\n"
        "---\n"
        "VPS Hub é o orquestrador raiz.\n",
        encoding="utf-8",
    )
    return claude


@pytest.fixture
def claude_config(tmp_path, claude_workspace):
    cfg = AnimusConfig(
        node_id="claude-test-node",
        node_name="claude-test",
        data_dir=tmp_path / "data",
        vscode_user_dir=tmp_path / "vscode",
        claude_data_dir=claude_workspace,
        server_secret="x" * 16,
    )
    cfg.ensure_dirs()
    return cfg


# ── collector behaviour ─────────────────────────────────────────────────


class TestClaudeCollector:
    def test_collect_empty(self, tmp_path):
        cfg = AnimusConfig(
            node_id="n1",
            data_dir=tmp_path / "d",
            vscode_user_dir=tmp_path / "v",
            claude_data_dir=tmp_path / "nope",
            server_secret="x" * 16,
        )
        cfg.ensure_dirs()
        assert ClaudeCollector(cfg).collect_all() == []

    def test_collect_transcripts(self, claude_config):
        mems = ClaudeCollector(claude_config).collect_all()
        chats = [m for m in mems if m.type == MemoryType.CLAUDE_CHAT]
        assert len(chats) == 2  # queue-op skipped, 1 user + 1 assistant
        first = chats[0]
        assert first.metadata["role"] == "user"
        assert first.metadata["session_title"].startswith("How do I deploy")
        assert first.workspace == "/home/repo/vps-hub"
        # Sequence preserved
        assert chats[0].sequence == 0
        assert chats[1].sequence == 1

    def test_assistant_tool_call_in_body(self, claude_config):
        mems = ClaudeCollector(claude_config).collect_all()
        chats = [m for m in mems if m.type == MemoryType.CLAUDE_CHAT]
        assistant = chats[1]
        assert "Tool call" in assistant.content
        assert "scripts/deploy.sh" in assistant.content
        assert assistant.metadata["tool_calls"] == ["Bash"]
        assert assistant.metadata["model"] == "claude-opus-4-7"

    def test_session_title_backfills_early_turns(self, claude_config, tmp_path):
        """The session_title is derived from the first user prompt and
        backfilled on turns indexed before it appeared."""
        proj = claude_config.claude_data_dir / "projects" / "-x"
        proj.mkdir(parents=True)
        sid = "deadbeef-0000-0000-0000-000000000000"
        lines = [
            # assistant-first (e.g. resumed session) — should be backfilled
            json.dumps({
                "type": "assistant",
                "message": {"role": "assistant",
                            "content": [{"type": "text", "text": "Welcome back."}]},
                "timestamp": "2026-05-02T10:00:00.000Z",
                "sessionId": sid,
            }),
            json.dumps({
                "type": "user",
                "message": {"role": "user",
                            "content": [{"type": "text", "text": "What's pending?"}]},
                "timestamp": "2026-05-02T10:00:05.000Z",
                "sessionId": sid,
            }),
        ]
        (proj / f"{sid}.jsonl").write_text("\n".join(lines), encoding="utf-8")
        mems = ClaudeCollector(claude_config).collect_all()
        x_turns = [m for m in mems if m.metadata.get("session") == sid]
        assert len(x_turns) == 2
        assert all(m.metadata["session_title"].startswith("What's pending") for m in x_turns)

    def test_collect_memory_files(self, claude_config):
        mems = ClaudeCollector(claude_config).collect_all()
        memos = [m for m in mems if m.type == MemoryType.CLAUDE_MEMORY]
        # 1 index + 1 typed memory
        assert len(memos) == 2
        by_title = {m.title: m for m in memos}
        assert "MEMORY.md (index)" in by_title
        assert by_title["MEMORY.md (index)"].metadata["is_index"] is True
        themed = by_title["vps-hub-overview"]
        assert themed.metadata["memory_kind"] == "project"
        assert themed.metadata["theme"].startswith("orquestrador raiz")
        # Tags include the kind for graph grouping
        assert "project" in themed.tags
        assert "claude-memory" in themed.tags

    def test_respects_disabled_flags(self, claude_config):
        claude_config.collect_claude_chat = False
        claude_config.collect_claude_memory = False
        assert ClaudeCollector(claude_config).collect_all() == []

    def test_chat_only(self, claude_config):
        claude_config.collect_claude_memory = False
        mems = ClaudeCollector(claude_config).collect_all()
        assert all(m.type == MemoryType.CLAUDE_CHAT for m in mems)

    def test_memory_only(self, claude_config):
        claude_config.collect_claude_chat = False
        mems = ClaudeCollector(claude_config).collect_all()
        assert all(m.type == MemoryType.CLAUDE_MEMORY for m in mems)
