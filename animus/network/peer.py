"""Peer client — connects to the Animus Hub for memory synchronization."""

from __future__ import annotations

import asyncio
import json
import logging
import platform
import socket
from typing import Optional

import httpx
import websockets
from websockets.asyncio.client import connect as ws_connect

from .. import __version__
from ..collector.antigravity import AntigravityCollector
from ..collector.claude import ClaudeCollector
from ..collector.copilot import CopilotCollector
from ..collector.copilot_cli import CopilotCliCollector
from ..collector.obsidian import ObsidianCollector
from ..collector.codex import CodexCollector
from ..collector.models import MemoryBatch
from . import updater
from ..config import AnimusConfig
from ..indexer.engine import IndexEngine
from .crypto import create_auth_header
from .sync import SyncProtocol
from .status import PeerStatus, utc_now

logger = logging.getLogger("animus.peer")

MIN_UPDATE_CHECK_SECONDS = 60
MAX_UPDATE_CHECK_SECONDS = 900


def effective_update_check_interval(configured: int) -> int:
    """Clamp update polling to a reliable 1–15 minute operational window."""
    return max(MIN_UPDATE_CHECK_SECONDS, min(MAX_UPDATE_CHECK_SECONDS, int(configured)))


class AnimusPeer:
    """Peer node — collects, indexes, and syncs memories with the hub.

    The Subject in Animus terminology.
    """

    def __init__(self, config: AnimusConfig):
        self.config = config
        self.config.ensure_dirs()
        self.engine = IndexEngine(config.db_path)
        self.collector = CopilotCollector(config)
        self.claude_collector = ClaudeCollector(config)
        self.antigravity_collector = AntigravityCollector(config)
        self.copilot_cli_collector = CopilotCliCollector(config)
        self.obsidian_collector = ObsidianCollector(config)
        self.codex_collector = CodexCollector(config)
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._running = False
        # Self-update bookkeeping: the daemon checks at most once per
        # ``config.update_check_interval_seconds`` regardless of how short
        # ``collect_interval_seconds`` is, so a 60-second collect loop
        # doesn't translate into 60-second pip storms.
        self._last_update_check_monotonic: float = 0.0
        self.status = PeerStatus(config.data_dir, config.collect_interval_seconds)

    async def collect_and_index(self) -> int:
        """Run a collection cycle — gather and index new memories."""
        logger.info("Collecting memories...")
        memories = self.collector.collect_all()
        memories.extend(self.claude_collector.collect_all())
        memories.extend(self.antigravity_collector.collect_all())
        memories.extend(self.copilot_cli_collector.collect_all())
        memories.extend(self.obsidian_collector.collect_all())
        memories.extend(self.codex_collector.collect_all())
        new_count = self.engine.index_batch(memories)
        from ..knowledge_feedback import export_new_candidates
        exported = export_new_candidates(self.config, self.engine, memories)
        if exported:
            logger.info("Exported %d candidate notes; no automatic verification", exported)
        for vault, active_ids in self.obsidian_collector.seen_by_vault.items():
            self.engine.mark_obsidian_missing(vault, self.config.node_id, active_ids)
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
            node_version=__version__,
            hostname=socket.gethostname(),
            os_name=platform.system(),
            os_version=platform.release(),
            memories=memories,
        )

        try:
            body_str = SyncProtocol.push(batch)
            secret = self.config.server_secret or self.config.hub_token
            headers = create_auth_header(secret, self.config.node_id, body=body_str)
            async with httpx.AsyncClient(timeout=30, headers=self.config.cloudflare_access_headers()) as client:
                # Use HTTP POST for batch sync (simpler than WS for one-shots)
                resp = await client.post(
                    f"{self.config.hub_url.replace('wss://', 'https://').replace('ws://', 'http://')}/api/sync/push",
                    content=body_str,
                    headers={**headers, "Content-Type": "application/json"},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    self.status.event("push_ok")
                    self.status.connection(True)
                    synced_ids = [m.id for m in memories]
                    self.engine.mark_synced(synced_ids)
                    logger.info("Synced %d memories to hub", len(synced_ids))
                    return len(synced_ids)
                else:
                    self.status.connection(False)
                    logger.error("Hub sync failed: HTTP %d — %s", resp.status_code, resp.text[:200])
                    return 0
        except Exception as e:
            self.status.connection(False)
            logger.error("Hub sync error: %s", e)
            return 0

    async def pull_from_hub(self) -> int:
        """Pull new memories from the hub."""
        if not self.config.hub_url:
            return 0

        try:
            body_str = json.dumps({
                "node_id": self.config.node_id,
                "node_name": self.config.node_name,
                "node_version": __version__,
                "hostname": socket.gethostname(),
                "os_name": platform.system(),
                "os_version": platform.release(),
                "limit": 200,
            })
            secret = self.config.server_secret or self.config.hub_token
            headers = create_auth_header(secret, self.config.node_id, body=body_str)
            async with httpx.AsyncClient(timeout=30, headers=self.config.cloudflare_access_headers()) as client:
                resp = await client.post(
                    f"{self.config.hub_url.replace('wss://', 'https://').replace('ws://', 'http://')}/api/sync/pull",
                    content=body_str,
                    headers={**headers, "Content-Type": "application/json"},
                )
                if resp.status_code == 200:
                    self.status.connection(True)
                    self.status.event("pull_ok")
                    data = resp.json()
                    memories, _skipped = SyncProtocol.memories_from_push(data)
                    new_count = self.engine.index_batch(memories)
                    logger.info("Pulled %d memories, %d new", len(memories), new_count)
                    return new_count
                self.status.connection(False)
        except Exception as e:
            self.status.connection(False)
            logger.error("Hub pull error: %s", e)
        return 0

    async def remote_search(self, query: str, *, workspace: str = '', mem_type: str = '', limit: int = 20, strict: bool = False) -> list[dict]:
        """Search memories via the hub (across all peers)."""
        if not self.config.hub_url:
            return []

        try:
            body_str = json.dumps({"query": query, "node_id": self.config.node_id,
                                   "workspace": workspace or None, "mem_type": mem_type or None,
                                   "limit": max(1, min(int(limit), 20))})
            secret = self.config.server_secret or self.config.hub_token
            headers = create_auth_header(secret, self.config.node_id, body=body_str)
            async with httpx.AsyncClient(timeout=15, headers=self.config.cloudflare_access_headers()) as client:
                resp = await client.post(
                    f"{self.config.hub_url.replace('wss://', 'https://').replace('ws://', 'http://')}/api/search",
                    content=body_str,
                    headers={**headers, "Content-Type": "application/json"},
                )
                if resp.status_code == 200:
                    return resp.json().get("results", [])
                if strict:
                    raise RuntimeError('Authenticated hub search unavailable')
        except Exception as e:
            if strict:
                raise RuntimeError('Authenticated hub search unavailable') from None
            logger.error("Remote search error: %s", e)
        return []

    async def _maybe_self_update(self) -> None:
        """Check the hub for a new release; re-exec if there is one.

        Runs at most once per ``update_check_interval_seconds`` (monotonic
        clock so a wall-clock jump doesn't trigger a check storm). All work
        happens off the event loop via ``asyncio.to_thread`` because pip
        is decidedly blocking.
        """
        if not self.config.auto_update_enabled:
            return
        import time as _time
        now = _time.monotonic()
        interval = effective_update_check_interval(
            self.config.update_check_interval_seconds
        )
        if now - self._last_update_check_monotonic < interval:
            return
        self._last_update_check_monotonic = now

        try:
            restart_required, info = await asyncio.to_thread(
                updater.check_and_apply, self.config
            )
        except Exception as exc:
            logger.warning("Self-update check failed: %s", exc)
            return
        if info is not None:
            logger.info(
                "Self-update check: current=v%s latest=v%s restart=%s",
                __version__, info.latest, restart_required,
            )
        if restart_required and info is not None:
            logger.info(
                "Self-update %s v%s (was %s) — initiating qualified restart",
                "staged" if updater.update_is_deferred() else "installed", info.latest, __version__,
            )
            # ``restart_in_place`` does not return on success.
            updater.restart_in_place()

    async def run_daemon(self) -> None:
        """Run the peer as a background daemon — collect, index, sync on interval."""
        self._running = True
        logger.info(
            "Animus peer %s (%s) v%s starting — interval=%ds "
            "(auto-update=%s, update-check=%ds)",
            self.config.node_id,
            self.config.node_name,
            __version__,
            self.config.collect_interval_seconds,
            self.config.auto_update_enabled,
            effective_update_check_interval(
                self.config.update_check_interval_seconds
            ),
        )

        # Check for updates immediately on startup — picks up releases that
        # happened while the host was off, before we even sync.
        self.status.start()
        try:
            await self._maybe_self_update()
            while self._running:
                try:
                    self.status.update(phase="collecting")
                    self.status.event("collect")
                    await self.collect_and_index()
                    self.status.update(phase="syncing")
                    await self.sync_to_hub()
                    await self.pull_from_hub()
                    stats = self.engine.stats_view()
                    self.status.update(phase="idle", last_cycle=utc_now(),
                                       total_memories=stats.get("total_memories"),
                                       unsynced=stats.get("unsynced"),
                                       workspaces=stats.get("unique_workspaces"),
                                       stats_status=stats.get("stats_status", "unavailable"))
                    self.status.event("cycle_complete")
                    await self._maybe_self_update()
                except Exception as e:
                    self.status.update(phase="idle", connected=False, connection_status="disconnected")
                    self.status.event("cycle_error")
                    logger.error("Daemon cycle error: %s", e)
                # A local click can request the next normal cycle. No credentials,
                # collection policy or remote endpoint are supplied by this IPC.
                for _ in range(max(1, self.config.collect_interval_seconds)):
                    if not self._running or self.status.sync_requested():
                        break
                    await asyncio.sleep(1)
        finally:
            self.status.stop()

    def stop(self) -> None:
        self._running = False
        self.engine.close()
