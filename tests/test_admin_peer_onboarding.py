import io
import secrets
import zipfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from animus.server.app import admin_router
from animus.server import admin_routes


@pytest.fixture
def admin_client(monkeypatch, hub_config, engine):
    app = FastAPI()
    app.include_router(admin_router)
    monkeypatch.setattr(admin_routes, "get_config", lambda: hub_config)
    monkeypatch.setattr(admin_routes, "get_engine", lambda: engine)
    with TestClient(app) as client:
        yield client, app


def test_peer_onboarding_uses_exact_provisioned_id(admin_client, hub_config, monkeypatch, tmp_path):
    client, app = admin_client
    key = secrets.token_urlsafe(48)
    node_id = "Peer_With.Case"
    hub_config.server_peer_keys_file = tmp_path / "fixture-registry.json"
    monkeypatch.setattr(admin_routes, "peer_secret", lambda config, identity: {node_id: key}.get(identity, ""))
    monkeypatch.setattr(admin_routes, "provisioned_peer_ids", lambda path: [node_id])
    reveal = "/admin/api/peers/secret"
    installer = "/admin/api/peers/installer.zip"
    assert client.post(reveal, params={"node_id": node_id}).status_code == 401
    assert client.get(installer, params={"node_id": node_id}).status_code == 401

    app.dependency_overrides[admin_routes.require_admin] = lambda: {"username": "fixture-admin"}
    page = client.get("/admin/peers")
    assert page.status_code == 200
    assert "Select a provisioned Node ID" in page.text
    assert f'<option value="{node_id}">' in page.text
    assert "Copy PowerShell commands" in page.text
    assert "Shared Secret" not in page.text
    assert key not in page.text
    for method, path in (("POST", reveal), ("GET", installer)):
        assert client.request(method, path).status_code == 400
        assert client.request(method, path, params={"node_id": "Peer With.Case"}).status_code == 400
        result = client.request(method, path, params={"node_id": node_id.lower()})
        assert result.status_code == 409
        assert "no enabled key" in result.json()["detail"]
        assert key not in result.text

    params = {"node_id": node_id}
    assert client.head(installer, params=params).status_code == 204
    assert client.head(installer, params={"node_id": "unknown"}).status_code == 409
    result = client.post(reveal, params=params)
    assert result.json() == {"secret": key}
    assert result.headers["Cache-Control"] == "no-store"
    result = client.get(installer, params=params)
    assert result.status_code == 200
    assert result.headers["Cache-Control"] == "no-store"
    with zipfile.ZipFile(io.BytesIO(result.content)) as archive:
        env = dict(line.split("=", 1) for line in archive.read("peer.env").decode().splitlines()
                   if line.startswith("ANIMUS_"))
        assert key not in archive.read("install.sh").decode()
    assert env["ANIMUS_NODE_ID"] == node_id
    assert env["ANIMUS_SERVER_SECRET"] == key
    assert env["ANIMUS_BRANCH"] == "master"


def test_shared_key_mode_still_supports_reveal_and_generated_id(admin_client, hub_config):
    client, app = admin_client
    hub_config.server_peer_keys_file = None
    hub_config.server_secret = secrets.token_urlsafe(48)
    app.dependency_overrides[admin_routes.require_admin] = lambda: {"username": "fixture-admin"}
    page = client.get("/admin/peers")
    assert "Shared Secret" in page.text
    assert hub_config.server_secret not in page.text
    assert client.post("/admin/api/peers/secret").json() == {"secret": hub_config.server_secret}
    assert client.get("/admin/api/peers/installer.zip").status_code == 200
