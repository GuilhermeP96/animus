"""Tests for animus.config."""

import json
import platform
from pathlib import Path
from unittest.mock import patch

import pytest

from animus.config import (
    AnimusConfig,
    _default_data_dir,
    _default_vscode_dir,
    _legacy_data_dirs,
    _migrate_legacy_data_dir,
)


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

    def test_load_with_explicit_path_does_not_touch_home_config(
        self, tmp_path, monkeypatch
    ):
        """Regression: a test calling ``load(some_tmp_path)`` must not
        write to the real ``~/.animus/config.json``. Previously the
        auto-save fallback inside ``load()`` clobbered live peer
        configs whenever the suite ran."""
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))
        # Sanity: home config doesn't exist yet
        home_cfg = fake_home / ".animus" / "config.json"
        assert not home_cfg.exists()
        # Load from a different path that doesn't exist either
        AnimusConfig.load(tmp_path / "elsewhere" / "config.json")
        # The home config must remain absent
        assert not home_cfg.exists()

    def test_save_creates_valid_json(self, config):
        config.save()
        data = json.loads(config.config_path.read_text(encoding="utf-8"))
        assert "node_id" in data
        assert "server_port" in data
        assert data["server_port"] == config.server_port


class TestWindowsDataDir:
    """v0.4.5 — data_dir on Windows must live outside AppData to
    avoid Microsoft Store Python AppX virtualization."""

    def test_default_data_dir_windows_uses_home(self):
        with patch("animus.config.platform.system", return_value="Windows"):
            result = _default_data_dir()
        assert result == Path.home() / ".animus"
        # Must NOT be under any AppData path
        s = str(result).lower()
        assert "appdata" not in s
        assert "localappdata" not in s

    def test_legacy_data_dirs_non_windows_empty(self):
        with patch("animus.config.platform.system", return_value="Linux"):
            assert _legacy_data_dirs() == []

    def test_legacy_data_dirs_includes_appdata(self, tmp_path, monkeypatch):
        monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
        with patch("animus.config.platform.system", return_value="Windows"):
            dirs = _legacy_data_dirs()
        assert tmp_path / "Roaming" / "animus" in dirs

    def test_legacy_data_dirs_includes_appx_virtualized(self, tmp_path, monkeypatch):
        local = tmp_path / "Local"
        appx = (
            local
            / "Packages"
            / "PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0"
            / "LocalCache"
            / "Roaming"
            / "animus"
        )
        appx.mkdir(parents=True)
        monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
        monkeypatch.setenv("LOCALAPPDATA", str(local))
        with patch("animus.config.platform.system", return_value="Windows"):
            dirs = _legacy_data_dirs()
        assert appx in dirs


class TestLegacyMigration:
    def test_migrate_copies_files_and_rewrites_data_dir(self, tmp_path):
        src = tmp_path / "old"
        dst = tmp_path / "new"
        src.mkdir()
        # Pre-existing data we expect to land at dst
        (src / "animus.db").write_bytes(b"\x00\x01")
        (src / "index").mkdir()
        (src / "index" / "lock").write_text("x")
        (src / "config.json").write_text(
            json.dumps({"node_id": "abc-123", "data_dir": str(src)}),
            encoding="utf-8",
        )

        _migrate_legacy_data_dir(src, dst)

        assert (dst / "animus.db").read_bytes() == b"\x00\x01"
        assert (dst / "index" / "lock").read_text() == "x"
        # Crucially: data_dir was rewritten to the destination path
        migrated = json.loads((dst / "config.json").read_text(encoding="utf-8"))
        assert migrated["node_id"] == "abc-123"
        assert migrated["data_dir"] == str(dst)

    def test_migrate_is_idempotent(self, tmp_path):
        src = tmp_path / "old"
        dst = tmp_path / "new"
        src.mkdir()
        (src / "config.json").write_text(
            json.dumps({"node_id": "x", "data_dir": str(src)}), encoding="utf-8"
        )
        (src / "animus.db").write_bytes(b"original")

        _migrate_legacy_data_dir(src, dst)

        # Second migration must not overwrite existing destination files
        (dst / "animus.db").write_bytes(b"newer")
        _migrate_legacy_data_dir(src, dst)
        assert (dst / "animus.db").read_bytes() == b"newer"

    def test_load_triggers_migration_when_target_empty(
        self, tmp_path, monkeypatch
    ):
        """If new data_dir has no config but a legacy one does, load()
        should auto-migrate."""
        legacy = tmp_path / "legacy_appdata" / "animus"
        legacy.mkdir(parents=True)
        (legacy / "config.json").write_text(
            json.dumps(
                {
                    "node_id": "migrated-node",
                    "node_name": "old-host",
                    "data_dir": str(legacy),
                }
            ),
            encoding="utf-8",
        )

        new_home = tmp_path / "home"
        new_home.mkdir()

        monkeypatch.setenv("APPDATA", str(tmp_path / "legacy_appdata"))
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: new_home))

        with patch("animus.config.platform.system", return_value="Windows"):
            cfg = AnimusConfig.load()

        assert cfg.node_id == "migrated-node"
        assert cfg.node_name == "old-host"
        # Migration must have populated the new home-based dir
        assert (new_home / ".animus" / "config.json").exists()
        # And the data_dir field must point at the new location
        assert cfg.data_dir == new_home / ".animus"
