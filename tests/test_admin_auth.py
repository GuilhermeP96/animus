"""Tests for animus.server.admin_auth fail-closed defaults."""

import importlib

import pytest


@pytest.fixture
def reload_admin_auth(monkeypatch):
    """Helper to reload admin_auth with a controlled environment."""

    def _reload(env: dict[str, str]):
        for k in [
            "ANIMUS_ADMIN_USER",
            "ANIMUS_ADMIN_PASSWORD",
            "ANIMUS_ADMIN_SECRET",
            "ANIMUS_SERVER_SECRET",
            "ANIMUS_ADMIN_INSECURE",
        ]:
            monkeypatch.delenv(k, raising=False)
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        from animus.server import admin_auth
        importlib.reload(admin_auth)
        return admin_auth

    return _reload


class TestAdminFailClosed:
    def test_no_password_no_secret_rejects_all(self, reload_admin_auth):
        m = reload_admin_auth({})
        assert m._admin_configured() is False
        assert m.validate_credentials("admin", "admin") is False
        assert m.validate_credentials("anything", "anything") is False

    def test_password_without_secret_still_rejects(self, reload_admin_auth):
        m = reload_admin_auth({"ANIMUS_ADMIN_PASSWORD": "hunter2"})
        assert m._admin_configured() is False
        assert m.validate_credentials("admin", "hunter2") is False

    def test_password_plus_secret_accepts(self, reload_admin_auth):
        m = reload_admin_auth(
            {
                "ANIMUS_ADMIN_PASSWORD": "hunter2",
                "ANIMUS_ADMIN_SECRET": "real-secret",
            }
        )
        assert m._admin_configured() is True
        assert m.validate_credentials("admin", "hunter2") is True
        assert m.validate_credentials("admin", "wrong") is False

    def test_explicit_insecure_bypass(self, reload_admin_auth):
        m = reload_admin_auth(
            {
                "ANIMUS_ADMIN_PASSWORD": "x",
                "ANIMUS_ADMIN_INSECURE": "1",
            }
        )
        # _admin_configured() True via insecure bypass; password check
        # still needs to match the env var.
        assert m._admin_configured() is True
        assert m.validate_credentials("admin", "x") is True

    def test_no_default_password_admin_admin(self, reload_admin_auth):
        """Regression: pre-0.4.6 default admin/admin must NOT work."""
        m = reload_admin_auth({})
        assert m.validate_credentials("admin", "admin") is False


def test_peer_secret_alone_never_configures_admin(reload_admin_auth):
    auth = reload_admin_auth({'ANIMUS_ADMIN_PASSWORD': 'fixture-password',
                              'ANIMUS_SERVER_SECRET': 'fixture-peer-secret'})
    assert not auth._admin_configured()
    assert not auth.validate_credentials('admin', 'fixture-password')
