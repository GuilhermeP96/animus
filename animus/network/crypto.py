"""Cryptographic utilities for peer authentication."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass


@dataclass
class PeerCredentials:
    """Credentials for a peer node."""

    node_id: str
    token: str
    created_at: float


def generate_token() -> str:
    """Generate a secure random token for peer auth."""
    return secrets.token_urlsafe(32)


def derive_peer_key(shared_secret: str, node_id: str) -> str:
    """Derive a peer-specific key from shared secret + node ID."""
    raw = f"{shared_secret}:{node_id}".encode()
    return hashlib.sha256(raw).hexdigest()


def sign_message(key: str, message: str) -> str:
    """Sign a message with HMAC-SHA256."""
    return hmac.new(key.encode(), message.encode(), hashlib.sha256).hexdigest()


def verify_signature(key: str, message: str, signature: str) -> bool:
    """Verify an HMAC-SHA256 signature (constant-time)."""
    expected = sign_message(key, message)
    return hmac.compare_digest(expected, signature)


def create_auth_header(shared_secret: str, node_id: str) -> dict[str, str]:
    """Create authentication headers for hub requests."""
    timestamp = str(int(time.time()))
    peer_key = derive_peer_key(shared_secret, node_id)
    payload = f"{node_id}:{timestamp}"
    sig = sign_message(peer_key, payload)
    return {
        "X-Animus-Node": node_id,
        "X-Animus-Timestamp": timestamp,
        "X-Animus-Signature": sig,
    }


def verify_auth_header(shared_secret: str, headers: dict[str, str], max_age: int = 300) -> bool:
    """Verify authentication headers from a peer."""
    node_id = headers.get("x-animus-node", "")
    timestamp = headers.get("x-animus-timestamp", "")
    signature = headers.get("x-animus-signature", "")

    if not all([node_id, timestamp, signature]):
        return False

    # Check timestamp freshness
    try:
        ts = int(timestamp)
        if abs(time.time() - ts) > max_age:
            return False
    except ValueError:
        return False

    peer_key = derive_peer_key(shared_secret, node_id)
    payload = f"{node_id}:{timestamp}"
    return verify_signature(peer_key, payload, signature)
