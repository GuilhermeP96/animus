"""Tests for animus.network.crypto."""

import time

import pytest

from animus.network.crypto import (
    create_auth_header,
    derive_peer_key,
    generate_nonce,
    generate_token,
    hash_body,
    sign_message,
    verify_auth_header,
    verify_signature,
    _replay_cache_clear,
)


@pytest.fixture(autouse=True)
def _clear_replay():
    _replay_cache_clear()
    yield
    _replay_cache_clear()


class TestGenerateToken:
    def test_returns_string(self):
        token = generate_token()
        assert isinstance(token, str)
        assert len(token) > 20

    def test_tokens_are_unique(self):
        t1 = generate_token()
        t2 = generate_token()
        assert t1 != t2


class TestDerivePeerKey:
    def test_deterministic(self):
        k1 = derive_peer_key("secret", "node-1")
        k2 = derive_peer_key("secret", "node-1")
        assert k1 == k2

    def test_different_for_different_nodes(self):
        k1 = derive_peer_key("secret", "node-1")
        k2 = derive_peer_key("secret", "node-2")
        assert k1 != k2

    def test_different_for_different_secrets(self):
        k1 = derive_peer_key("secret-a", "node-1")
        k2 = derive_peer_key("secret-b", "node-1")
        assert k1 != k2

    def test_returns_hex_string(self):
        key = derive_peer_key("secret", "node-1")
        assert len(key) == 64  # SHA-256 hex
        int(key, 16)  # Should parse as hex


class TestSignAndVerify:
    def test_sign_returns_hex(self):
        sig = sign_message("key", "message")
        assert len(sig) == 64
        int(sig, 16)

    def test_verify_valid_signature(self):
        sig = sign_message("key", "message")
        assert verify_signature("key", "message", sig) is True

    def test_verify_wrong_key(self):
        sig = sign_message("key", "message")
        assert verify_signature("wrong-key", "message", sig) is False

    def test_verify_wrong_message(self):
        sig = sign_message("key", "message")
        assert verify_signature("key", "wrong-message", sig) is False

    def test_verify_tampered_signature(self):
        sig = sign_message("key", "message")
        tampered = "0" * 64
        assert verify_signature("key", "message", tampered) is False

    def test_deterministic(self):
        s1 = sign_message("key", "message")
        s2 = sign_message("key", "message")
        assert s1 == s2


class TestAuthHeaders:
    def test_create_auth_header_has_required_fields(self):
        headers = create_auth_header("secret", "node-1")
        assert "X-Animus-Node" in headers
        assert "X-Animus-Timestamp" in headers
        assert "X-Animus-Signature" in headers
        assert headers["X-Animus-Node"] == "node-1"

    def test_verify_auth_header_roundtrip(self):
        headers = create_auth_header("secret", "node-1")
        # Convert to lowercase keys as FastAPI does
        lower = {k.lower(): v for k, v in headers.items()}
        assert verify_auth_header("secret", lower) is True

    def test_verify_rejects_wrong_secret(self):
        headers = create_auth_header("secret", "node-1")
        lower = {k.lower(): v for k, v in headers.items()}
        assert verify_auth_header("wrong-secret", lower) is False

    def test_verify_rejects_missing_fields(self):
        assert verify_auth_header("secret", {}) is False
        assert verify_auth_header("secret", {"x-animus-node": "n1"}) is False

    def test_verify_rejects_expired_timestamp(self):
        headers = create_auth_header("secret", "node-1")
        lower = {k.lower(): v for k, v in headers.items()}
        # Tamper timestamp to be old
        lower["x-animus-timestamp"] = str(int(time.time()) - 600)
        assert verify_auth_header("secret", lower, max_age=300) is False

    def test_verify_rejects_invalid_timestamp(self):
        headers = create_auth_header("secret", "node-1")
        lower = {k.lower(): v for k, v in headers.items()}
        lower["x-animus-timestamp"] = "not-a-number"
        assert verify_auth_header("secret", lower) is False

class TestNonce:
    def test_generate_nonce_unique(self):
        n1 = generate_nonce()
        n2 = generate_nonce()
        assert n1 != n2
        assert len(n1) == 32  # 16 bytes hex

    def test_replay_rejected_within_window(self):
        headers = create_auth_header("secret", "node-1", secure=True)
        lower = {k.lower(): v for k, v in headers.items()}
        # First call accepts
        assert verify_auth_header("secret", lower) is True
        # Same nonce again -> rejected
        assert verify_auth_header("secret", lower) is False

    def test_replay_cache_separates_by_node(self):
        h1 = create_auth_header("secret", "node-1", secure=True)
        h2 = create_auth_header("secret", "node-2", secure=True)
        l1 = {k.lower(): v for k, v in h1.items()}
        l2 = {k.lower(): v for k, v in h2.items()}
        assert verify_auth_header("secret", l1) is True
        assert verify_auth_header("secret", l2) is True

    def test_require_nonce_flag(self):
        # Build a header then strip the nonce
        headers = create_auth_header("secret", "node-1", secure=True)
        lower = {k.lower(): v for k, v in headers.items()}
        lower.pop("x-animus-nonce", None)
        # Without require_nonce, header structure is incomplete and
        # signature won't match anyway (it includes the nonce); this
        # is fine — we just verify require_nonce short-circuits.
        assert verify_auth_header("secret", lower, require_nonce=True) is False


class TestBodySigning:
    def test_hash_body_empty(self):
        assert hash_body(None) == ""
        assert hash_body("") == ""
        assert hash_body(b"") == ""

    def test_hash_body_deterministic(self):
        assert hash_body("hello") == hash_body("hello")
        assert hash_body(b"hello") == hash_body("hello")

    def test_signed_body_round_trip(self):
        body = b'{"node_id":"n1","limit":200}'
        headers = create_auth_header("secret", "node-1", body=body, secure=True)
        lower = {k.lower(): v for k, v in headers.items()}
        assert "x-animus-body-sha256" in lower
        assert verify_auth_header("secret", lower, body=body) is True

    def test_tampered_body_rejected(self):
        body = b'{"node_id":"n1","limit":200}'
        headers = create_auth_header("secret", "node-1", body=body, secure=True)
        lower = {k.lower(): v for k, v in headers.items()}
        tampered = b'{"node_id":"n1","limit":99999}'
        assert verify_auth_header("secret", lower, body=tampered) is False

    def test_body_hash_header_must_match_body(self):
        body = b"hello"
        headers = create_auth_header("secret", "node-1", body=body, secure=True)
        lower = {k.lower(): v for k, v in headers.items()}
        # Substitute a wrong body hash header — must be rejected even
        # before signature check.
        lower["x-animus-body-sha256"] = "0" * 64
        assert verify_auth_header("secret", lower, body=body) is False

    def test_empty_body_sig_compatible_with_body_send(self):
        # Header created without body; verifier called with body=b""
        headers = create_auth_header("secret", "node-1")
        lower = {k.lower(): v for k, v in headers.items()}
        assert verify_auth_header("secret", lower, body=b"") is True
