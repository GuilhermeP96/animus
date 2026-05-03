"""Admin panel routes — The Animus Interface."""

from __future__ import annotations

import io
import json
import logging
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from .admin_auth import (
    AdminSession,
    clear_session_cookie,
    create_session_token,
    get_current_admin,
    require_admin,
    set_session_cookie,
    validate_credentials,
)
from .app import get_config, get_engine, _connected_peers

logger = logging.getLogger("animus.admin")

# ── Templates ──
_template_dir = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(_template_dir))

# ── Router ──
router = APIRouter()


# ── Login ──

class LoginForm(BaseModel):
    username: str
    password: str


@router.get("/login", response_class=HTMLResponse, name="admin_login")
async def login_page(request: Request):
    session = get_current_admin(request)
    if session:
        return RedirectResponse(url="/admin", status_code=302)
    return templates.TemplateResponse(request, "login.html", {"error": None})


@router.post("/login", response_class=HTMLResponse)
async def login_submit(request: Request):
    form = await request.form()
    username = form.get("username", "")
    password = form.get("password", "")

    if not validate_credentials(str(username), str(password)):
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "Accesso negado — credenciais inválidas"},
            status_code=401,
        )

    token = create_session_token(str(username))
    response = RedirectResponse(url="/admin", status_code=302)
    set_session_cookie(response, token)
    return response


@router.get("/logout")
async def logout(request: Request):
    response = RedirectResponse(url="/login", status_code=302)
    clear_session_cookie(response)
    return response


# ── Dashboard ──

@router.get("/admin", response_class=HTMLResponse, name="admin_dashboard")
async def dashboard(request: Request, session: AdminSession = Depends(require_admin)):
    engine = get_engine()
    stats = engine.get_stats()
    config = get_config()

    return templates.TemplateResponse(request, "dashboard.html", {
        "session": session,
        "stats": stats,
        "config": {
            "node_id": config.node_id,
            "node_name": config.node_name,
            "node_role": config.node_role,
        },
        "peers_online": len(_connected_peers),
        "peers": list(_connected_peers.values()),
    })


# ── Memories ──

