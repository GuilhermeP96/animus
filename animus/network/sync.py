"""Sync protocol — memory synchronization between peers and hub."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from ..collector.models import Memory, MemoryBatch, MemoryType

logger = logging.getLogger("animus.sync")


class SyncProtocol:
    """Protocol messages for Animus synchronization.

    Wire format: JSON over WebSocket.
    Message types:
      - HANDSHAKE: Initial peer identification
      - PUSH: Send memories to hub
      - PULL: Request memories from hub
      - ACK: Acknowledge receipt
      - QUERY: Remote search query
      - RESULT: Search results
      - HEARTBEAT: Keep-alive
    """

    @staticmethod
    def handshake(node_id: str, node_name: str, capabilities: list[str] | None = None) -> str:
        return json.dumps({
            "type": "HANDSHAKE",
            "node_id": node_id,
            "node_name": node_name,
            "capabilities": capabilities or ["push", "pull", "query"],
            "version": "0.1.0",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    @staticmethod
    def push(batch: MemoryBatch) -> str:
        return json.dumps({
            "type": "PUSH",
            "node_id": batch.node_id,
            "node_name": batch.node_name,
            "count": len(batch.memories),
            "memories": [m.model_dump(mode="json") for m in batch.memories],
            "timestamp": batch.batch_timestamp.isoformat(),
        })

    @staticmethod
    def pull(node_id: str, since: str | None = None, limit: int = 100) -> str:
        return json.dumps({
            "type": "PULL",
            "node_id": node_id,
            "since": since,
            "limit": limit,
        })

    @staticmethod
    def ack(message_type: str, count: int, memory_ids: list[str] | None = None) -> str:
        return json.dumps({
            "type": "ACK",
            "ack_for": message_type,
            "count": count,
            "memory_ids": memory_ids or [],
        })

    @staticmethod
    def query(node_id: str, search_query: str, filters: dict | None = None) -> str:
        return json.dumps({
            "type": "QUERY",
            "node_id": node_id,
            "query": search_query,
            "filters": filters or {},
        })

    @staticmethod
    def result(results: list[dict], query_ref: str = "") -> str:
        return json.dumps({
            "type": "RESULT",
            "query": query_ref,
            "count": len(results),
            "results": results,
        })

    @staticmethod
    def heartbeat(node_id: str, stats: dict | None = None) -> str:
        return json.dumps({
            "type": "HEARTBEAT",
            "node_id": node_id,
            "stats": stats or {},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    @staticmethod
    def parse(raw: str) -> dict[str, Any]:
        """Parse an incoming sync message."""
        try:
            data = json.loads(raw)
            if not isinstance(data, dict) or "type" not in data:
                raise ValueError("Invalid message format")
            return data
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON: {e}") from e

    @staticmethod
    def memories_from_push(data: dict) -> list[Memory]:
        """Reconstruct Memory objects from a PUSH message."""
        memories = []
        for raw in data.get("memories", []):
            try:
                raw["type"] = MemoryType(raw["type"])
                memories.append(Memory(**raw))
            except (ValueError, KeyError) as e:
                logger.warning("Skipping malformed memory: %s", e)
        return memories
