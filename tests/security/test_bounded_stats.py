"""Real SQLite contention/interruption fixtures; no production DB or model."""
import sqlite3
import time

import pytest
from fastapi.testclient import TestClient

import animus.indexer.engine as index_module
from animus.indexer.engine import IndexEngine, StatsUnavailable
import animus.server.app as server
from animus.server.admin_auth import require_admin, AdminSession


def interrupt(monkeypatch):
    # Run actual SQLite VM with an already-expired budget, not a mocked error.
    monkeypatch.setattr(index_module, '_STATS_QUERY_TIMEOUT_SECONDS', 0)
    monkeypatch.setattr(index_module, '_PROGRESS_HANDLER_INTERVAL', 1)


def test_cold_interrupt_is_typed_and_backed_off(populated_engine, monkeypatch):
    interrupt(monkeypatch)
    with pytest.raises(StatsUnavailable) as failure:
        populated_engine.get_stats()
    assert failure.value.reason == 'query_timeout'
    assert failure.value.payload()['total_memories'] is None
    # Still fails cold, with no false empty result, after VM budget restored.
    monkeypatch.setattr(index_module, '_STATS_QUERY_TIMEOUT_SECONDS', 2)
    with pytest.raises(StatsUnavailable):
        populated_engine.get_stats()
    populated_engine._stats_retry_at = 0
    assert populated_engine.get_stats()['total_memories'] == 7


def test_stale_interrupt_retains_count_age_and_degradation(populated_engine, monkeypatch):
    original = populated_engine.get_stats()
    populated_engine._stats_cached_at -= 31
    interrupt(monkeypatch)
    stale = populated_engine.get_stats()
    assert stale['total_memories'] == original['total_memories'] == 7
    assert stale['stats_collected_at'] == original['stats_collected_at']
    assert stale['stats_age_seconds'] >= 31
    assert stale['stats_status'] == 'stale'
    assert stale['stats_degraded'] is True
    assert stale['stats_reason'] == 'query_timeout'
    assert stale['stats_retry_after_seconds'] == 30
    stale['by_type'].clear()
    assert populated_engine.cached_stats()['by_type']
    # Failed counting progress handler cannot leak onto independent health read.
    start = time.monotonic()
    populated_engine.check_health()
    assert time.monotonic() - start < .5


def test_writer_transaction_does_not_block_read_snapshot(populated_engine):
    writer = sqlite3.connect(str(populated_engine.db_path), timeout=.25)
    try:
        writer.execute('BEGIN IMMEDIATE')
        writer.execute("UPDATE memories SET synced=1")
        with populated_engine._lock:
            start = time.monotonic()
            stats = populated_engine.get_stats()
            populated_engine.check_health()
            assert time.monotonic() - start < .5
        # WAL snapshot correctly excludes the uncommitted update.
        assert stats['total_memories'] == 7
        assert stats['unsynced'] == 7
        writer.commit()
        populated_engine._stats_cached_at -= 31
        assert populated_engine.get_stats()['unsynced'] == 0
    finally:
        writer.close()


def test_actual_exclusive_lock_is_bounded_and_safe(populated_engine):
    path = populated_engine.db_path
    populated_engine.close()
    locker = sqlite3.connect(str(path))
    locker.execute('PRAGMA journal_mode=DELETE')
    locker.execute('BEGIN EXCLUSIVE')
    try:
        start = time.monotonic()
        with pytest.raises(StatsUnavailable) as failure:
            populated_engine.get_stats()
        assert time.monotonic() - start < 1
        assert failure.value.reason == 'database_busy'
        assert failure.value.payload()['total_memories'] is None
    finally:
        locker.rollback()
        locker.close()


def test_single_flight_never_waits_for_refresh_lock(populated_engine):
    with populated_engine._stats_lock:
        with pytest.raises(StatsUnavailable) as failure:
            populated_engine.get_stats()
        assert failure.value.reason == 'refresh_busy'
    populated_engine.get_stats()
    populated_engine._stats_cached_at -= 31
    with populated_engine._stats_lock:
        result = populated_engine.get_stats()
    assert result['stats_status'] == 'stale'
    assert result['stats_reason'] == 'refresh_busy'
    assert result['total_memories'] == 7


def test_missing_or_wrong_schema_never_becomes_zero(tmp_path):
    path = tmp_path / 'wrong.sqlite3'
    with sqlite3.connect(path) as connection:
        connection.execute('CREATE TABLE wrong (value TEXT)')
    engine = IndexEngine(path)
    with pytest.raises(StatsUnavailable) as failure:
        engine.get_stats()
    assert failure.value.reason == 'database_unavailable'
    assert engine.stats_view()['total_memories'] is None
    assert engine._conn is None  # No writable migration on stats path.


def test_covering_plans_never_scan_content(populated_engine):
    queries = [
        'SELECT COUNT(*) FROM memories INDEXED BY idx_memories_synced',
        'SELECT COUNT(DISTINCT source_node) FROM memories INDEXED BY idx_memories_node',
        'SELECT COUNT(DISTINCT workspace) FROM memories INDEXED BY idx_memories_workspace',
        'SELECT COUNT(*) FROM memories INDEXED BY idx_memories_synced WHERE synced=0',
        'SELECT type, COUNT(*) FROM memories INDEXED BY idx_memories_type GROUP BY type',
    ]
    with sqlite3.connect(populated_engine.db_path) as connection:
        for query in queries:
            plan = ' '.join(row[3] for row in connection.execute('EXPLAIN QUERY PLAN ' + query))
            assert 'COVERING INDEX' in plan
            assert 'TEMP B-TREE' not in plan


