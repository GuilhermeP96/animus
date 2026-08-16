"""FastAPI server — the central Animus Hub."""

from __future__ import annotations

import json
import logging
import re
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
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
_connected_peers: dict[str, dict] = {}  # node_id -> presence info

# A peer counts as "online" when seen (WS message or HTTP sync) within this
# window. 3× the default 300s collect interval, so one missed cycle doesn't
# flap the Brotherhood page.
_PEER_ONLINE_TTL_SECONDS = 900


def _note_peer_activity(node_id: str, node_name: str = "", transport: str = "http") -> None:
    """Upsert a presence entry for a peer.

    Most peers sync over plain HTTP (``/api/sync/push|pull``) and never open
    the WebSocket — without this, ``_connected_peers`` only ever reflected WS
    clients and the Brotherhood page stayed empty.
    """
    if not node_id:
        return
    now = datetime.now(timezone.utc).isoformat()
    info = _connected_peers.get(node_id)
    if info is None:
        info = {
            "node_id": node_id,
            "node_name": node_name,
            "capabilities": [],
            "connected_at": now,
        }
        _connected_peers[node_id] = info
    if node_name:
        info["node_name"] = node_name
    info["last_seen"] = now
    info["transport"] = transport


def _peer_is_online(info: dict) -> bool:
    last = info.get("last_seen") or info.get("connected_at")
    if not last:
        return False
    try:
        dt = datetime.fromisoformat(last)
    except (ValueError, TypeError):
        return False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - dt).total_seconds() < _PEER_ONLINE_TTL_SECONDS


def _peers_with_status() -> list[dict]:
    return [
        {**info, "online": _peer_is_online(info)}
        for info in _connected_peers.values()
    ]

# ── Rate limiter (in-memory) ──
_RATE_LIMIT_REQUESTS = 60  # max requests
_RATE_LIMIT_WINDOW = 60    # per window (seconds)
_rate_buckets: dict[str, list[float]] = defaultdict(list)


def get_config() -> AnimusConfig:
    assert _config is not None
    return _config


def get_engine() -> IndexEngine:
    assert _engine is not None
    return _engine


