"""Tests for animus.network.crypto."""

import time

import pytest

from animus.network.crypto import (
    create_auth_header,
    derive_peer_key,
    generate_token,
    sign_message,
    verify_auth_header,
    verify_signature,
)


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
