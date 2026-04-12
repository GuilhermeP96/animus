"""Peer client — connects to the Animus Hub for memory synchronization."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

import httpx
import websockets
from websockets.asyncio.client import connect as ws_connect

from ..collector.copilot import CopilotCollector
from ..collector.models import MemoryBatch
from ..config import AnimusConfig
from ..indexer.engine import IndexEngine
from .crypto import create_auth_header
from .sync import SyncProtocol

logger = logging.getLogger("animus.peer")


class AnimusPeer:
    """Peer node — collects, indexes, and syncs memories with the hub.

    The Subject in Animus terminology.
    """

    def __init__(self, config: AnimusConfig):
        self.config = config
        self.config.ensure_dirs()
        self.engine = IndexEngine(config.db_path)
        self.collector = CopilotCollector(config)
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._running = False

    async def collect_and_index(self) -> int:
        """Run a collection cycle — gather and index new memories."""
        logger.info("Collecting memories...")
        memories = self.collector.collect_all()
        new_count = self.engine.index_batch(memories)
        logger.info("Collected %d memories, %d new", len(memories), new_count)
        return new_count

    async def sync_to_hub(self) -> int:
        """Push unsynced memories to the hub."""
        if not self.config.hub_url:
            logger.debug("No hub configured, skipping sync")
            return 0

        unsynced = self.engine.get_unsynced(limit=200)
        if not unsynced:
            return 0

        # Convert dicts back to Memory objects
        from ..collector.models import Memory, MemoryType

        memories = []
        for row in unsynced:
            memories.append(Memory(
                id=row["id"],
                type=MemoryType(row["type"]),
                source_node=row["source_node"],
                source_path=row.get("source_path", ""),
                workspace=row.get("workspace", ""),
                title=row.get("title", ""),
                content=row["content"],
                metadata=json.loads(row.get("metadata", "{}")),
                tags=json.loads(row.get("tags", "[]")),
                sequence=row.get("sequence", 0),
            ))

        batch = MemoryBatch(
            node_id=self.config.node_id,
            node_name=self.config.node_name,
            memories=memories,
        )

        try:
            headers = create_auth_header(self.config.server_secret or self.config.hub_token, self.config.node_id)
            async with httpx.AsyncClient(timeout=30) as client:
                # Use HTTP POST for batch sync (simpler than WS for one-shots)
                resp = await client.post(
                    f"{self.config.hub_url.replace('wss://', 'https://').replace('ws://', 'http://')}/api/sync/push",
                    json=json.loads(SyncProtocol.push(batch)),
                    headers=headers,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    synced_ids = [m.id for m in memories]
                    self.engine.mark_synced(synced_ids)
                    logger.info("Synced %d memories to hub", len(synced_ids))
                    return len(synced_ids)
                else:
                    logger.error("Hub sync failed: HTTP %d — %s", resp.status_code, resp.text[:200])
                    return 0
        except Exception as e:
            logger.error("Hub sync error: %s", e)
            return 0

    async def pull_from_hub(self) -> int:
        """Pull new memories from the hub."""
        if not self.config.hub_url:
            return 0

        try:
            headers = create_auth_header(self.config.server_secret or self.config.hub_token, self.config.node_id)
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    f"{self.config.hub_url.replace('wss://', 'https://').replace('ws://', 'http://')}/api/sync/pull",
                    json={"node_id": self.config.node_id, "limit": 200},
                    headers=headers,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    memories, _skipped = SyncProtocol.memories_from_push(data)
                    new_count = self.engine.index_batch(memories)
                    logger.info("Pulled %d memories, %d new", len(memories), new_count)
                    return new_count
        except Exception as e:
            logger.error("Hub pull error: %s", e)
        return 0

    async def remote_search(self, query: str) -> list[dict]:
        """Search memories via the hub (across all peers)."""
        if not self.config.hub_url:
            return []

        try:
            headers = create_auth_header(self.config.server_secret or self.config.hub_token, self.config.node_id)
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    f"{self.config.hub_url.replace('wss://', 'https://').replace('ws://', 'http://')}/api/search",
                    json={"query": query, "node_id": self.config.node_id},
                    headers=headers,
                )
                if resp.status_code == 200:
                    return resp.json().get("results", [])
        except Exception as e:
            logger.error("Remote search error: %s", e)
        return []

    async def run_daemon(self) -> None:
        """Run the peer as a background daemon — collect, index, sync on interval."""
        self._running = True
        logger.info(
            "Animus peer %s (%s) starting — interval=%ds",
            self.config.node_id,
            self.config.node_name,
            self.config.collect_interval_seconds,
        )

        while self._running:
            try:
                await self.collect_and_index()
                await self.sync_to_hub()
                await self.pull_from_hub()
            except Exception as e:
                logger.error("Daemon cycle error: %s", e)

            await asyncio.sleep(self.config.collect_interval_seconds)

    def stop(self) -> None:
        self._running = False
        self.engine.close()
