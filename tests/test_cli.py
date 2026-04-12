"""Tests for animus.cli — CLI commands via Typer."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from animus.cli import app

runner = CliRunner()


@pytest.fixture
def mock_config(tmp_path):
    """Patch AnimusConfig.load to return a temp config."""
    from animus.config import AnimusConfig

    cfg = AnimusConfig(
        node_id="cli-test-01",
        node_name="cli-machine",
        data_dir=tmp_path / "data",
        vscode_user_dir=tmp_path / "vscode",
    )
    cfg.ensure_dirs()
    with patch("animus.cli.AnimusConfig.load", return_value=cfg):
        yield cfg


class TestInit:
    def test_init_creates_config(self, mock_config):
        result = runner.invoke(app, ["init"])
        assert result.exit_code == 0
        assert "initialized" in result.output.lower() or "Animus" in result.output


class TestConfigShow:
    def test_config_show(self, mock_config):
        result = runner.invoke(app, ["config-show"])
        assert result.exit_code == 0
        assert "cli-test-01" in result.output


class TestConfigSet:
    def test_set_known_key(self, mock_config):
        result = runner.invoke(app, ["config-set", "node_name", "new-name"])
        assert result.exit_code == 0
        assert "new-name" in result.output

    def test_set_unknown_key(self, mock_config):
        result = runner.invoke(app, ["config-set", "nonexistent_field", "val"])
        assert result.exit_code == 1


class TestCollect:
    def test_collect_no_memories(self, mock_config):
        result = runner.invoke(app, ["collect"])
        assert result.exit_code == 0
        assert "Synchronization complete" in result.output or "complete" in result.output.lower()


class TestStats:
    def test_stats_empty(self, mock_config):
        result = runner.invoke(app, ["stats"])
        assert result.exit_code == 0
        assert "0" in result.output  # zero memories


class TestSearch:
    def test_search_no_results(self, mock_config):
        result = runner.invoke(app, ["search", "nonexistent-term-xyz"])
        assert result.exit_code == 0
        assert "No memories" in result.output or "0" in result.output
