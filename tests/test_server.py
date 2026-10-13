"""Tests for animus.server.app (FastAPI endpoints)."""

import time

import pytest
from fastapi.testclient import TestClient

from animus.indexer.engine import IndexEngine
import animus.server.app as server_module
from animus.server.app import app
from animus.server.admin_auth import AdminSession, require_admin


@pytest.fixture
def hub_app(hub_config):
    """Set up the FastAPI app with test config/engine."""
    # Set module-level globals directly
    server_module._config = hub_config
    hub_config.server_secret = ""  # Explicit loopback-only fixture bypass.
    hub_config.allow_insecure_dev_auth = True
    hub_config.server_host = "127.0.0.1"
    engine = IndexEngine(hub_config.db_path)
    _ = engine.conn
    server_module._engine = engine
    server_module._connected_peers = {}

    yield app

    engine.close()
    server_module._config = None
    server_module._engine = None


@pytest.fixture
def client(hub_app):
    return TestClient(hub_app)


@pytest.fixture
def auth_headers():
    """Auth headers that pass verify_peer (no secret = dev mode)."""
    return {"X-Animus-Node": "test-peer-01"}


class TestRootAndHealth:
    def test_liveness_does_not_scan_memory_index(self, client, monkeypatch):
        def expensive_stats():
            raise AssertionError("liveness must not scan the index")
        monkeypatch.setattr(server_module._engine, "get_stats", expensive_stats)
        resp = client.get("/health/live")
        assert resp.status_code == 200
        assert resp.json() == {"status": "alive"}

    def test_root(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Animus Hub"
        assert data["codename"] == "Animus Hub"

    def test_health(self, client, auth_headers):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"
        assert "memories" in data


class TestPushEndpoint:
    def test_push_memories(self, client, auth_headers):
        payload = {
            "type": "PUSH",
            "node_id": "test-peer-01",
            "node_name": "test-machine",
            "count": 1,
            "memories": [
                {
                    "type": "copilot_chat",
                    "source_node": "test-peer-01",
                    "content": "How to use Docker?",
                    "title": "Docker question",
                    "source_path": "/test",
                    "workspace": "test-proj",
                    "timestamp": "2024-01-01T00:00:00Z",
                    "metadata": {},
                    "tags": [],
                    "sequence": 0,
                }
            ],
            "timestamp": "2024-01-01T00:00:00Z",
        }
        resp = client.post("/api/sync/push", json=payload, headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["received"] >= 1


class TestPullEndpoint:
    def test_pull_memories(self, client, auth_headers):
        payload = {"node_id": "test-peer-01", "limit": 10}
        resp = client.post("/api/sync/pull", json=payload, headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["type"] == "PULL_RESPONSE"
        assert isinstance(data["memories"], list)


class TestSearchEndpoint:
    def test_search_empty(self, client, auth_headers):
        payload = {"query": "docker", "limit": 5}
        resp = client.post("/api/search", json=payload, headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "results" in data

    def test_search_after_push(self, client, auth_headers):
        # Push a memory
        push_payload = {
            "type": "PUSH",
            "node_id": "peer-02",
            "node_name": "other-machine",
            "count": 1,
            "memories": [
                {
                    "type": "copilot_chat",
                    "source_node": "peer-02",
                    "content": "FastAPI supports async endpoints with Python type hints",
                    "title": "FastAPI async",
                    "source_path": "/test",
                    "workspace": "api-project",
                    "timestamp": "2024-01-01T00:00:00Z",
                    "metadata": {},
                    "tags": ["python", "fastapi"],
                    "sequence": 0,
                }
            ],
            "timestamp": "2024-01-01T00:00:00Z",
        }
        client.post("/api/sync/push", json=push_payload, headers=auth_headers)

        # Search
        search_payload = {"query": "FastAPI async", "limit": 5}
        resp = client.post("/api/search", json=search_payload, headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] >= 1


class TestStatsEndpoint:
    def test_stats(self, client, auth_headers):
        resp = client.get("/api/stats", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "total_memories" in data


class TestObsidianAdmin:
    @staticmethod
    def _admin_override():
        now = time.time()
        return AdminSession(user="test-admin", iat=now, exp=now + 60)

    @staticmethod
    def _push_note(client, auth_headers):
        payload = {
            "type": "PUSH",
            "node_id": "obsidian-peer",
            "node_name": "knowledge-node",
            "count": 1,
            "memories": [{
                "id": "obsidian-test-note",
                "type": "obsidian_note",
                "source_node": "obsidian-peer",
                "source_path": "obsidian://Panthro/Projetos/Animus.md",
                "workspace": "Panthro",
                "timestamp": "2026-09-11T00:00:00Z",
                "title": "Arquitetura Animus",
                "content": "---\nstatus: verificado\n---\n# Arquitetura",
                "metadata": {
                    "vault": "Panthro",
                    "relative_path": "Projetos/Animus.md",
                    "frontmatter": {
                        "projeto": "Animus",
                        "status": "verificado",
                        "sensibilidade": "interno",
                    },
                    "missing": False,
                },
                "tags": ["animus"],
                "sequence": 0,
            }],
            "timestamp": "2026-09-11T00:00:00Z",
        }
        response = client.post("/api/sync/push", json=payload, headers=auth_headers)
        assert response.status_code == 200

    def test_obsidian_page_and_read_only_apis(self, client, auth_headers):
        self._push_note(client, auth_headers)
        app.dependency_overrides[require_admin] = self._admin_override
        try:
            stats = client.get("/admin/api/obsidian/stats")
            assert stats.status_code == 200
            assert stats.json()["verified"] == 1

            notes = client.get(
                "/admin/api/obsidian/notes",
                params={"vault": "Panthro", "status": "verificado"},
            )
            assert notes.status_code == 200
            assert notes.json()["notes"][0]["project"] == "Animus"
            assert "content" not in notes.json()["notes"][0]

            page = client.get("/admin/obsidian")
            assert page.status_code == 200
            assert "Arquitetura Animus" in page.text
        finally:
            app.dependency_overrides.pop(require_admin, None)

    def test_obsidian_apis_require_admin(self, client):
        response = client.get("/admin/api/obsidian/stats")
        assert response.status_code == 401

    def test_memory_detail_has_safe_markdown_and_mermaid_renderer(self, client, auth_headers):
        self._push_note(client, auth_headers)
        app.dependency_overrides[require_admin] = self._admin_override
        try:
            page = client.get("/admin/memories/obsidian-test-note")
            assert page.status_code == 200
            assert "mermaid@11.12.2" in page.text
            assert "securityLevel: 'strict'" in page.text
            assert "typeof DOMPurify === 'undefined'" in page.text
            assert "pre code.language-mermaid" in page.text
        finally:
            app.dependency_overrides.pop(require_admin, None)


class TestRecentEndpoint:
    def test_recent(self, client, auth_headers):
        resp = client.get("/api/memories/recent?limit=5", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "memories" in data


class TestPeersEndpoint:
    def test_peers_empty(self, client, auth_headers):
        resp = client.get("/api/peers", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data["peers"], list)

    def test_peer_identity_uses_hostname_without_alias(self, client, auth_headers):
        payload = {
            "type": "PUSH", "node_id": "panthro-id", "node_name": "",
            "node_version": "0.8.3", "hostname": "Panthro",
            "os_name": "Windows", "os_version": "11", "memories": [],
        }
        assert client.post("/api/sync/push", json=payload, headers=auth_headers).status_code == 200
        peers = client.get("/api/peers", headers=auth_headers).json()["peers"]
        peer = next(item for item in peers if item["node_id"] == "panthro-id")
        assert peer["display_name"] == "Panthro"
        assert peer["hostname"] == "Panthro"
        assert peer["os_name"] == "Windows"
        assert peer["node_version"] == "0.8.3"

    def test_registered_peer_can_download_own_update_kit(self, client, hub_config):
        import io
        import zipfile
        from animus.network.crypto import create_auth_header, _replay_cache_clear

        _replay_cache_clear()
        hub_config.server_secret = "test-shared-secret"
        server_module._note_peer_activity(
            "panthro-id", hostname="Panthro", os_name="Windows", node_version="0.8.3"
        )
        headers = create_auth_header(
            hub_config.server_secret, "panthro-id", body=None, secure=True
        )
        response = client.get("/api/peers/update-kit.zip", headers=headers)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            names = archive.namelist()
            assert names == [
                "peer.env", "install.sh", "install.ps1", "install.bat",
                "COPILOT.md", "README.md",
            ]
            assert all("/" not in name for name in names)
            installer_bytes = archive.read("install.ps1")
            assert installer_bytes.startswith(b"\xef\xbb\xbf")
            installer = installer_bytes.decode("utf-8-sig")
            batch = archive.read("install.bat").decode()
            assert "Get-ScheduledTask -TaskName 'AnimusPeerDaemon'" in installer
            assert "Test-Path $installedSource" in installer
            assert "git -C $installDir fetch" in installer
            assert "exit $installExitCode" in installer
            assert "-Verb RunAs" not in batch
            peer_env = archive.read("peer.env").decode()
        assert "ANIMUS_NODE_ID=panthro-id" in peer_env
        assert "ANIMUS_NODE_NAME=Panthro" in peer_env
        assert "ANIMUS_OS_HINT=Windows" in peer_env

    def test_registered_peer_can_download_hub_wheel(
        self, client, hub_config, tmp_path, monkeypatch
    ):
        import hashlib
        from animus import __version__
        from animus.network.crypto import create_auth_header, _replay_cache_clear

        package = tmp_path / f"animus-{__version__}-py3-none-any.whl"
        package.write_bytes(b"current-hub-wheel")
        monkeypatch.setenv("ANIMUS_PACKAGE_DIR", str(tmp_path))
        _replay_cache_clear()
        hub_config.server_secret = "test-shared-secret"
        headers = create_auth_header(
            hub_config.server_secret, "panthro-id", body=None, secure=True
        )
        response = client.get("/api/peers/package.whl", headers=headers)
        assert response.status_code == 200
        assert response.content == b"current-hub-wheel"
        assert response.headers["x-animus-version"] == __version__
        assert response.headers["x-animus-package-sha256"] == hashlib.sha256(
            response.content
        ).hexdigest()

class TestSecureAuth:
    """v0.4.6 — body-bound HMAC + replay protection at the HTTP layer."""

    @pytest.fixture
    def secured_client(self, hub_app, hub_config):
        from animus.network.crypto import _replay_cache_clear
        _replay_cache_clear()
        hub_config.server_secret = "test-shared-secret"
        return TestClient(hub_app)

    def test_unsigned_request_rejected(self, secured_client):
        resp = secured_client.post(
            "/api/sync/pull",
            json={"node_id": "n1", "limit": 5},
            headers={"X-Animus-Node": "n1"},
        )
        assert resp.status_code == 401

    def test_signed_request_accepted(self, secured_client):
        from animus.network.crypto import create_auth_header
        body = b'{"node_id":"n1","limit":5}'
        headers = create_auth_header("test-shared-secret", "n1", body=body, secure=True)
        resp = secured_client.post(
            "/api/sync/pull",
            content=body,
            headers={**headers, "Content-Type": "application/json"},
        )
        assert resp.status_code == 200

    def test_tampered_body_rejected(self, secured_client):
        from animus.network.crypto import create_auth_header
        body = b'{"node_id":"n1","limit":5}'
        headers = create_auth_header("test-shared-secret", "n1", body=body, secure=True)
        # Send a different body but the original headers
        resp = secured_client.post(
            "/api/sync/pull",
            content=b'{"node_id":"n1","limit":99999}',
            headers={**headers, "Content-Type": "application/json"},
        )
        assert resp.status_code == 401

    def test_replay_rejected(self, secured_client):
        from animus.network.crypto import create_auth_header
        body = b'{"node_id":"n1","limit":5}'
        headers = create_auth_header("test-shared-secret", "n1", body=body, secure=True)
        h = {**headers, "Content-Type": "application/json"}
        # First request OK
        r1 = secured_client.post("/api/sync/pull", content=body, headers=h)
        assert r1.status_code == 200
        # Replay same headers + body -> rejected
        r2 = secured_client.post("/api/sync/pull", content=body, headers=h)
        assert r2.status_code == 401

    def test_wrong_secret_rejected(self, secured_client):
        from animus.network.crypto import create_auth_header
        body = b'{"node_id":"n1","limit":5}'
        headers = create_auth_header("wrong-secret", "n1", body=body, secure=True)
        resp = secured_client.post(
            "/api/sync/pull",
            content=body,
            headers={**headers, "Content-Type": "application/json"},
        )
        assert resp.status_code == 401

    def test_authenticated_node_must_match_body(self, secured_client):
        from animus.network.crypto import create_auth_header
        body = b'{"node_id":"n2","limit":5}'
        headers = create_auth_header("test-shared-secret", "n1", body=body, secure=True)
        resp = secured_client.post(
            "/api/sync/pull",
            content=body,
            headers={**headers, "Content-Type": "application/json"},
        )
        assert resp.status_code == 403


class TestRemediationReadiness:
    def test_public_no_secret_is_fail_closed(self, client, hub_config):
        hub_config.allow_insecure_dev_auth = False
        hub_config.server_host = '0.0.0.0'
        assert client.get('/api/stats', headers={'X-Animus-Node': 'fixture-node'}).status_code == 401

    def test_health_ignores_writer_count_lock_and_detects_corruption(self, client, tmp_path):
        engine = server_module._engine
        with engine._lock:
            assert client.get('/health').status_code == 200
        corrupt = tmp_path / 'corrupt.sqlite3'
        corrupt.write_bytes(b'corrupt-fixture-database' * 512)
        engine.db_path = corrupt
        response = client.get('/health')
        assert response.status_code == 503
        assert response.json() == {'status': 'unhealthy', 'database': 'unavailable'}

    def test_per_node_credentials_do_not_fall_back(self, client, hub_config, tmp_path):
        import json
        import secrets
        from animus.network.crypto import create_auth_header, _replay_cache_clear
        _replay_cache_clear()
        key = secrets.token_urlsafe(48)
        other = secrets.token_urlsafe(48)
        registry = tmp_path / 'peer-keys.json'
        registry.write_text(json.dumps({'version': 1, 'peers': {
            'node-one': {'enabled': True, 'secret': key},
            'node-two': {'enabled': True, 'secret': other}}}))
        registry.chmod(0o600)
        hub_config.server_peer_keys_file = registry
        assert client.get('/api/stats', headers=create_auth_header(key, 'node-one')).status_code == 200
        assert client.get('/api/stats', headers=create_auth_header(key, 'node-two')).status_code == 401
        assert client.get('/api/stats', headers=create_auth_header(hub_config.server_secret or key, 'unknown')).status_code == 401
