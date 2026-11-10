"""Real SQLite/HMAC/X25519 regressions; no native-control or LLM simulation."""
import base64
import importlib.util
import json
import os
from pathlib import Path
import secrets
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

from animus.network import crypto
from animus.network.credential_rotation import seal, unseal, public_bytes, fingerprint, envelope_digest
from animus.server.peer_keys import peer_secret


def lower(headers):
    return {key.lower(): value for key, value in headers.items()}


def test_invalid_signature_does_not_poison_nonce():
    crypto._replay_cache_clear()
    key = secrets.token_urlsafe(48)
    headers = lower(crypto.create_auth_header(key, 'fixture-node'))
    assert not crypto.verify_auth_header(key, {**headers, 'x-animus-signature': '0' * 64})
    assert crypto.verify_auth_header(key, headers)
    assert not crypto.verify_auth_header(key, headers)


def test_simultaneous_replay_accepts_once():
    crypto._replay_cache_clear()
    key = secrets.token_urlsafe(48)
    headers = lower(crypto.create_auth_header(key, 'fixture-node'))
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda _: crypto.verify_auth_header(key, headers), range(8)))
    assert sum(results) == 1


def test_live_replay_cache_cannot_be_evicted(monkeypatch):
    crypto._replay_cache_clear()
    monkeypatch.setattr(crypto, '_REPLAY_CACHE_MAX', 2)
    key = secrets.token_urlsafe(48)
    headers = [lower(crypto.create_auth_header(key, 'fixture-node')) for _ in range(3)]
    assert crypto.verify_auth_header(key, headers[0])
    assert crypto.verify_auth_header(key, headers[1])
    assert not crypto.verify_auth_header(key, headers[2])
    assert not crypto.verify_auth_header(key, headers[0])
    crypto._replay_cache_clear()


def test_missing_secret_and_legacy_without_nonce_refused():
    crypto._replay_cache_clear()
    key = secrets.token_urlsafe(48)
    headers = lower(crypto.create_auth_header(key, 'fixture-node', secure=False))
    assert not crypto.verify_auth_header(key, headers)
    assert not crypto.verify_auth_header('', headers)
    with pytest.raises(ValueError):
        crypto.create_auth_header('', 'fixture-node')


@pytest.mark.skipif(os.name != 'posix', reason='Linux hub registry uses POSIX operator ownership; Windows is a native peer')
def test_per_node_registry_is_authoritative(hub_config, tmp_path):
    key = secrets.token_urlsafe(48)
    registry = tmp_path / 'peer-keys.json'
    registry.write_text(json.dumps({'version': 1, 'peers': {'node-one': {'enabled': True, 'secret': key}}}))
    registry.chmod(0o600)
    hub_config.server_peer_keys_file = registry
    assert peer_secret(hub_config, 'node-one') == key
    assert peer_secret(hub_config, 'node-two') == ''  # Never use shared fallback.
    registry.chmod(0o644)
    # Change mode does not change cached parse identity: safety checked each call.
    with pytest.raises(ValueError):
        peer_secret(hub_config, 'node-one')


@pytest.mark.skipif(os.name != 'posix', reason='Linux hub registry uses POSIX operator ownership')
def test_registry_rotation_invalidates_old_node_key(hub_config, tmp_path):
    registry = tmp_path / 'peer-keys.json'
    key = secrets.token_urlsafe(48)
    registry.write_text(json.dumps({'version': 1, 'peers': {'node-one': {'enabled': True, 'secret': key}}}))
    registry.chmod(0o600)
    hub_config.server_peer_keys_file = registry
    assert peer_secret(hub_config, 'node-one') == key
    replacement = tmp_path / 'new-registry.json'
    fresh = secrets.token_urlsafe(48)
    replacement.write_text(json.dumps({'version': 1, 'peers': {'node-one': {'enabled': True, 'secret': fresh}}}))
    replacement.chmod(0o600)
    replacement.replace(registry)
    assert peer_secret(hub_config, 'node-one') == fresh
    crypto._replay_cache_clear()
    assert not crypto.verify_auth_header(fresh, lower(crypto.create_auth_header(key, 'node-one')))


def test_encrypted_rotation_requires_independent_identity_digest():
    recipient = X25519PrivateKey.generate()
    raw = public_bytes(recipient.public_key())
    key = secrets.token_urlsafe(48)
    envelope = seal('node-one', key, raw, fingerprint(raw), 'fixture-rotation', int(time.time()) + 60)
    digest = envelope_digest(envelope)
    assert key not in json.dumps(envelope)
    assert unseal(envelope, recipient, 'node-one', 'fixture-rotation', digest) == key
    with pytest.raises(ValueError):
        unseal(envelope, recipient, 'node-two', 'fixture-rotation', digest)
    with pytest.raises(ValueError):
        unseal(envelope, recipient, 'node-one', 'fixture-rotation', '0' * 64)
    changed = {**envelope, 'ciphertext': base64.b64encode(b'tampered').decode()}
    with pytest.raises(InvalidTag):
        unseal(changed, recipient, 'node-one', 'fixture-rotation', envelope_digest(changed))
    with pytest.raises(ValueError):
        expired = {**envelope, 'expires_at': int(time.time()) - 1}
        unseal(expired, recipient, 'node-one', 'fixture-rotation', envelope_digest(expired))
    with pytest.raises(ValueError):
        seal('node-one', key, raw, '0' * 64, 'fixture-rotation', int(time.time()) + 60)


