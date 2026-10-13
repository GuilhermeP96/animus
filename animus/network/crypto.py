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
empty strings) only with explicit ``ANIMUS_REQUIRE_NONCE=0`` during local legacy tests. Strict mode is the default.
"""

from __future__ import annotations

import hashlib
import heapq
import hmac
import os
import re
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


# Fingerprint only: the compromised former test fallback is never a valid key.
_REVOKED_SECRET_SHA256 = frozenset({
    'e82a6b79ae8c5fa691dfd50e923714fd121a125a2a50a568232065ce0b4dcd27',
})


def secret_is_revoked(secret: str) -> bool:
    return hashlib.sha256(secret.encode()).hexdigest() in _REVOKED_SECRET_SHA256


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

    Defaults to the **secure** payload format (nonce + body-hash signing)
    introduced in 0.4.6. Hubs on 0.4.6+ accept both formats via the legacy
    fallback in :func:`verify_auth_header`, but hubs configured with
    ``ANIMUS_REQUIRE_NONCE=1`` reject the legacy format outright. Set
    ``ANIMUS_SECURE_AUTH=0`` (or ``secure=False``) only when this peer
    must talk to a hub older than 0.4.6 during a rolling upgrade.
    """
    if not shared_secret or secret_is_revoked(shared_secret):
        raise ValueError("Missing or revoked peer secret")
    if secure is None:
        secure = os.environ.get("ANIMUS_SECURE_AUTH", "1") == "1"

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
_replay_expirations: list[tuple[float, tuple[str, str]]] = []


def _seen_recently(node_id: str, nonce: str, max_age: int, expires_at: float | None = None) -> bool:
    """Atomically consume a verified nonce; fail closed if live cache is full.

    Store the timestamp's validity deadline, including permitted future skew.
    Invalid signatures never call this function or consume nonce capacity.
    """
    if not nonce:
        return False
    key = (node_id, nonce)
    now = time.time()
    with _replay_lock:
        while _replay_expirations and _replay_expirations[0][0] < now:
            expiry, old = heapq.heappop(_replay_expirations)
            if _replay_cache.get(old) == expiry:
                del _replay_cache[old]
        if key in _replay_cache or len(_replay_cache) >= _REPLAY_CACHE_MAX:
            return True
        expiry = expires_at if expires_at is not None else now + max_age
        _replay_cache[key] = expiry
        heapq.heappush(_replay_expirations, (expiry, key))
    return False


def _replay_cache_clear() -> None:
    """Test-only: drop all remembered nonces."""
    with _replay_lock:
        _replay_cache.clear()
        _replay_expirations.clear()


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
    if not shared_secret or secret_is_revoked(shared_secret):
        return False
    node_id = headers.get("x-animus-node", "")
    timestamp = headers.get("x-animus-timestamp", "")
    signature = headers.get("x-animus-signature", "")
    nonce = headers.get("x-animus-nonce", "")
    sent_body_hash = headers.get("x-animus-body-sha256", "")

    if not all(isinstance(value, str) for value in (node_id, timestamp, signature, nonce, sent_body_hash)):
        return False
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", node_id):
        return False
    if not re.fullmatch(r"[0-9]{1,12}", timestamp) or not re.fullmatch(r"[0-9a-f]{64}", signature):
        return False
    if nonce and not re.fullmatch(r"[0-9a-f]{32}", nonce):
        return False
    if sent_body_hash and not re.fullmatch(r"[0-9a-f]{64}", sent_body_hash):
        return False
    if not 0 < max_age <= 300:
        return False

    if require_nonce is None:
        require_nonce = os.environ.get("ANIMUS_REQUIRE_NONCE", "1") == "1"
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

    peer_key = derive_peer_key(shared_secret, node_id)
    payload = _build_payload(node_id, timestamp, nonce, body_h)
    if verify_signature(peer_key, payload, signature):
        return not _seen_recently(node_id, nonce, max_age, expires_at=ts + max_age)
    # Backwards compat: 0.4.5 and older peers don't send a nonce or
    # body hash and sign only ``f"{node_id}:{timestamp}"``. Accept
    # them only when the hub hasn't enabled strict nonce mode.
    if not require_nonce and not nonce and not sent_body_hash:
        legacy_payload = _build_legacy_payload(node_id, timestamp)
        if verify_signature(peer_key, legacy_payload, signature):
            return True
    return False
