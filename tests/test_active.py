"""Tests for animus.mcp.active (Active Context Injector)."""

import pytest
from pathlib import Path

from animus.mcp.active import ActiveContextInjector


class TestActiveContextInjector:
    @pytest.fixture
    def injector(self, config, populated_engine, monkeypatch):
        """Create an injector backed by populated engine."""
        inj = ActiveContextInjector.__new__(ActiveContextInjector)
        inj.config = config
        inj.engine = populated_engine
        return inj

    def test_generate_workspace_context(self, injector, tmp_path):
        workspace = tmp_path / "my-project"
        workspace.mkdir()
        context = injector.generate_workspace_context(workspace)
        assert "# Animus Context" in context
        assert "my-project" in context
        assert "Total memories" in context

    def test_context_contains_node_info(self, injector, tmp_path):
        workspace = tmp_path / "project"
        workspace.mkdir()
        context = injector.generate_workspace_context(workspace)
        assert injector.config.node_id in context

    def test_write_workspace_context(self, injector, tmp_path):
        workspace = tmp_path / "project"
        workspace.mkdir()
        injector.write_workspace_context(workspace)
        context_file = workspace / ".animus-context.md"
        assert context_file.exists()
        content = context_file.read_text(encoding="utf-8")
        assert "Animus Context" in content

    def test_generate_copilot_instructions_overlay(self, injector, tmp_path):
        workspace = tmp_path / "project"
        workspace.mkdir()
        overlay = injector.generate_copilot_instructions_overlay(workspace)
        assert isinstance(overlay, str)
        assert len(overlay) > 0