@pytest.mark.skipif(os.name != 'posix', reason='Linux administrative registry generator requires POSIX ownership')
def test_offline_rotation_artifacts_private_and_not_activated(tmp_path):
    spec = importlib.util.spec_from_file_location('prepare_rotation', Path(__file__).parents[1] / 'scripts/security/prepare-peer-rotation.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    recipient = X25519PrivateKey.generate()
    raw = public_bytes(recipient.public_key())
    approval = tmp_path / 'approved.json'
    approval.write_text(json.dumps({'node-one': {'public_key': base64.b64encode(raw).decode(),
        'verified_sha256': fingerprint(raw), 'rotation_id':'fixture-rotation', 'expires_at':int(time.time())+300, 'independent_channel': {'method': 'existing-ssh-publickey', 'evidence_id': 'disposable-fixture-key-verification'}}}))
    approval.chmod(0o600)
    output = tmp_path / 'prepared'
    receipt = module.prepare(approval, output, 'fixture-rotation')
    assert receipt['activated'] is False
    assert output.stat().st_mode & 0o777 == 0o700
    registry = json.loads((output / 'peer-keys.json').read_text())
    for path in output.iterdir():
        assert path.stat().st_mode & 0o777 == 0o600
    envelope = json.loads((output / 'node-one.rotation.json').read_text())
    assert unseal(envelope, recipient, 'node-one', 'fixture-rotation',
                  receipt['envelope_sha256']['node-one']) == registry['peers']['node-one']['secret']


def test_health_uses_real_database_but_not_writer_lock(engine):
    with engine._lock:
        engine.check_health()  # Independent read-only connection.
        assert engine.get_stats()['total_memories'] == 0
    engine.close()
    engine.db_path = engine.db_path.parent / 'corrupt-fixture.sqlite3'
    engine.db_path.write_bytes(b'not-a-sqlite-database' * 512)
    with pytest.raises(sqlite3.DatabaseError):
        engine.check_health()


def test_stats_cache_avoids_repeated_scans_and_marks_age(populated_engine):
    queries = []
    populated_engine.conn.set_trace_callback(queries.append)
    first = populated_engine.get_stats()
    assert first['total_memories'] == 7
    assert 0 <= first['stats_age_seconds'] < 1
    queries.clear()
    second = populated_engine.get_stats()
    assert second['total_memories'] == 7
    assert second['stats_age_seconds'] >= 0
    assert queries == []
    populated_engine._stats_cached_at = time.monotonic() - 31
    assert populated_engine.cached_stats()['stats_status'] == 'stale'
    refreshed = populated_engine.get_stats()
    assert queries == []  # Refresh never touches writer connection.
    assert refreshed['total_memories'] == 7
    assert refreshed['stats_status'] == 'fresh'


def test_configured_revocation_is_permanent_for_peer_auth(monkeypatch):
    key = secrets.token_urlsafe(48)
    headers = lower(crypto.create_auth_header(key, 'fixture-node'))
    revoked = {crypto.hashlib.sha256(key.encode()).hexdigest(), *crypto._REVOKED_SECRET_SHA256}
    monkeypatch.setattr(crypto, '_REVOKED_SECRET_SHA256', frozenset(revoked))
    assert crypto.secret_is_revoked(key)
    assert not crypto.verify_auth_header(key, headers)
    with pytest.raises(ValueError):
        crypto.create_auth_header(key, 'fixture-node')


def test_deletion_marks_snapshot_stale_until_bounded_refresh(populated_engine):
    before = populated_engine.get_stats()['total_memories']
    row = populated_engine.get_recent(1)[0]
    populated_engine.delete_memory(row['id'])
    cached = populated_engine.get_stats()
    assert cached['total_memories'] == before
    assert cached['stats_status'] == 'stale'
    assert cached['stats_reason'] == 'index_changed'
    populated_engine._stats_cached_at = time.monotonic() - 31
    assert populated_engine.get_stats()['total_memories'] == before - 1


def test_future_timestamp_nonce_retained_for_entire_signature_window(monkeypatch):
    crypto._replay_cache_clear()
    key = secrets.token_urlsafe(48)
    now = time.time()
    headers = lower(crypto.create_auth_header(key, 'fixture-node'))
    headers['x-animus-timestamp'] = str(int(now + 290))
    payload = crypto._build_payload('fixture-node', headers['x-animus-timestamp'],
                                    headers['x-animus-nonce'], '')
    headers['x-animus-signature'] = crypto.sign_message(crypto.derive_peer_key(key, 'fixture-node'), payload)
    assert crypto.verify_auth_header(key, headers)
    monkeypatch.setattr(crypto.time, 'time', lambda: now + 310)
    assert not crypto.verify_auth_header(key, headers)
    crypto._replay_cache_clear()


def test_registry_invalid_shape_is_rejected(hub_config, tmp_path):
    registry = tmp_path / 'invalid.json'
    registry.write_text('[]')
    registry.chmod(0o600)
    hub_config.server_peer_keys_file = registry
    with pytest.raises(ValueError):
        peer_secret(hub_config, 'fixture-node')


def test_health_rejects_database_missing_required_memories_table(engine):
    # Real valid SQLite with unrelated schema is not an operational Animus DB.
    engine.conn.execute("DROP TABLE memories")
    engine.conn.commit()
    with pytest.raises(sqlite3.OperationalError, match="no such table: memories"):
        engine.check_health()
