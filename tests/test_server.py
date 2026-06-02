"""Tests for animus.server.app (FastAPI endpoints)."""

import json

import pytest
from fastapi.testclient import TestClient

from animus.collector.models import MemoryType
from animus.config import AnimusConfig
from animus.indexer.engine import IndexEngine
import animus.server.app as server_module
from animus.server.app import app


@pytest.fixture
def hub_app(hub_config):
    """Set up the FastAPI app with test config/engine."""
    # Set module-level globals directly
    server_module._config = hub_config
    hub_config.server_secret = ""  # Dev mode — no auth
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
