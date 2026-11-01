import httpx
import pytest
from fastapi import HTTPException

from animus.server import licensing


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            request = httpx.Request("POST", "http://licensing/check")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError("failed", request=request, response=response)

    def json(self):
        return self.payload


class FakeClient:
    response = FakeResponse({"allowed": True, "status": "active"})
    calls = 0

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, *args, **kwargs):
        type(self).calls += 1
        return type(self).response


@pytest.fixture(autouse=True)
def reset(monkeypatch):
    licensing.clear_license_cache()
    FakeClient.calls = 0
    FakeClient.response = FakeResponse({"allowed": True, "status": "active"})
    monkeypatch.setenv("ANIMUS_LICENSE_API_URL", "http://licensing:8000")
    monkeypatch.setenv("ANIMUS_LICENSE_API_SECRET", "test-secret")
    monkeypatch.setattr(licensing.httpx, "AsyncClient", FakeClient)


@pytest.mark.asyncio
async def test_active_license_is_cached():
    first = await licensing.require_peer_license("node-1", node_name="Panthro")
    second = await licensing.require_peer_license("node-1", node_name="Panthro")
    assert first["status"] == "active"
    assert second["allowed"] is True
    assert FakeClient.calls == 1


@pytest.mark.asyncio
async def test_suspended_license_is_denied():
    FakeClient.response = FakeResponse({"allowed": False, "status": "suspended"})
    with pytest.raises(HTTPException) as exc:
        await licensing.require_peer_license("node-2")
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_missing_configuration_keeps_development_mode(monkeypatch):
    monkeypatch.delenv("ANIMUS_LICENSE_API_URL")
    monkeypatch.delenv("ANIMUS_LICENSE_API_SECRET")
    result = await licensing.require_peer_license("dev-node")
    assert result["status"] == "unmanaged"
