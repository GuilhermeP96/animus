"""End-to-end integration tests — collect → index → search → push → pull."""

import json
import secrets

import pytest
from fastapi.testclient import TestClient

from animus.collector.models import Memory, MemoryBatch, MemoryType
from animus.config import AnimusConfig
from animus.indexer.engine import IndexEngine
from animus.network.sync import SyncProtocol
from animus.network.crypto import create_auth_header
import animus.server.app as server_module
from animus.server.app import app


@pytest.fixture
def e2e_env(tmp_path):
    """Spin up a full local stack: config + engine + hub + client."""
    # Hub config
    hub_cfg = AnimusConfig(
        node_id="hub-e2e",
        node_name="hub",
        node_role="hub",
        data_dir=tmp_path / "hub",
        vscode_user_dir=tmp_path / "vscode",
        server_secret=secrets.token_urlsafe(48),
    )
    hub_cfg.ensure_dirs()
    engine = IndexEngine(hub_cfg.db_path)
    _ = engine.conn

    # Peer config
    peer_cfg = AnimusConfig(
        node_id="peer-e2e",
        node_name="peer",
        node_role="peer",
        data_dir=tmp_path / "peer",
        vscode_user_dir=tmp_path / "vscode",
    )
    peer_cfg.ensure_dirs()
    peer_engine = IndexEngine(peer_cfg.db_path)

    # Wire up the server module
    server_module._config = hub_cfg
    server_module._engine = engine
    server_module._connected_peers = {}

    class AuthenticatedPeerClient(TestClient):
        def request(self, method, url, **kwargs):
            body = kwargs.get('content')
            if kwargs.get('json') is not None:
                body = json.dumps(kwargs.pop('json'), separators=(',', ':'), ensure_ascii=False)
                kwargs['content'] = body
            headers = dict(kwargs.pop('headers', {}) or {})
            headers.update(create_auth_header(hub_cfg.server_secret, 'peer-e2e', body=body))
            if body is not None:
                headers['Content-Type'] = 'application/json'
            return super().request(method, url, headers=headers, **kwargs)

    client = AuthenticatedPeerClient(app)

    yield {
        "hub_cfg": hub_cfg,
        "hub_engine": engine,
        "peer_cfg": peer_cfg,
        "peer_engine": peer_engine,
        "client": client,
    }

    engine.close()
    peer_engine.close()
    server_module._config = None
    server_module._engine = None


HEADERS = {"X-Animus-Node": "peer-e2e"}


class TestE2EFlow:
    def test_full_collect_index_push_search(self, e2e_env):
        """Simulate: peer collects memories → indexes → pushes to hub → searches via hub."""
        peer_engine = e2e_env["peer_engine"]
        client = e2e_env["client"]

        # 1. "Collect" — create some memories locally on the peer
        memories = [
            Memory(
                type=MemoryType.COPILOT_CHAT,
                source_node="peer-e2e",
                content="Django ORM supports async queries since version 4.1",
                title="Django async ORM",
                workspace="aura-erp",
            ),
            Memory(
                type=MemoryType.WORKSPACE_MEMORY,
                source_node="peer-e2e",
                content="Always use pytest-asyncio with auto mode for async tests",
                title="Testing conventions",
                workspace="aura-erp",
            ),
            Memory(
                type=MemoryType.COPILOT_DEBUG,
                source_node="peer-e2e",
                content="Extension activated at 12:00:00 session_id=abc123",
                title="debug-line-1",
                workspace="aura-erp",
            ),
        ]

        # 2. Index locally
        for m in memories:
            peer_engine.index_memory(m)
        stats = peer_engine.get_stats()
        assert stats["total_memories"] == 3

        # 3. Push to hub via HTTP
        batch = MemoryBatch(
            node_id="peer-e2e",
            node_name="peer",
            memories=memories,
        )
        push_data = json.loads(SyncProtocol.push(batch))
        resp = client.post("/api/sync/push", json=push_data, headers=HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["received"] == 3
        assert data["new"] == 3
        assert data["skipped"] == 0

        # 4. Search on hub — should find Django memory
        search_resp = client.post(
            "/api/search",
            json={"query": "Django async", "limit": 5},
            headers=HEADERS,
        )
        assert search_resp.status_code == 200
        results = search_resp.json()
        assert results["count"] >= 1
        assert any("django" in r.get("content", "").lower() for r in results["results"])

        # 5. Pull from hub as a different peer
        pull_resp = client.post(
            "/api/sync/pull",
            json={"node_id": "other-peer", "limit": 100},
            headers={"X-Animus-Node": "other-peer"},
        )
        assert pull_resp.status_code == 200
        pull_data = pull_resp.json()
        assert pull_data["count"] == 3  # all 3 memories from peer-e2e

        # 6. Stats endpoint reflects indexed data
        stats_resp = client.get("/api/stats", headers=HEADERS)
        assert stats_resp.status_code == 200
        hub_stats = stats_resp.json()
        assert hub_stats["total_memories"] == 3

    def test_push_with_malformed_memories(self, e2e_env):
        """Verify malformed memories are skipped, valid ones are indexed."""
        client = e2e_env["client"]
        payload = {
            "type": "PUSH",
            "node_id": "peer-e2e",
            "node_name": "peer",
            "count": 3,
            "memories": [
                {
                    "type": "copilot_chat",
                    "source_node": "peer-e2e",
                    "content": "Valid memory content",
                    "title": "valid one",
                    "source_path": "",
                    "workspace": "test",
                    "timestamp": "2024-01-01T00:00:00Z",
                    "metadata": {},
                    "tags": [],
                    "sequence": 0,
                },
                {"bad": "data"},  # malformed
                {"also": "bad"},  # malformed
            ],
            "timestamp": "2024-01-01T00:00:00Z",
        }
        resp = client.post("/api/sync/push", json=payload, headers=HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert data["received"] == 1
        assert data["skipped"] == 2

    def test_duplicate_push_idempotent(self, e2e_env):
        """Pushing the same memory twice should not create duplicates."""
        client = e2e_env["client"]
        mem = {
            "type": "copilot_chat",
            "source_node": "peer-e2e",
            "content": "Unique memory for dedup test",
            "title": "dedup",
            "source_path": "",
            "workspace": "test",
            "timestamp": "2024-06-01T00:00:00Z",
            "metadata": {},
            "tags": [],
            "sequence": 0,
        }
        payload = {
            "type": "PUSH",
            "node_id": "peer-e2e",
            "node_name": "peer",
            "count": 1,
            "memories": [mem],
            "timestamp": "2024-06-01T00:00:00Z",
        }

        # First push
        r1 = client.post("/api/sync/push", json=payload, headers=HEADERS)
        assert r1.json()["new"] == 1

        # Second push — same memory
        r2 = client.post("/api/sync/push", json=payload, headers=HEADERS)
        assert r2.json()["new"] == 0  # duplicate, not new