@router.get("/admin/memories", response_class=HTMLResponse, name="admin_memories")
async def memories_page(
    request: Request,
    page: int = 1,
    mem_type: str = "",
    workspace: str = "",
    q: str = "",
    session: AdminSession = Depends(require_admin),
):
    engine = get_engine()
    per_page = 50
    offset = (page - 1) * per_page

    if q:
        # FTS search
        results = engine.search(q, mem_type=mem_type or None, workspace=workspace or None, limit=per_page)
        total = len(results)
        memories = results
    else:
        # Paginated listing
        conditions = []
        params: list[Any] = []
        if mem_type:
            conditions.append("type = ?")
            params.append(mem_type)
        if workspace:
            conditions.append("workspace = ?")
            params.append(workspace)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        total_row = engine.conn.execute(f"SELECT COUNT(*) as cnt FROM memories {where}", params).fetchone()
        total = total_row["cnt"]

        params_q = list(params) + [per_page, offset]
        rows = engine.conn.execute(
            f"SELECT * FROM memories {where} ORDER BY timestamp DESC LIMIT ? OFFSET ?",
            params_q,
        ).fetchall()
        memories = [dict(r) for r in rows]

    # Get filter options
    types_rows = engine.conn.execute("SELECT DISTINCT type FROM memories ORDER BY type").fetchall()
    ws_rows = engine.conn.execute("SELECT DISTINCT workspace FROM memories WHERE workspace != '' ORDER BY workspace").fetchall()

    stats = engine.get_stats()
    total_pages = max(1, (total + per_page - 1) // per_page)

    return templates.TemplateResponse(request, "memories.html", {
        "session": session,
        "memories": memories,
        "stats": stats,
        "total": total,
        "page": page,
        "total_pages": total_pages,
        "per_page": per_page,
        "types": [r["type"] for r in types_rows],
        "workspaces": [r["workspace"] for r in ws_rows],
        "filter_type": mem_type,
        "filter_workspace": workspace,
        "search_query": q,
    })


@router.get("/admin/memories/{memory_id}", response_class=HTMLResponse, name="admin_memory_detail")
async def memory_detail(
    request: Request,
    memory_id: str,
    session: AdminSession = Depends(require_admin),
):
    engine = get_engine()
    row = engine.conn.execute("SELECT * FROM memories WHERE id = ?", (memory_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Memory not found")

    memory = dict(row)
    # Parse JSON fields for display
    try:
        memory["metadata_parsed"] = json.loads(memory.get("metadata", "{}"))
    except (json.JSONDecodeError, TypeError):
        memory["metadata_parsed"] = {}
    try:
        memory["tags_parsed"] = json.loads(memory.get("tags", "[]"))
    except (json.JSONDecodeError, TypeError):
        memory["tags_parsed"] = []

    return templates.TemplateResponse(request, "memory_detail.html", {
        "session": session,
        "memory": memory,
    })


@router.delete("/admin/api/memories/{memory_id}")
async def delete_memory(
    memory_id: str,
    session: AdminSession = Depends(require_admin),
):
    engine = get_engine()
    engine.conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
    engine.conn.commit()
    return {"status": "deleted", "id": memory_id}


# ── Search (Eagle Vision) ──

@router.get("/admin/search", response_class=HTMLResponse, name="admin_search")
async def search_page(
    request: Request,
    q: str = "",
    session: AdminSession = Depends(require_admin),
):
    engine = get_engine()
    results = []
    if q:
        results = engine.search(q, limit=50)

    return templates.TemplateResponse(request, "search.html", {
        "session": session,
        "query": q,
        "results": results,
    })


# ── Peers ──

@router.get("/admin/peers", response_class=HTMLResponse, name="admin_peers")
async def peers_page(
    request: Request,
    session: AdminSession = Depends(require_admin),
):
    engine = get_engine()
    config = get_config()
    # Get peer stats from memories
    peer_stats = engine.conn.execute("""
        SELECT source_node, COUNT(*) as mem_count,
               MAX(timestamp) as last_activity,
               COUNT(DISTINCT workspace) as workspaces,
               COUNT(DISTINCT type) as types
        FROM memories
        GROUP BY source_node
        ORDER BY last_activity DESC
    """).fetchall()

    # Merge connected peers and historical stats
    connected = list(_connected_peers.values())
    historical = [dict(r) for r in peer_stats]

    # Public hub URL preferred (falls back to request host)
    hub_url = config.hub_url or f"https://{request.url.netloc}"
    repo_url = "https://github.com/GuilhermeP96/animus"

    return templates.TemplateResponse(request, "peers.html", {
        "session": session,
        "peers_online": len(_connected_peers),
        "peer_stats": connected,
        "historical_peers": historical,
        "hub_url": hub_url,
        "repo_url": repo_url,
    })


@router.post("/admin/api/peers/secret", name="admin_reveal_secret")
async def reveal_secret(session: AdminSession = Depends(require_admin)):
    """Return the shared HMAC secret. Admin-only; intended to be shown
    once in the UI after an explicit click."""
    config = get_config()
    return {"secret": config.server_secret or ""}


# ── Peer installer kit (self-contained ZIP) ──

_INSTALLER_KIT_DIR = Path(__file__).parent / "installer_kit"
# Files copied into the ZIP. Each goes through {{PLACEHOLDER}} substitution.
_INSTALLER_KIT_FILES = (
    "peer.env",
    "install.sh",
    "install.ps1",
    "install.bat",
    "COPILOT.md",
    "README.md",
)
# Files that should be marked executable in the ZIP (POSIX mode 0o755).
_INSTALLER_KIT_EXEC = {"install.sh"}


@router.get("/admin/api/peers/installer.zip", name="admin_installer_zip")
async def installer_zip(
    request: Request,
    node_name: str | None = None,
    node_id: str | None = None,
    session: AdminSession = Depends(require_admin),
):
    """Build a customized peer installer ZIP with pre-baked hub URL, HMAC
    secret, node id and node name. Admin-only."""
    config = get_config()
    secret = config.server_secret or ""
    if not secret:
        raise HTTPException(
            status_code=409,
            detail="Hub has no ANIMUS_SERVER_SECRET configured — set it in .env first.",
        )

    if not _INSTALLER_KIT_DIR.is_dir():
        raise HTTPException(
            status_code=500,
            detail=f"installer_kit templates missing at {_INSTALLER_KIT_DIR}",
        )

    hub_url = config.hub_url or f"https://{request.url.netloc}"
    repo_url = "https://github.com/GuilhermeP96/animus.git"
    branch = "master"
    nid = (node_id or str(uuid.uuid4())[:12]).strip()
    nname = (node_name or f"peer-{nid}").strip()
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    substitutions = {
        "{{HUB_URL}}": hub_url,
        "{{SECRET}}": secret,
        "{{NODE_ID}}": nid,
        "{{NODE_NAME}}": nname,
        "{{REPO_URL}}": repo_url,
        "{{BRANCH}}": branch,
        "{{GENERATED_AT}}": generated_at,
    }

    def render(text: str) -> str:
        for key, val in substitutions.items():
            text = text.replace(key, val)
        return text

    buf = io.BytesIO()
    folder = f"animus-peer-{nid}"
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for fname in _INSTALLER_KIT_FILES:
            src = _INSTALLER_KIT_DIR / fname
            if not src.is_file():
                logger.warning("installer_kit: missing %s", src)
                continue
            content = render(src.read_text(encoding="utf-8"))
            arcname = f"{folder}/{fname}"
            info = zipfile.ZipInfo(arcname)
            info.compress_type = zipfile.ZIP_DEFLATED
            now = datetime.now(timezone.utc).timetuple()
            info.date_time = (now.tm_year, now.tm_mon, now.tm_mday,
                              now.tm_hour, now.tm_min, now.tm_sec)
            # POSIX file mode in upper 16 bits of external_attr.
            mode = 0o755 if fname in _INSTALLER_KIT_EXEC else 0o644
            info.external_attr = (mode & 0xFFFF) << 16
            zf.writestr(info, content)

    buf.seek(0)
    filename = f"animus-peer-{nid}.zip"
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Cache-Control": "no-store",
    }
    return StreamingResponse(buf, media_type="application/zip", headers=headers)


# ── Settings ──

@router.get("/admin/settings", response_class=HTMLResponse, name="admin_settings")
async def settings_page(
    request: Request,
    session: AdminSession = Depends(require_admin),
):
    config = get_config()
    # Safe config display (mask secrets)
    safe_config = {}
    for key, val in config.model_dump().items():
        if any(s in key.lower() for s in ("secret", "token", "password", "key")):
            safe_config[key] = (str(val)[:8] + "••••••••") if val else "(empty)"
        else:
            safe_config[key] = str(val)

    return templates.TemplateResponse(request, "settings.html", {
        "session": session,
        "config": safe_config,
    })


# ── Admin API endpoints ──

@router.get("/admin/api/stats")
async def admin_stats(session: AdminSession = Depends(require_admin)):
    engine = get_engine()
    stats = engine.get_stats()
    stats["peers_online"] = len(_connected_peers)
    return stats


@router.get("/admin/api/timeline")
async def admin_timeline(
    days: int = 7,
    session: AdminSession = Depends(require_admin),
):
    engine = get_engine()
    rows = engine.conn.execute("""
        SELECT date(timestamp) as day, type, COUNT(*) as cnt
        FROM memories
        GROUP BY date(timestamp), type
        ORDER BY day DESC
        LIMIT ?
    """, (days * 10,)).fetchall()
    return {"timeline": [dict(r) for r in rows]}