def test_http_cold_failure_json_pages_and_health(hub_config, populated_engine, monkeypatch):
    old = (server._engine, server._config, server._connected_peers)
    server._engine, server._config, server._connected_peers = populated_engine, hub_config, {}
    hub_config.server_secret = ''
    hub_config.allow_insecure_dev_auth = True
    hub_config.server_host = '127.0.0.1'
    server.app.dependency_overrides[require_admin] = lambda: AdminSession(user='fixture', exp=int(time.time())+3600, iat=int(time.time()))
    interrupt(monkeypatch)
    try:
        # ASGI error responses remain handled on one client; TCP keepalive is a rollout gate.
        client = TestClient(server.app)  # Do not run production lifespan/tasks.
        for url in ('/admin/api/stats', '/api/stats'):
            response = client.get(url, headers={'X-Animus-Node': 'fixture'})
            assert response.status_code == 503
            assert response.headers['Retry-After'] == '30'
            assert response.json()['stats_reason'] == 'query_timeout'
            assert response.json()['total_memories'] is None
            assert 'SELECT' not in response.text and 'sqlite3' not in response.text
        page = client.get('/admin')
        assert page.status_code == 200
        assert 'Statistics temporarily unavailable' in page.text
        assert 'Unavailable' in page.text
        health = client.get('/health')
        assert health.status_code == 200
        assert health.json()['memories'] is None
        assert health.json()['stats_status'] == 'unavailable'
        assert client.get('/health/live').json() == {'status': 'alive'}
    finally:
        client.close()
        server.app.dependency_overrides.pop(require_admin, None)
        server._engine, server._config, server._connected_peers = old


def test_http_stale_snapshot_is_explicit_not_healthy_fresh(hub_config, populated_engine, monkeypatch):
    old = (server._engine, server._config, server._connected_peers)
    original = populated_engine.get_stats()
    populated_engine._stats_cached_at -= 31
    server._engine, server._config, server._connected_peers = populated_engine, hub_config, {}
    server.app.dependency_overrides[require_admin] = lambda: AdminSession(user='fixture', exp=int(time.time())+3600, iat=int(time.time()))
    interrupt(monkeypatch)
    client = TestClient(server.app)
    try:
        response = client.get('/admin/api/stats')
        assert response.status_code == 200
        assert response.json()['stats_status'] == 'stale'
        assert response.json()['stats_degraded'] is True
        assert response.json()['total_memories'] == original['total_memories']
        assert response.json()['stats_age_seconds'] >= 31
        page = client.get('/admin')
        assert page.status_code == 200
        assert 'Statistics are from a previous snapshot' in page.text
        health = client.get('/health').json()
        assert health['status'] == 'healthy'  # Actual cheap DB read succeeded.
        assert health['stats_status'] == 'stale'
        assert health['stats_degraded'] is True
    finally:
        client.close()
        server.app.dependency_overrides.pop(require_admin, None)
        server._engine, server._config, server._connected_peers = old


def test_all_counts_share_one_snapshot_during_commit(populated_engine, monkeypatch):
    # Hook a real SQLite trace to commit a separate WAL writer between aggregates.
    # Without BEGIN the final unsynced count would mix snapshots (7 -> 0).
    connect = sqlite3.connect
    writer = connect(str(populated_engine.db_path))
    committed = []

    def traced_connect(*args, **kwargs):
        connection = connect(*args, **kwargs)
        if kwargs.get('uri'):
            def trace(statement):
                if 'COUNT(DISTINCT source_node)' in statement and not committed:
                    writer.execute('UPDATE memories SET synced=1')
                    writer.commit()
                    committed.append(True)
            connection.set_trace_callback(trace)
        return connection

    monkeypatch.setattr(index_module.sqlite3, 'connect', traced_connect)
    try:
        result = populated_engine.get_stats()
        assert committed == [True]
        assert result['unsynced'] == 7
        populated_engine._stats_cached_at -= 31
        assert populated_engine.get_stats()['unsynced'] == 0
    finally:
        writer.close()


def test_published_snapshot_keeps_generation_bound_to_its_counts(populated_engine):
    before = populated_engine.get_stats()
    captured = populated_engine._stats_cache
    assert '_index_generation' not in before
    assert '_cached_monotonic' not in before
    row = populated_engine.get_recent(1)[0]
    populated_engine.delete_memory(row['id'])
    # The snapshot's generation cannot be reset by a parallel refresh flag.
    assert captured['_index_generation'] != populated_engine._stats_generation
    assert populated_engine._stats_cache is captured
    assert populated_engine.cached_stats()['stats_reason'] == 'index_changed'
    populated_engine._stats_cached_at -= 31
    assert populated_engine.get_stats()['total_memories'] == before['total_memories'] - 1
    assert populated_engine.cached_stats()['stats_status'] == 'fresh'