def _migrate_unwrap_transcript_envelopes(engine: IndexEngine) -> None:
    """Repair transcript memories collected before v0.4.8.

    The pre-0.4.8 Copilot collector probed ``data.get("content")`` at the
    top level of each JSONL line, but VS Code's transcript format wraps
    the message inside ``{"type": ..., "data": {"content": ...}}``. The
    probe missed every record and fell back to writing the *raw* JSON
    line into the memory body — which is what produced the unreadable
    backslash-soup in the admin UI.

    This migration walks any row whose ``content`` looks like a JSON
    envelope (starts with ``{"type"``) and replaces it with the unwrapped
    message text, when present.
    """
    with engine._lock:
        rows = engine.conn.execute(
            "SELECT id, content FROM memories "
            "WHERE type = 'copilot_chat' AND content LIKE '{\"type\"%' "
            "LIMIT 200000"
        ).fetchall()
        repaired = 0
        truncated_recovered = 0
        # Regex used to recover `"content": "<value>"` from truncated rows
        # where json.loads fails. It only matches the *first* content key,
        # which on assistant/user message envelopes is the human-readable
        # body — exactly what the UI should render.
        content_re = re.compile(r'"content"\s*:\s*"((?:[^"\\]|\\.)*)"', re.DOTALL)
        for row in rows:
            mem_id = row["id"]
            raw = row["content"] or ""
            text: str | None = None
            try:
                data = json.loads(raw)
            except (TypeError, ValueError):
                # Truncated JSON (the pre-0.4.9 collector capped lines at 50KB).
                # Best-effort recover the first `content` field via regex.
                match = content_re.search(raw)
                if match:
                    try:
                        text = json.loads('"' + match.group(1) + '"')
                        truncated_recovered += 1
                    except ValueError:
                        text = None
                if not text:
                    # Even more aggressive: the closing quote was cut off.
                    # Grab everything after the first `"content":"`, drop a
                    # trailing partial escape, and decode.
                    open_re = re.search(r'"content"\s*:\s*"', raw)
                    if open_re:
                        tail = raw[open_re.end():]
                        # Strip a dangling backslash that would break decoding.
                        if tail.endswith("\\"):
                            tail = tail[:-1]
                        try:
                            text = json.loads('"' + tail + '"')
                            truncated_recovered += 1
                        except ValueError:
                            # Last resort: manual unescape, accept some loss.
                            text = (
                                tail.replace("\\r\\n", "\n")
                                .replace("\\n", "\n")
                                .replace("\\t", "\t")
                                .replace('\\"', '"')
                                .replace("\\\\", "\\")
                            )
                            truncated_recovered += 1
                if not text:
                    continue
            else:
                payload = data.get("data") if isinstance(data.get("data"), dict) else data
                text = (
                    payload.get("content")
                    or payload.get("text")
                    or payload.get("message")
                    or data.get("content")
                    or data.get("text")
                    or data.get("message")
                    or ""
                )
                if isinstance(text, list):
                    text = "\n".join(
                        p.get("text", "") if isinstance(p, dict) else str(p) for p in text
                    ).strip()
            if not isinstance(text, str) or not text.strip():
                continue
            engine.conn.execute(
                "UPDATE memories SET content = ? WHERE id = ?",
                (text, mem_id),
            )
            repaired += 1
        engine.conn.commit()
    if repaired:
        logger.info(
            "Hub migration: unwrapped %d transcript-envelope memories "
            "(%d via truncated-JSON recovery)",
            repaired, truncated_recovered,
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _config, _engine
    _config = AnimusConfig.load()
    _config.node_role = "hub"
    _config.ensure_dirs()
    _engine = IndexEngine(_config.db_path)
    # Hub-side migration: any memory already in the DB is, by definition,
    # synced (the hub is the destination). Without this backfill the admin
    # UI shows every imported memory as "Pending" forever.
    try:
        with _engine._lock:
            updated = _engine.conn.execute(
                "UPDATE memories SET synced = 1 WHERE synced = 0"
            ).rowcount
            _engine.conn.commit()
        if updated:
            logger.info("Hub migration: marked %d backlog memories as synced", updated)
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning("Hub synced-flag backfill failed: %s", exc)
    # Hub-side migration: repair Copilot transcript memories that were
    # collected before v0.4.8, where the collector stored the raw JSONL
    # line (heavily escaped) instead of the actual message body.
    try:
        _migrate_unwrap_transcript_envelopes(_engine)
    except Exception as exc:  # pragma: no cover
        logger.warning("Transcript-envelope unwrap migration failed: %s", exc)
    logger.info("Animus Hub started — node=%s", _config.node_id)
    yield
    if _engine:
        _engine.close()
    logger.info("Animus Hub stopped")


app = FastAPI(
    title="Animus Hub",
    description="Central memory synchronization server — Animus Hub",
    version="0.1.0",
    lifespan=lifespan,
)

def _get_cors_origins() -> list[str]:
    import os
    origins = os.environ.get("ANIMUS_CORS_ORIGINS", "")
    if origins:
        return [o.strip() for o in origins.split(",") if o.strip()]
    return ["*"]


app.add_middleware(
    CORSMiddleware,
    allow_origins=_get_cors_origins(),
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Admin Panel ──
from .admin_routes import router as admin_router  # noqa: E402

app.include_router(admin_router)


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    """Simple sliding-window rate limiter per client IP."""
    client_ip = request.client.host if request.client else "unknown"
    now = time.monotonic()
    bucket = _rate_buckets[client_ip]
    # Prune expired entries
    cutoff = now - _RATE_LIMIT_WINDOW
    _rate_buckets[client_ip] = bucket = [t for t in bucket if t > cutoff]
    if len(bucket) >= _RATE_LIMIT_REQUESTS:
        return JSONResponse(status_code=429, content={"detail": "Too many requests"})
    bucket.append(now)
    return await call_next(request)


# ── Auth Dependency ──

async def verify_peer(request: Request) -> str:
    """Verify peer authentication. Returns node_id."""
    config = get_config()
    if not config.server_secret:
        # No auth configured — accept all (dev mode)
        return request.headers.get("x-animus-node", "anonymous")

    # Read body up front so we can include its hash in the signed
    # payload. FastAPI caches the result on the Request object, so
    # the downstream pydantic dependency still sees the same bytes.
    body = await request.body() if request.method in ("POST", "PUT", "PATCH") else b""

    if not verify_auth_header(config.server_secret, dict(request.headers), body=body):
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
    include_self: bool = False  # If True, also return memories from the requesting node


class SearchRequest(BaseModel):
    query: str
    node_id: str = ""
    mem_type: str | None = None
    workspace: str | None = None
    limit: int = 20


# ── API Routes ──

@app.get("/")
async def root():
    from .. import __version__
    return {
        "name": "Animus Hub",
        "version": __version__,
        "status": "operational",
        "codename": "Animus Hub",
    }


@app.get("/api/version")
async def api_version():
    """Latest version peers should auto-update to.

    Unauthenticated on purpose — the only thing it discloses is the version
    string the hub is already serving from ``/`` and ``/docs``. Peers poll
    this endpoint periodically; see :mod:`animus.network.updater`.

    The pin can be overridden by env so the hub op can park peers on an
    older release (``ANIMUS_PIN_VERSION=0.4.15``) or stage a roll-out
    (``ANIMUS_PIN_GIT_REF=v0.5.0-rc.1``) without rebuilding the image.
    """
    import os
    from .. import __version__

    latest = os.environ.get("ANIMUS_PIN_VERSION", __version__)
    return {
        "latest": latest,
        "min_compat": os.environ.get("ANIMUS_MIN_COMPAT", ""),
        "channel": os.environ.get("ANIMUS_CHANNEL", "stable"),
        "install_url": os.environ.get(
            "ANIMUS_INSTALL_URL",
            "git+https://github.com/GuilhermeP96/animus.git",
        ),
        "git_ref": os.environ.get("ANIMUS_GIT_REF", "main"),
        "notes": os.environ.get("ANIMUS_RELEASE_NOTES", ""),
    }


@app.get("/health")
async def health():
    engine = get_engine()
    stats = engine.get_stats()
    return {
        "status": "healthy",
        "memories": stats["total_memories"],
        "nodes": stats["unique_nodes"],
        "peers_online": sum(1 for p in _connected_peers.values() if _peer_is_online(p)),
    }


@app.get("/api/stats")
async def stats(node_id: str = Depends(verify_peer)):
    engine = get_engine()
    return engine.get_stats()


@app.post("/api/sync/push")
async def sync_push(req: PushRequest, node_id: str = Depends(verify_peer)):
    """Receive memories from a peer."""
    engine = get_engine()
    _note_peer_activity(req.node_id, req.node_name, transport="http")
    data = req.model_dump()
    memories, skipped = SyncProtocol.memories_from_push(data)
    # Hub is the destination — there is nowhere to push these onward,
    # so mark them synced on ingest to avoid a misleading "Pending" UI.
    new_count = engine.index_batch(memories, synced=True)

    logger.info(
        "PUSH from %s (%s): %d memories, %d new, %d skipped",
        req.node_id, req.node_name, len(memories), new_count, skipped,
    )

    return {
        "status": "ok",
        "received": len(memories),
        "new": new_count,
        "skipped": skipped,
        "total": engine.get_stats()["total_memories"],
    }


@app.post("/api/sync/pull")
async def sync_pull(req: PullRequest, node_id: str = Depends(verify_peer)):
    """Send memories to a peer.

    By default returns memories from OTHER nodes only. Set ``include_self=True``
    to also receive memories the peer originally pushed (useful when the peer's
    local DB was lost / rebuilt and needs to re-hydrate from the hub).
    """
    engine = get_engine()
    _note_peer_activity(req.node_id, getattr(req, "node_name", ""), transport="http")

    conditions: list[str] = []
    params: list[Any] = []

    if not req.include_self:
        conditions.append("source_node != ?")
        params.append(req.node_id)
    if req.since:
        conditions.append("timestamp > ?")
        params.append(req.since)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    params.append(req.limit)
    query = f"SELECT * FROM memories {where} ORDER BY timestamp DESC LIMIT ?"

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
    return {"peers": _peers_with_status()}


# ── WebSocket for realtime sync ──


def _ws_origin_allowed(origin: str) -> bool:
    """Allowlist of Origins permitted to open the sync WebSocket.

    Set ``ANIMUS_WS_ALLOWED_ORIGINS`` to a comma-separated list. If
    empty, only requests with no Origin header (i.e. native peer
    clients, not browsers) are accepted. ``*`` disables the check
    (dev only).
    """
    import os
    allow = os.environ.get("ANIMUS_WS_ALLOWED_ORIGINS", "").strip()
    if allow == "*":
        return True
    if not origin:
        # Non-browser clients (httpx, websockets lib) typically don't
        # send Origin; that's fine. CSRF only applies to browsers.
        return True
    allowed = {o.strip() for o in allow.split(",") if o.strip()}
    return origin in allowed


@app.websocket("/ws/sync")
async def websocket_sync(ws: WebSocket):
    """WebSocket endpoint for realtime peer synchronization."""
    origin = ws.headers.get("origin", "")
    if not _ws_origin_allowed(origin):
        await ws.close(code=4403, reason="Origin not allowed")
        return

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

        # Verify auth if configured. The handshake message itself is
        # the signed body, so a stolen header alone can't be replayed
        # against a different handshake.
        if config.server_secret:
            sig_headers = {
                "x-animus-node": msg.get("node_id", ""),
                "x-animus-timestamp": str(msg.get("timestamp", "")),
                "x-animus-nonce": msg.get("nonce", ""),
                "x-animus-signature": msg.get("signature", ""),
            }
            signed_body = (
                f"{msg.get('node_id', '')}|{msg.get('node_name', '')}|"
                f"{msg.get('timestamp', '')}|{msg.get('nonce', '')}"
            )
            if not verify_auth_header(
                config.server_secret, sig_headers, body=signed_body
            ):
                await ws.close(code=4003, reason="Invalid auth signature")
                return

        _note_peer_activity(peer_node_id, msg.get("node_name", ""), transport="ws")
        _connected_peers[peer_node_id]["capabilities"] = msg.get("capabilities", [])
        logger.info("Peer connected: %s (%s)", peer_node_id, msg.get("node_name"))

        await ws.send_text(SyncProtocol.ack("HANDSHAKE", 1))

        # Message loop
        engine = get_engine()
        while True:
            raw = await ws.receive_text()
            msg = SyncProtocol.parse(raw)

            if msg["type"] == "PUSH":
                memories, _skipped = SyncProtocol.memories_from_push(msg)
                new_count = engine.index_batch(memories)
                await ws.send_text(SyncProtocol.ack("PUSH", new_count, [m.id for m in memories]))

            elif msg["type"] == "PULL":
                if msg.get("include_self", False):
                    rows = engine.conn.execute(
                        "SELECT * FROM memories ORDER BY timestamp DESC LIMIT ?",
                        (msg.get("limit", 100),),
                    ).fetchall()
                else:
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
                _note_peer_activity(peer_node_id, transport="ws")

    except WebSocketDisconnect:
        logger.info("Peer disconnected: %s", peer_node_id)
    except Exception as e:
        logger.error("WebSocket error: %s", e)
    finally:
        # Keep the entry — presence now fades via the last_seen TTL, so a
        # peer that falls back to HTTP sync (or briefly drops the WS) still
        # shows up on the Brotherhood page with its last activity.
        if peer_node_id and peer_node_id in _connected_peers:
            _connected_peers[peer_node_id]["transport"] = "ws (closed)"


def create_app(config: AnimusConfig | None = None) -> FastAPI:
    """Create the FastAPI app (for programmatic use)."""
    global _config, _engine
    if config:
        _config = config
        _config.ensure_dirs()
        _engine = IndexEngine(_config.db_path)
    return app
