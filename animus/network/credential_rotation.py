"""Offline bounded recovery envelopes for independently verified X25519 keys.

Old HMAC, an entitlement lookup or unsigned CF headers are NOT recovery trust.
The caller must verify the recipient key over an independent channel first.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import secrets
import time

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


def public_bytes(key: X25519PublicKey) -> bytes:
    return key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def fingerprint(key: bytes) -> str:
    return hashlib.sha256(key).hexdigest()


def _key(shared: bytes, context: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None,
                info=b'animus-peer-rotation-v1:' + context).derive(shared)


def seal(node_id: str, new_secret: str, recipient: bytes, approved_fingerprint: str,
         rotation_id: str, expires_at: int) -> dict:
    if not re.fullmatch(r'[A-Za-z0-9_.-]{1,128}', node_id) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,128}', rotation_id):
        raise ValueError('Invalid recovery identity')
    if fingerprint(recipient) != approved_fingerprint:
        raise ValueError('Recipient fingerprint does not match independent approval')
    if not 0 < expires_at - time.time() <= 86400:
        raise ValueError('Recovery envelope validity must be at most24 hours')
    if len(new_secret) < 43 or len(set(new_secret)) < 8:
        raise ValueError('Rotation requires a generated strong credential')
    metadata = {'version': 1, 'node_id': node_id, 'rotation_id': rotation_id,
                'expires_at': expires_at, 'recipient_sha256': approved_fingerprint}
    context = json.dumps(metadata, sort_keys=True, separators=(',', ':')).encode()
    ephemeral = X25519PrivateKey.generate()
    nonce = secrets.token_bytes(12)
    payload = json.dumps({'server_secret': new_secret}, separators=(',', ':')).encode()
    cipher = AESGCM(_key(ephemeral.exchange(X25519PublicKey.from_public_bytes(recipient)), context))
    return {**metadata, 'ephemeral_public': base64.b64encode(public_bytes(ephemeral.public_key())).decode(),
            'nonce': base64.b64encode(nonce).decode(),
            'ciphertext': base64.b64encode(cipher.encrypt(nonce, payload, context)).decode()}


def envelope_digest(envelope: dict) -> str:
    return hashlib.sha256(json.dumps(envelope, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def unseal(envelope: dict, recipient: X25519PrivateKey, expected_node: str,
           expected_rotation: str, expected_digest: str) -> str:
    # This digest must arrive through the independently authenticated operator
    # channel; encryption alone does not authenticate the package sender.
    if not secrets.compare_digest(envelope_digest(envelope), expected_digest):
        raise ValueError('Recovery package does not match independently approved digest')
    if envelope.get('version') != 1 or envelope.get('node_id') != expected_node or envelope.get('rotation_id') != expected_rotation:
        raise ValueError('Recovery envelope identity or rotation mismatch')
    if not time.time() < envelope.get('expires_at', 0) <= time.time() + 86400:
        raise ValueError('Recovery envelope expired or has invalid validity')
    own = public_bytes(recipient.public_key())
    if envelope.get('recipient_sha256') != fingerprint(own):
        raise ValueError('Recovery envelope recipient mismatch')
    metadata = {key: envelope[key] for key in ('version', 'node_id', 'rotation_id', 'expires_at', 'recipient_sha256')}
    context = json.dumps(metadata, sort_keys=True, separators=(',', ':')).encode()
    peer = X25519PublicKey.from_public_bytes(base64.b64decode(envelope['ephemeral_public'], validate=True))
    cipher = AESGCM(_key(recipient.exchange(peer), context))
    payload = cipher.decrypt(base64.b64decode(envelope['nonce'], validate=True),
                             base64.b64decode(envelope['ciphertext'], validate=True), context)
    value = json.loads(payload)['server_secret']
    if not isinstance(value, str) or len(value) < 43 or len(set(value)) < 8:
        raise ValueError('Recovery credential is invalid')
    return value
