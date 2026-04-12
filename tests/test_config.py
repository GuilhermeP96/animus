"""Tests for animus.config."""

import json
import platform
from pathlib import Path

import pytest

from animus.config import AnimusConfig, _default_data_dir, _default_vscode_dir


class TestDefaultPaths:
    def test_default_data_dir_returns_path(self):
        result = _default_data_dir()
        assert isinstance(result, Path)
        assert "animus" in str(result)

    def test_default_vscode_dir_returns_path(self):
        result = _default_vscode_dir()
        assert isinstance(result, Path)
        assert "Code" in str(result)


class TestAnimusConfig:
    def test_default_values(self):
        cfg = AnimusConfig()
        assert cfg.node_role == "peer"
        assert cfg.server_port == 8314
        assert cfg.collect_interval_seconds == 300
        assert cfg.fts_enabled is True
        assert cfg.vector_enabled is False

    def test_custom_values(self, tmp_path):
        cfg = AnimusConfig(
            node_id="custom-id",
            node_name="my-machine",
            data_dir=tmp_path,
            server_port=9999,
        )
        assert cfg.node_id == "custom-id"
        assert cfg.node_name == "my-machine"
        assert cfg.server_port == 9999

    def test_properties(self, config):
        assert config.db_path == config.data_dir / "animus.db"
        assert config.index_path == config.data_dir / "index"
        assert config.config_path == config.data_dir / "config.json"

    def test_ensure_dirs(self, config):
        config.ensure_dirs()
        assert config.data_dir.exists()
        assert config.index_path.exists()

    def test_save_and_load(self, config):
        config.save()
        assert config.config_path.exists()

        loaded = AnimusConfig.load(config.config_path)
        assert loaded.node_id == config.node_id
        assert loaded.node_name == config.node_name
        assert loaded.server_port == config.server_port

    def test_load_generates_node_id(self, tmp_path):
        """Loading without existing config should auto-generate node_id."""
        cfg = AnimusConfig(data_dir=tmp_path / "fresh")
        # Force a fresh load (no config file exists)
        loaded = AnimusConfig.load(tmp_path / "fresh" / "config.json")
        assert loaded.node_id  # Should be auto-generated
        assert len(loaded.node_id) > 0

    def test_save_creates_valid_json(self, config):
        config.save()
        data = json.loads(config.config_path.read_text(encoding="utf-8"))
        assert "node_id" in data
        assert "server_port" in data
        assert data["server_port"] == config.server_port
