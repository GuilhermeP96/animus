"""Cryptographic utilities for peer authentication.

Auth scheme: HMAC-SHA256 over a payload that binds together speaker
identity, timestamp, a one-shot nonce, and the request body hash.

Signed payload::

    f"{node_id}:{timestamp}:{nonce}:{body_hash}"

Wire format (HTTP headers, case-insensitive on the wire)::

    X-Animus-Node:        <node_id>
    X-Animus-Timestamp:   <unix_seconds>
    X-Animus-Nonce:       <hex>
    X-Animus-Body-SHA256: <hex of sha256(body)>   (optional, default "")
    X-Animus-Signature:   <hmac-sha256 hex of payload>

Backwards compatibility: peers older than 0.4.6 omit ``Nonce`` and
``Body-SHA256``. The verifier still accepts them (treating both as
empty strings) unless ``ANIMUS_REQUIRE_NONCE=1`` is set on the hub.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import threading
import time
from collections import OrderedDict
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


def generate_nonce() -> str:
    """16 random bytes as hex — collision-resistant within any
    practical replay window."""
    return secrets.token_hex(16)


def hash_body(body: bytes | str | None) -> str:
    """SHA-256 hex digest of a request body. Empty input -> ""."""
    if not body:
        return ""
    if isinstance(body, str):
        body = body.encode("utf-8")
    return hashlib.sha256(body).hexdigest()


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


def _build_payload(node_id: str, timestamp: str, nonce: str, body_hash: str) -> str:
    return f"{node_id}:{timestamp}:{nonce}:{body_hash}"


def _build_legacy_payload(node_id: str, timestamp: str) -> str:
    """Pre-0.4.6 payload. Kept so a hub on 0.4.6 can validate
    requests from peers still running 0.4.5 or older."""
    return f"{node_id}:{timestamp}"


def create_auth_header(
    shared_secret: str,
    node_id: str,
    body: bytes | str | None = None,
    *,
    secure: bool | None = None,
) -> dict[str, str]:
    """Create authentication headers for hub requests.

    By default, the **legacy** payload format is used so a 0.4.6
    peer can talk to a 0.4.5 hub during a rolling upgrade. Set
    ``secure=True`` (or ``ANIMUS_SECURE_AUTH=1``) once your hub is
    on 0.4.6+ to enable nonce + body-hash signing.
    """
    if secure is None:
        secure = os.environ.get("ANIMUS_SECURE_AUTH", "0") == "1"

    timestamp = str(int(time.time()))
    peer_key = derive_peer_key(shared_secret, node_id)

    if not secure:
        sig = sign_message(peer_key, _build_legacy_payload(node_id, timestamp))
        return {
            "X-Animus-Node": node_id,
            "X-Animus-Timestamp": timestamp,
            "X-Animus-Signature": sig,
        }

    nonce = generate_nonce()
    body_h = hash_body(body)
    sig = sign_message(peer_key, _build_payload(node_id, timestamp, nonce, body_h))
    headers = {
        "X-Animus-Node": node_id,
        "X-Animus-Timestamp": timestamp,
        "X-Animus-Nonce": nonce,
        "X-Animus-Signature": sig,
    }
    if body_h:
        headers["X-Animus-Body-SHA256"] = body_h
    return headers


# ── Replay protection ──────────────────────────────────────────────

_REPLAY_CACHE_MAX = 100_000
_replay_cache: "OrderedDict[tuple[str, str], float]" = OrderedDict()
_replay_lock = threading.Lock()


def _seen_recently(node_id: str, nonce: str, max_age: int) -> bool:
    """Return True if (node_id, nonce) was already seen inside the
    replay window. Records the pair if it's new."""
    if not nonce:
        # Pre-0.4.6 peer or a request that doesn't carry a nonce.
        # Timestamp window is the only defence in that case.
        return False
    key = (node_id, nonce)
    now = time.time()
    cutoff = now - max_age
    with _replay_lock:
        ts = _replay_cache.get(key)
        if ts is not None and ts >= cutoff:
            return True
        _replay_cache[key] = now
        _replay_cache.move_to_end(key)
        while len(_replay_cache) > _REPLAY_CACHE_MAX:
            _replay_cache.popitem(last=False)
    return False


def _replay_cache_clear() -> None:
    """Test-only: drop all remembered nonces."""
    with _replay_lock:
        _replay_cache.clear()


def verify_auth_header(
    shared_secret: str,
    headers: dict[str, str],
    max_age: int = 300,
    body: bytes | str | None = None,
    require_nonce: bool | None = None,
) -> bool:
    """Verify authentication headers from a peer.

    ``body`` is the raw request body received. When provided, the
    ``X-Animus-Body-SHA256`` header (when present) must match
    ``sha256(body)`` and the value the client signed.

    ``require_nonce`` defaults to the ``ANIMUS_REQUIRE_NONCE``
    environment flag. When True, requests without a nonce are
    rejected outright.
    """
    node_id = headers.get("x-animus-node", "")
    timestamp = headers.get("x-animus-timestamp", "")
    signature = headers.get("x-animus-signature", "")
    nonce = headers.get("x-animus-nonce", "")
    sent_body_hash = headers.get("x-animus-body-sha256", "")

    if not all([node_id, timestamp, signature]):
        return False

    if require_nonce is None:
        require_nonce = os.environ.get("ANIMUS_REQUIRE_NONCE", "0") == "1"
    if require_nonce and not nonce:
        return False

    try:
        ts = int(timestamp)
        if abs(time.time() - ts) > max_age:
            return False
    except ValueError:
        return False

    actual_body_hash = hash_body(body)
    if sent_body_hash and sent_body_hash != actual_body_hash:
        return False
    body_h = sent_body_hash or actual_body_hash

    if _seen_recently(node_id, nonce, max_age):
        return False

    peer_key = derive_peer_key(shared_secret, node_id)
    payload = _build_payload(node_id, timestamp, nonce, body_h)
    if verify_signature(peer_key, payload, signature):
        return True
    # Backwards compat: 0.4.5 and older peers don't send a nonce or
    # body hash and sign only ``f"{node_id}:{timestamp}"``. Accept
    # them only when the hub hasn't enabled strict nonce mode.
    if not require_nonce and not nonce and not sent_body_hash:
        legacy_payload = _build_legacy_payload(node_id, timestamp)
        if verify_signature(peer_key, legacy_payload, signature):
            return True
    return False
