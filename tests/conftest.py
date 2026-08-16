"""Shared fixtures for all Animus tests."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from animus.collector.models import Memory, MemoryBatch, MemoryType
from animus.config import AnimusConfig
from animus.indexer.engine import IndexEngine


@pytest.fixture
def tmp_dir(tmp_path):
    """Provide a temporary directory."""
    return tmp_path


@pytest.fixture
def config(tmp_path):
    """Create an AnimusConfig pointing to temp dirs."""
    cfg = AnimusConfig(
        node_id="test-node-01",
        node_name="test-machine",
        node_role="peer",
        data_dir=tmp_path / "data",
        vscode_user_dir=tmp_path / "vscode",
        claude_data_dir=tmp_path / "claude",
        antigravity_data_dir=tmp_path / "gemini",
        copilot_cli_data_dir=tmp_path / "copilot",
        server_secret="test-secret-key-12345",
        hub_url="",
        server_port=18314,
    )
    cfg.ensure_dirs()
    return cfg


@pytest.fixture
def hub_config(tmp_path):
    """Config for hub mode."""
    cfg = AnimusConfig(
        node_id="hub-node-01",
        node_name="test-hub",
        node_role="hub",
        data_dir=tmp_path / "hub-data",
        vscode_user_dir=tmp_path / "vscode",
        claude_data_dir=tmp_path / "claude",
        server_secret="test-secret-key-12345",
        server_port=18314,
    )
    cfg.ensure_dirs()
    return cfg


@pytest.fixture
def engine(config):
    """Create an IndexEngine with temp database."""
    eng = IndexEngine(config.db_path)
    _ = eng.conn  # Initialize
    yield eng
    eng.close()


@pytest.fixture
def sample_memory():
    """Create a sample Memory object."""
    return Memory(
        type=MemoryType.COPILOT_CHAT,
        source_node="test-node-01",
        source_path="/test/chat.json",
        workspace="test-project",
        title="How to deploy Docker containers",
        content="User asked about deploying Docker containers with docker-compose. "
                "Solution involved creating a multi-stage Dockerfile with health checks.",
        tags=["docker", "deploy"],
        sequence=0,
    )


@pytest.fixture
def sample_memories():
    """Create a list of diverse sample memories."""
    return [
        Memory(
            type=MemoryType.COPILOT_CHAT,
            source_node="test-node-01",
            source_path="/test/chat1.json",
            workspace="aura-erp",
            title="Django model migration issue",
            content="Fixed migration conflict by running makemigrations --merge. "
                    "The issue was caused by two branches modifying the same model.",
            tags=["django", "python", "database"],
        ),
        Memory(
            type=MemoryType.COPILOT_DEBUG,
            source_node="test-node-01",
            source_path="/test/debug.log",
            workspace="aura-erp",
            title="debug-session-42",
            content='{"type": "error", "message": "ImportError: No module named celery"}',
            tags=["debug", "python"],
        ),
        Memory(
            type=MemoryType.WORKSPACE_MEMORY,
            source_node="test-node-01",
            source_path="/test/.instructions.md",
            workspace="animus",
            title=".instructions.md",
            content="# Animus Project\nUse FastAPI for the server. SQLite FTS5 for search.",
            tags=["docs"],
        ),
        Memory(
            type=MemoryType.SESSION_NOTE,
            source_node="node-02",
            source_path="/test/session.md",
            workspace="aura-erp",
            title="session-deploy-fix",
            content="Fixed the nginx reverse proxy config. The WebSocket upgrade header was missing.",
            tags=["nginx", "deploy", "fix"],
        ),
        Memory(
            type=MemoryType.MCP_KNOWLEDGE,
            source_node="test-node-01",
            source_path="/mcp/memory.json",
            workspace="",
            title="PostgreSQL partitioning",
            content="PostgreSQL table partitioning by date range improves query performance "
                    "for time-series data. Use PARTITION BY RANGE.",
            tags=["postgres", "database", "performance"],
        ),
        Memory(
            type=MemoryType.PROMPT_FILE,
            source_node="test-node-01",
            source_path="/test/deploy.prompt.md",
            workspace="datano-agents",
            title="deploy.prompt.md",
            content="Deploy workflow: build Docker image, run tests, push to registry, "
                    "SSH deploy to VPS, health check.",
            tags=["deploy", "docker"],
        ),
        Memory(
            type=MemoryType.COPILOT_CHAT,
            source_node="node-02",
            source_path="/test/chat2.json",
            workspace="binance-bot",
            title="Implement MACD indicator",
            content="Implemented MACD (Moving Average Convergence Divergence) indicator "
                    "using pandas. Signal line crossover strategy for buy/sell signals.",
            tags=["python", "trading", "pandas"],
        ),
    ]


@pytest.fixture
def populated_engine(engine, sample_memories):
    """Engine pre-populated with sample memories."""
    engine.index_batch(sample_memories)
    return engine


@pytest.fixture
def vscode_workspace(tmp_path):
    """Create a fake VS Code workspace structure."""
    ws_root = tmp_path / "vscode" / "workspaceStorage" / "abc123"
    copilot_dir = ws_root / "GitHub.copilot-chat"
    debug_dir = copilot_dir / "debug-logs"
    debug_dir.mkdir(parents=True)

    # Create a debug log
    log = debug_dir / "session-001"
    log.write_text(
        '{"type": "chat", "content": "How to use FastAPI?"}\n'
        '{"type": "response", "content": "FastAPI uses async handlers with type hints."}\n',
        encoding="utf-8",
    )

    # Create a chat history JSON
    chat_dir = copilot_dir / "chat-history"
    chat_dir.mkdir()
    chat_file = chat_dir / "conversation.json"
    chat_file.write_text(json.dumps({
        "title": "FastAPI setup",
        "messages": [
            {"role": "user", "content": "How to create a FastAPI app?"},
            {"role": "assistant", "content": "Use `from fastapi import FastAPI; app = FastAPI()`"},
        ]
    }), encoding="utf-8")

    # Create workspace.json
    workspace_json = ws_root / "workspace.json"
    project_root = tmp_path / "projects" / "test-project"
    project_root.mkdir(parents=True)
    workspace_json.write_text(json.dumps({
        "folder": f"file:///{project_root.as_posix()}"
    }), encoding="utf-8")

    # Create copilot-instructions.md in the project
    github_dir = project_root / ".github"
    github_dir.mkdir()
    (github_dir / "copilot-instructions.md").write_text(
        "# Test Project\nUse Python 3.12 and FastAPI.\n", encoding="utf-8"
    )
    (project_root / ".instructions.md").write_text(
        "Always use type hints.\n", encoding="utf-8"
    )

    # Create prompt files
    prompts_dir = github_dir / "prompts"
    prompts_dir.mkdir()
    (prompts_dir / "deploy.prompt.md").write_text(
        "---\ndescription: Deploy\n---\nDeploy the app to production.\n", encoding="utf-8"
    )

    return tmp_path / "vscode"
