"""Detailed statistics must not stall liveness or bounded health checks."""
import asyncio
import time

import pytest
from animus.server import app as server


@pytest.mark.asyncio
async def test_slow_statistics_do_not_block_liveness_or_cached_health(monkeypatch):
    class Engine:
        def get_stats(self):
            time.sleep(0.2)
            return {"total_memories": 42, "unique_nodes": 3}

        def check_health(self):
            return True

        def cached_stats(self):
            return {"total_memories": 42, "unique_nodes": 3,
                    "stats_age_seconds": 0, "stats_status": "ready",
                    "stats_degraded": False}

    monkeypatch.setattr(server, "get_engine", lambda: Engine())
    monkeypatch.setattr(server, "_connected_peers", {})
    diagnostic = asyncio.create_task(server.stats(node_id="synthetic-node"))
    await asyncio.sleep(0.02)
    assert not diagnostic.done()
    started = time.monotonic()
    assert server.liveness() == {"status": "alive"}
    health = server.health()
    assert time.monotonic() - started < 0.1
    assert health["status"] == "healthy" and health["memories"] == 42
    assert await diagnostic == {"total_memories": 42, "unique_nodes": 3}
