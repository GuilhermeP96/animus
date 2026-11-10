from fastapi.testclient import TestClient

from animus.server.app import app, _rate_buckets
from animus.server.security_headers import CONTENT_SECURITY_POLICY, SECURITY_HEADERS


def test_policy_keeps_turnstile_and_pinned_dashboard_scripts():
    directives = dict(item.split(" ", 1) for item in CONTENT_SECURITY_POLICY.split("; "))
    assert "https://challenges.cloudflare.com" in directives["script-src"]
    assert "https://cdn.jsdelivr.net" in directives["script-src"]
    assert directives["frame-src"] == "https://challenges.cloudflare.com"
    assert directives["object-src"] == "'none'"
    assert directives["frame-ancestors"] == "'none'"
    assert "*" not in directives["script-src"]


def test_headers_cover_success_not_found_and_rate_limit(monkeypatch):
    # No lifespan or production store is needed for these transport checks.
    _rate_buckets.clear()
    monkeypatch.setattr("animus.server.app._engine", object())
    try:
        client = TestClient(app)
        for path, expected in (("/health/live", 200), ("/missing-policy-test", 404)):
            response = client.get(path)
            assert response.status_code == expected
            for name, value in SECURITY_HEADERS.items():
                assert response.headers[name] == value
        import time
        _rate_buckets["testclient"] = [time.monotonic()] * 60
        response = client.get("/health/live")
        assert response.status_code == 429
        assert response.headers["content-security-policy"] == CONTENT_SECURITY_POLICY
    finally:
        _rate_buckets.clear()
