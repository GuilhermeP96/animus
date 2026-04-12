"""FastAPI server — the Abstergo Hub."""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from ..collector.models import Memory, MemoryType
from ..config import AnimusConfig
from ..indexer.engine import IndexEngine
from ..network.crypto import verify_auth_header
from ..network.sync import SyncProtocol

logger = logging.getLogger("animus.server")

# ── Globals ──
_config: AnimusConfig | None = None
_engine: IndexEngine | None = None
_connected_peers: dict[str, dict] = {}  # node_id -> info


def get_config() -> AnimusConfig:
    assert _config is not None
    return _config


def get_engine() -> IndexEngine:
    assert _engine is not None
    return _engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _config, _engine
    _config = AnimusConfig.load()
    _config.node_role = "hub"
    _config.ensure_dirs()
    _engine = IndexEngine(_config.db_path)
    logger.info("Animus Hub started — node=%s", _config.node_id)
    yield
    if _engine:
        _engine.close()
    logger.info("Animus Hub stopped")


app = FastAPI(
    title="Animus Hub",
    description="Central memory synchronization server — Abstergo",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Auth Dependency ──

async def verify_peer(request: Request) -> str:
    """Verify peer authentication. Returns node_id."""
    config = get_config()
    if not config.server_secret:
        # No auth configured — accept all (dev mode)
        return request.headers.get("x-animus-node", "anonymous")

    if not verify_auth_header(config.server_secret, dict(request.headers)):
        raise HTTPException(status_code=401, detail="Invalid authentication")
    return request.headers["x-animus-node"]


# ── Request/Response Models ──

class PushRequest(BaseModel):
    type: str = "PUSH"
    node_id: str
    node_name: str = ""
    count: int = 0
    memories: list[dict[str, Any]]
    timestamp: str = ""


class PullRequest(BaseModel):
    node_id: str
    since: str | None = None
    limit: int = 100


class SearchRequest(BaseModel):
    query: str
    node_id: str = ""
    mem_type: str | None = None
    workspace: str | None = None
    limit: int = 20


# ── API Routes ──

@app.get("/")
async def root():
    return {
        "name": "Animus Hub",
        "version": "0.1.0",
        "status": "operational",
        "codename": "Abstergo",
    }


@app.get("/health")
async def health():
    engine = get_engine()
    stats = engine.get_stats()
    return {
        "status": "healthy",
        "memories": stats["total_memories"],
        "nodes": stats["unique_nodes"],
        "peers_online": len(_connected_peers),
    }


@app.get("/api/stats")
async def stats(node_id: str = Depends(verify_peer)):
    engine = get_engine()
    return engine.get_stats()


@app.post("/api/sync/push")
async def sync_push(req: PushRequest, node_id: str = Depends(verify_peer)):
    """Receive memories from a peer."""
    engine = get_engine()
    data = req.model_dump()
    memories = SyncProtocol.memories_from_push(data)
    new_count = engine.index_batch(memories)

    logger.info(
        "PUSH from %s (%s): %d memories, %d new",
        req.node_id, req.node_name, len(memories), new_count,
    )

    return {
        "status": "ok",
        "received": len(memories),
        "new": new_count,
        "total": engine.get_stats()["total_memories"],
    }


@app.post("/api/sync/pull")
async def sync_pull(req: PullRequest, node_id: str = Depends(verify_peer)):
    """Send memories to a peer (memories from OTHER nodes)."""
    engine = get_engine()

    # Get memories not from the requesting node
    query = "SELECT * FROM memories WHERE source_node != ? ORDER BY timestamp DESC LIMIT ?"
    params = [req.node_id, req.limit]

    if req.since:
        query = "SELECT * FROM memories WHERE source_node != ? AND timestamp > ? ORDER BY timestamp DESC LIMIT ?"
        params = [req.node_id, req.since, req.limit]

    rows = engine.conn.execute(query, params).fetchall()
    memories_data = [dict(r) for r in rows]

    return {
        "type": "PULL_RESPONSE",
        "count": len(memories_data),
        "memories": memories_data,
    }


@app.post("/api/search")
async def search_memories(req: SearchRequest, node_id: str = Depends(verify_peer)):
    """Search across all indexed memories — Eagle Vision."""
    engine = get_engine()
    results = engine.search(
        req.query,
        mem_type=req.mem_type,
        workspace=req.workspace,
        limit=req.limit,
    )
    return {
        "query": req.query,
        "count": len(results),
        "results": results,
    }


@app.get("/api/memories/recent")
async def recent_memories(limit: int = 20, node_id: str = Depends(verify_peer)):
    engine = get_engine()
    return {"memories": engine.get_recent(limit)}


@app.get("/api/peers")
async def list_peers(node_id: str = Depends(verify_peer)):
    return {"peers": list(_connected_peers.values())}


# ── WebSocket for realtime sync ──

@app.websocket("/ws/sync")
async def websocket_sync(ws: WebSocket):
    """WebSocket endpoint for realtime peer synchronization."""
    await ws.accept()
    peer_node_id = None

    try:
        # Wait for handshake
        raw = await ws.receive_text()
        msg = SyncProtocol.parse(raw)

        if msg["type"] != "HANDSHAKE":
            await ws.close(code=4001, reason="Expected HANDSHAKE")
            return

        peer_node_id = msg["node_id"]
        config = get_config()

        # Verify auth if configured
        if config.server_secret:
            # For WS, verify via token in handshake
            pass  # TODO: Add WS auth

        _connected_peers[peer_node_id] = {
            "node_id": peer_node_id,
            "node_name": msg.get("node_name", ""),
            "capabilities": msg.get("capabilities", []),
            "connected_at": datetime.now(timezone.utc).isoformat(),
        }
        logger.info("Peer connected: %s (%s)", peer_node_id, msg.get("node_name"))

        await ws.send_text(SyncProtocol.ack("HANDSHAKE", 1))

        # Message loop
        engine = get_engine()
        while True:
            raw = await ws.receive_text()
            msg = SyncProtocol.parse(raw)

            if msg["type"] == "PUSH":
                memories = SyncProtocol.memories_from_push(msg)
                new_count = engine.index_batch(memories)
                await ws.send_text(SyncProtocol.ack("PUSH", new_count, [m.id for m in memories]))

            elif msg["type"] == "PULL":
                rows = engine.conn.execute(
                    "SELECT * FROM memories WHERE source_node != ? ORDER BY timestamp DESC LIMIT ?",
                    (peer_node_id, msg.get("limit", 100)),
                ).fetchall()
                await ws.send_text(SyncProtocol.result([dict(r) for r in rows]))

            elif msg["type"] == "QUERY":
                results = engine.search(msg["query"])
                await ws.send_text(SyncProtocol.result(results, msg["query"]))

            elif msg["type"] == "HEARTBEAT":
                _connected_peers[peer_node_id]["last_heartbeat"] = datetime.now(timezone.utc).isoformat()

    except WebSocketDisconnect:
        logger.info("Peer disconnected: %s", peer_node_id)
    except Exception as e:
        logger.error("WebSocket error: %s", e)
    finally:
        if peer_node_id and peer_node_id in _connected_peers:
            del _connected_peers[peer_node_id]


def create_app(config: AnimusConfig | None = None) -> FastAPI:
    """Create the FastAPI app (for programmatic use)."""
    global _config, _engine
    if config:
        _config = config
        _config.ensure_dirs()
        _engine = IndexEngine(_config.db_path)
    return app
