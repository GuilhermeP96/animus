"""Tests for animus.network.updater and the /api/version endpoint."""

from __future__ import annotations

import hashlib
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from animus import __version__
from animus.network.updater import (
    DEFAULT_REPO,
    RESTART_EXIT_CODE,
    VersionInfo,
    check_and_apply,
    fetch_latest,
    is_newer,
)


# ── pure helpers ────────────────────────────────────────────────────────


class TestIsNewer:
    @pytest.mark.parametrize("remote, local, expected", [
        ("0.5.1", "0.5.0", True),
        ("0.5.0", "0.5.0", False),
        ("0.4.9", "0.5.0", False),
        ("1.0.0", "0.99.99", True),
        ("0.5", "0.5.0", False),         # zero-pad equivalence
        ("0.5.0-rc.1", "0.5.0", False),  # pre-release < release in our loose parser
        ("", "0.5.0", False),            # empty → not newer
    ])
    def test_comparisons(self, remote, local, expected):
        assert is_newer(remote, local) is expected


class TestVersionInfo:
    def test_defaults(self):
        v = VersionInfo.from_dict({"latest": "0.6.0"})
        assert v.latest == "0.6.0"
        assert v.install_url == DEFAULT_REPO
        assert v.git_ref == "main"
        assert v.channel == "stable"

    def test_overrides(self):
        v = VersionInfo.from_dict({
            "latest": "0.6.0-rc.1",
            "channel": "beta",
            "install_url": "git+https://example.com/repo.git",
            "git_ref": "v0.6.0-rc.1",
            "package_url": "/api/peers/package.whl",
            "min_compat": "0.5.0",
            "notes": "Big release",
        })
        assert v.channel == "beta"
        assert v.git_ref == "v0.6.0-rc.1"
        assert v.package_url == "/api/peers/package.whl"
        assert v.min_compat == "0.5.0"


# ── fetch_latest ────────────────────────────────────────────────────────


class TestFetchLatest:
    def test_no_hub_returns_none(self, config):
        config.hub_url = ""
        assert fetch_latest(config) is None

    def test_hub_unreachable_returns_none(self, config):
        # Bogus port; httpx will time out / refuse. ``fetch_latest`` swallows
        # the exception and returns ``None`` rather than crash the daemon.
        config.hub_url = "http://127.0.0.1:1"
        assert fetch_latest(config, timeout=0.5) is None


# ── check_and_apply ─────────────────────────────────────────────────────


class TestCheckAndApply:
    def test_no_version_no_action(self, config):
        with patch("animus.network.updater.fetch_latest", return_value=None):
            assert check_and_apply(config) == (False, None)

    def test_up_to_date(self, config):
        info = VersionInfo(latest=__version__)
        with patch("animus.network.updater.fetch_latest", return_value=info):
            restart, ret = check_and_apply(config)
            assert restart is False
            assert ret is info

    def test_dry_run(self, config):
        info = VersionInfo(latest="99.0.0")
        with patch("animus.network.updater.fetch_latest", return_value=info), \
             patch("animus.network.updater.apply_update") as apply:
            restart, ret = check_and_apply(config, dry_run=True)
            assert restart is True
            assert ret is info
            apply.assert_not_called()  # dry-run never installs

    def test_force_applies_when_same_version(self, config):
        info = VersionInfo(latest=__version__)
        with patch("animus.network.updater.fetch_latest", return_value=info), \
             patch("animus.network.updater.apply_update", return_value=True) as apply:
            restart, _ = check_and_apply(config, force=True)
            assert restart is True
            apply.assert_called_once()

    def test_apply_failure_keeps_running(self, config):
        info = VersionInfo(latest="99.0.0")
        with patch("animus.network.updater.fetch_latest", return_value=info), \
             patch("animus.network.updater.apply_update", return_value=False):
            restart, _ = check_and_apply(config)
            # ``check_and_apply`` returns the boolean from apply_update so the
            # daemon can skip the restart on failure and try again next cycle.
            assert restart is False

    def test_pre_release_preference_reaches_pip(self, config):
        config.update_allow_pre = True
        info = VersionInfo(latest="99.0.0")
        with patch("animus.network.updater.fetch_latest", return_value=info), \
             patch("animus.network.updater.apply_update", return_value=True) as apply:
            assert check_and_apply(config)[0] is True
            apply.assert_called_once_with(info, allow_pre=True, config=config)


class TestHubPackageDownload:
    def test_downloads_over_authenticated_peer_channel(self, config):
        from animus.network import updater

        config.hub_url = "https://hub.example"
        content = b"wheel-content"
        response = SimpleNamespace(
            status_code=200,
            content=content,
            headers={
                "X-Animus-Package-Filename": "animus-9.0.0-py3-none-any.whl",
                "X-Animus-Package-SHA256": hashlib.sha256(content).hexdigest(),
                "X-Animus-Version": "9.0.0",
            },
        )
        client = MagicMock()
        client.__enter__.return_value.get.return_value = response
        with patch.object(updater.httpx, "Client", return_value=client):
            result = updater.download_hub_package(
                config,
                VersionInfo(latest="9.0.0", package_url="/api/peers/package.whl"),
            )
        assert result is not None
        assert result.read_bytes() == content
        _, kwargs = client.__enter__.return_value.get.call_args
        assert kwargs["headers"]["X-Animus-Node"] == config.node_id
        assert "X-Animus-Signature" in kwargs["headers"]

    def test_rejects_checksum_mismatch(self, config):
        from animus.network import updater

        config.hub_url = "https://hub.example"
        response = SimpleNamespace(
            status_code=200,
            content=b"tampered",
            headers={
                "X-Animus-Package-Filename": "animus-9.0.0-py3-none-any.whl",
                "X-Animus-Package-SHA256": "0" * 64,
                "X-Animus-Version": "9.0.0",
            },
        )
        client = MagicMock()
        client.__enter__.return_value.get.return_value = response
        with patch.object(updater.httpx, "Client", return_value=client):
            assert updater.download_hub_package(
                config,
                VersionInfo(latest="9.0.0", package_url="/api/peers/package.whl"),
            ) is None


# ── apply_update guards ─────────────────────────────────────────────────


class TestApplyUpdateGuards:
    def test_refuses_when_install_not_writable(self):
        from animus.network import updater
        info = VersionInfo(latest="99.0.0")
        with patch.object(updater, "_is_writable_install", return_value=False):
            assert updater.apply_update(info) is False

    def test_refuses_when_pip_missing(self):
        from animus.network import updater
        info = VersionInfo(latest="99.0.0")
        with patch.object(updater, "_is_writable_install", return_value=True), \
             patch.object(updater, "_pip_exe", return_value=None):
            assert updater.apply_update(info) is False

    def test_subprocess_failure_returns_false(self, tmp_path):
        from animus.network import updater
        info = VersionInfo(latest="99.0.0")
        fake_pip = tmp_path / "pip"
        fake_pip.write_text("#!/bin/sh\nexit 1\n")
        fake_pip.chmod(0o755)
        with patch.object(updater, "_is_writable_install", return_value=True), \
             patch.object(updater, "_pip_exe", return_value=fake_pip), \
             patch.object(
                 updater.subprocess, "run",
                 return_value=type("Result", (), {"returncode": 1, "stderr": "failed", "stdout": ""})(),
             ):
            with patch.object(updater.os, "name", "posix"):
                assert updater.apply_update(info) is False

    def test_subprocess_success_returns_true(self, tmp_path):
        from animus.network import updater
        info = VersionInfo(latest="99.0.0")
        fake_pip = tmp_path / "pip"
        fake_pip.write_text("#!/bin/sh\nexit 0\n")
        fake_pip.chmod(0o755)
        with patch.object(updater, "_is_writable_install", return_value=True), \
             patch.object(updater, "_pip_exe", return_value=fake_pip), \
             patch.object(
                 updater.subprocess, "run",
                 return_value=type("Result", (), {"returncode": 0, "stderr": "", "stdout": ""})(),
             ):
            with patch.object(updater.os, "name", "posix"):
                assert updater.apply_update(info) is True

    def test_windows_legacy_git_target_does_not_exit_or_launch_helper(self, tmp_path):
        from animus.network import updater
        info = VersionInfo(latest="99.0.0")
        fake_pip = tmp_path / "pip.exe"
        fake_pip.write_text("")
        updater._deferred_update_pending = False
        with patch.object(updater, "_is_writable_install", return_value=True), \
             patch.object(updater, "_pip_exe", return_value=fake_pip), \
             patch.object(updater.os, "name", "nt"), \
             patch.object(updater.subprocess, "Popen") as detached:
            assert updater.apply_update(info) is False
        detached.assert_not_called()
        assert updater.update_is_deferred() is False


class TestRestartInPlace:
    def test_deferred_windows_update_exits_without_exec(self):
        from animus.network import updater
        updater._deferred_update_pending = True
        try:
            with patch("os.execv") as execv, pytest.raises(SystemExit) as exc:
                updater.restart_in_place()
            assert exc.value.code == RESTART_EXIT_CODE
            execv.assert_not_called()
        finally:
            updater._deferred_update_pending = False

    def test_falls_back_to_exit_when_execv_fails(self):
        from animus.network import updater
        with patch("os.execv", side_effect=OSError("nope")), \
             pytest.raises(SystemExit) as exc:
            updater.restart_in_place()
        assert exc.value.code == RESTART_EXIT_CODE


# ── /api/version endpoint ────────────────────────────────────────────────


@pytest.fixture
def version_client(hub_config):
    import animus.server.app as server_module
    from animus.indexer.engine import IndexEngine
    from animus.server.app import app

    server_module._config = hub_config
    hub_config.server_secret = ""  # dev mode
    engine = IndexEngine(hub_config.db_path)
    _ = engine.conn
    server_module._engine = engine
    server_module._connected_peers = {}
    yield TestClient(app)
    engine.close()
    server_module._config = None
    server_module._engine = None


class TestVersionEndpoint:
    def test_serves_current_version(self, version_client):
        resp = version_client.get("/api/version")
        assert resp.status_code == 200
        data = resp.json()
        assert data["latest"] == __version__
        assert data["channel"] == "stable"
        assert data["install_url"].startswith("git+")
        assert data["git_ref"] in {"main", "master"}
        assert data["package_url"] == "/api/peers/package.whl"

    def test_env_overrides(self, version_client, monkeypatch):
        monkeypatch.setenv("ANIMUS_PIN_VERSION", "0.4.99")
        monkeypatch.setenv("ANIMUS_CHANNEL", "beta")
        monkeypatch.setenv("ANIMUS_GIT_REF", "v0.4.99")
        monkeypatch.setenv("ANIMUS_RELEASE_NOTES", "Pin for QA")
        resp = version_client.get("/api/version")
        data = resp.json()
        assert data["latest"] == "0.4.99"
        assert data["channel"] == "beta"
        assert data["git_ref"] == "v0.4.99"
        assert data["notes"] == "Pin for QA"
        assert data["package_url"] == ""
