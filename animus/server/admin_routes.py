"""Admin panel routes — The Animus Interface."""

from __future__ import annotations

import io
import json
import logging
import re
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
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
from .app import (
    get_config, get_engine, _connected_peers, _peer_is_online,
    _peers_with_status,
)

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
        "peers_online": sum(1 for p in _connected_peers.values() if _peer_is_online(p)),
        "peers": _peers_with_status(),
    })


# ── Memories ──

def _json_object(value: Any) -> dict[str, Any]:
    """Decode a SQLite JSON field without letting one malformed row break the UI."""
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        decoded = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _obsidian_record(row: dict[str, Any]) -> dict[str, Any]:
    """Return the safe, read-only projection used by Obsidian admin views."""
    metadata = _json_object(row.get("metadata"))
    frontmatter = metadata.get("frontmatter")
    if not isinstance(frontmatter, dict):
        frontmatter = {}
    return {
        "id": row.get("id", ""),
        "title": row.get("title", ""),
        "workspace": row.get("workspace", ""),
        "timestamp": row.get("timestamp", ""),
        "source_node": row.get("source_node", ""),
        "vault": str(metadata.get("vault") or "unknown"),
        "relative_path": str(metadata.get("relative_path") or ""),
        "project": str(
            frontmatter.get("projeto")
            or frontmatter.get("project")
            or frontmatter.get("workspace")
            or row.get("workspace")
            or "Geral"
        ),
        "status": str(frontmatter.get("status") or "unclassified"),
        "sensitivity": str(
            frontmatter.get("sensibilidade")
            or frontmatter.get("sensitivity")
            or "internal"
        ),
        "missing": bool(metadata.get("missing", False)),
        "managed": bool(metadata.get("exported_by_animus", False)),
    }


def _obsidian_catalog() -> list[dict[str, Any]]:
    engine = get_engine()
    rows = engine.conn.execute(
        "SELECT id, title, workspace, timestamp, source_node, metadata "
        "FROM memories WHERE type = ? ORDER BY timestamp DESC",
        ("obsidian_note",),
    ).fetchall()
    return [_obsidian_record(dict(row)) for row in rows]


def _filter_obsidian(
    notes: list[dict[str, Any]],
    *,
    vault: str = "",
    project: str = "",
    status: str = "",
    sensitivity: str = "",
    q: str = "",
) -> list[dict[str, Any]]:
    query = q.casefold().strip()
    return [
        note
        for note in notes
        if (not vault or note["vault"] == vault)
        and (not project or note["project"] == project)
        and (not status or note["status"] == status)
        and (not sensitivity or note["sensitivity"] == sensitivity)
        and (
            not query
            or query in note["title"].casefold()
            or query in note["relative_path"].casefold()
            or query in note["workspace"].casefold()
        )
    ]


def _obsidian_stats(notes: list[dict[str, Any]]) -> dict[str, Any]:
    def counts(field: str) -> dict[str, int]:
        result: dict[str, int] = {}
        for note in notes:
            value = str(note[field])
            result[value] = result.get(value, 0) + 1
        return dict(sorted(result.items()))

    active = [note for note in notes if not note["missing"]]
    return {
        "total": len(notes),
        "active": len(active),
        "missing": len(notes) - len(active),
        "managed": sum(1 for note in active if note["managed"]),
        "verified": sum(1 for note in active if note["status"] == "verificado"),
        "by_vault": counts("vault"),
        "by_project": counts("project"),
        "by_status": counts("status"),
        "by_sensitivity": counts("sensitivity"),
    }


@router.get("/admin/obsidian", response_class=HTMLResponse, name="admin_obsidian")
async def obsidian_page(
    request: Request,
    page: int = 1,
    vault: str = "",
    project: str = "",
    status: str = "",
    sensitivity: str = "",
    q: str = "",
    session: AdminSession = Depends(require_admin),
):
    page = max(1, page)
    per_page = 50
    catalog = _obsidian_catalog()
    notes = _filter_obsidian(
        catalog,
        vault=vault,
        project=project,
        status=status,
        sensitivity=sensitivity,
        q=q,
    )
    total_pages = max(1, (len(notes) + per_page - 1) // per_page)
    page = min(page, total_pages)
    offset = (page - 1) * per_page
    return templates.TemplateResponse(request, "obsidian.html", {
        "session": session,
        "stats": get_engine().get_stats(),
        "obsidian_stats": _obsidian_stats(catalog),
        "notes": notes[offset:offset + per_page],
        "total": len(notes),
        "page": page,
        "total_pages": total_pages,
        "vaults": sorted({note["vault"] for note in catalog}),
        "projects": sorted({note["project"] for note in catalog}),
        "statuses": sorted({note["status"] for note in catalog}),
        "sensitivities": sorted({note["sensitivity"] for note in catalog}),
        "filters": {
            "vault": vault,
            "project": project,
            "status": status,
            "sensitivity": sensitivity,
            "q": q,
        },
    })

@router.get("/admin/memories", response_class=HTMLResponse, name="admin_memories")
async def memories_page(
    request: Request,
    page: int = 1,
    mem_type: str = Query("", alias="type"),
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

    # Enrich rows with theme/session metadata so the template can show a
    # human-readable title instead of "user: ...." or "claude:assistant:...".
    for m in memories:
        try:
            meta = json.loads(m.get("metadata") or "{}")
        except (json.JSONDecodeError, TypeError):
            meta = {}
        m["theme_title"] = (
            meta.get("session_title") or meta.get("theme") or meta.get("name") or ""
        )
        m["memory_kind"] = meta.get("memory_kind") or meta.get("role") or ""
        m["session_id_meta"] = meta.get("session") or ""

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


# ── Sessions: reconstruct conversations as a coherent transcript ──

@router.get("/admin/sessions", response_class=HTMLResponse, name="admin_sessions")
async def sessions_index(
    request: Request,
    session: AdminSession = Depends(require_admin),
    workspace: str | None = None,
):
    """List every distinct Copilot session, biggest first."""
    engine = get_engine()
    where = ""
    params: list[Any] = []
    if workspace:
        where = "AND workspace = ?"
        params.append(workspace)
    rows = engine.conn.execute(
        f"""
        SELECT
            json_extract(metadata, '$.session') as session_id,
            workspace,
            source_node,
            -- type column gets renamed so {{{{ s.type }}}} in templates remains
            -- the per-row memory type column. We expose it as ``mem_type`` to
            -- keep the language-of-the-domain ("session type") consistent with
            -- the graph endpoint.
            MAX(type) as mem_type,
            COUNT(*) as turn_count,
            MIN(timestamp) as first_seen,
            MAX(timestamp) as last_seen,
            COALESCE(
                MAX(json_extract(metadata, '$.session_title')),
                MAX(CASE WHEN json_extract(metadata, '$.role') = 'user'
                         THEN title END)
            ) as session_title
        FROM memories
        WHERE json_extract(metadata, '$.session') IS NOT NULL {where}
        GROUP BY session_id, workspace, source_node
        ORDER BY last_seen DESC
        LIMIT 500
        """,
        params,
    ).fetchall()
    sessions = []
    for r in rows:
        d = dict(r)
        # Normalize the title: drop "transcript:role:" / "claude:role:" prefixes
        # so the list shows the actual chat subject.
        title = d.get("session_title") or ""
        for prefix in ("transcript:", "claude:"):
            if title.startswith(prefix):
                title = title.split(":", 2)[-1]
                break
        d["display_title"] = title.strip().splitlines()[0][:120] if title else ""
        d["is_claude"] = (d.get("mem_type") or "").startswith("claude_")
        sessions.append(d)
    workspaces_rows = engine.conn.execute(
        "SELECT DISTINCT workspace FROM memories WHERE workspace IS NOT NULL "
        "AND workspace != '' ORDER BY workspace"
    ).fetchall()
    return templates.TemplateResponse(request, "sessions.html", {
        "session": session,
        "sessions": sessions,
        "workspaces": [w["workspace"] for w in workspaces_rows],
        "filter_workspace": workspace,
    })


@router.get("/admin/sessions/{session_id}", response_class=HTMLResponse, name="admin_session_detail")
async def session_detail(
    request: Request,
    session_id: str,
    session: AdminSession = Depends(require_admin),
):
    """Render every turn of one Copilot session in chronological order."""
    engine = get_engine()
    rows = engine.conn.execute(
        """
        SELECT * FROM memories
        WHERE json_extract(metadata, '$.session') = ?
        ORDER BY COALESCE(sequence, 0), timestamp
        """,
        (session_id,),
    ).fetchall()
    if not rows:
        raise HTTPException(status_code=404, detail="Session not found")
    turns: list[dict] = []
    for r in rows:
        d = dict(r)
        try:
            d["metadata_parsed"] = json.loads(d.get("metadata") or "{}")
        except (json.JSONDecodeError, TypeError):
            d["metadata_parsed"] = {}
        turns.append(d)
    # Derive a human-readable chat title: prefer ``metadata.session_title`` if
    # the collector already stamped it; otherwise fall back to the first
    # user turn's text (stripping the ``role:`` prefix the collectors prepend).
    session_title = ""
    for t in turns:
        st = t["metadata_parsed"].get("session_title")
        if st:
            session_title = st
            break
    if not session_title:
        for t in turns:
            if t["metadata_parsed"].get("role") == "user":
                raw = t.get("title") or t.get("content") or ""
                for prefix in ("transcript:user:", "claude:user:"):
                    if raw.startswith(prefix):
                        raw = raw[len(prefix):]
                session_title = raw.strip().splitlines()[0][:160] if raw else ""
                break

    summary = {
        "session_id": session_id,
        "workspace": turns[0].get("workspace"),
        "source_node": turns[0].get("source_node"),
        "first_seen": turns[0].get("timestamp"),
        "last_seen": turns[-1].get("timestamp"),
        "turn_count": len(turns),
        "session_title": session_title,
        "is_claude": (turns[0].get("type") or "").startswith("claude_"),
    }
    return templates.TemplateResponse(request, "session_detail.html", {
        "session": session,
        "summary": summary,
        "turns": turns,
    })


# ── Neural Map: workspace × session graph ──

@router.get("/admin/graph", response_class=HTMLResponse, name="admin_graph")
async def graph_view(
    request: Request,
    session: AdminSession = Depends(require_admin),
):
    return templates.TemplateResponse(request, "graph.html", {"session": session})


@router.get("/admin/api/graph", name="admin_graph_data")
async def graph_data(
    session: AdminSession = Depends(require_admin),
    min_turns: int = 5,
):
    """Return nodes + edges for the Neural Map.

    Nodes:
      - one per workspace (``group="workspace"``) — anchors all chats from
        the same project
      - one per chat session with ≥ ``min_turns`` turns. Two flavors:
        Copilot Chat sessions (``group="session"``) and Claude Code sessions
        (``group="claude_session"``). The label is the human-readable chat
        title (first user prompt or session_title metadata) instead of an
        opaque UUID.
      - one per Claude Code auto-memory file (``group="memory"``) — the
        ``description`` from the file's frontmatter becomes the theme label,
        and the ``metadata.type`` (user / feedback / project / reference)
        becomes a secondary sub-group for color-coding.
    Edges:
      - workspace → session  (containment)
      - workspace → memory   (containment)
      - session ↔ session when they share ≥2 tags (cross-pollination)
      - memory ↔ session when the memory's name/theme appears in the session's
        first-user-prompt title (memory was likely written from that chat)
    """
    engine = get_engine()
    sess_rows = engine.conn.execute(
        """
        SELECT
            json_extract(metadata, '$.session') as session_id,
            workspace,
            type as mem_type,
            COUNT(*) as turn_count,
            MIN(timestamp) as first_seen,
            MAX(timestamp) as last_seen,
            -- First non-empty session_title wins; falls back to title text.
            COALESCE(
                MAX(json_extract(metadata, '$.session_title')),
                MAX(CASE WHEN json_extract(metadata, '$.role') = 'user'
                         THEN title END)
            ) as session_title
        FROM memories
        WHERE json_extract(metadata, '$.session') IS NOT NULL
        GROUP BY session_id, workspace, mem_type
        HAVING turn_count >= ?
        ORDER BY turn_count DESC
        """,
        (min_turns,),
    ).fetchall()

    def _clean_title(raw: str | None, fallback: str) -> str:
        if not raw:
            return fallback
        t = raw
        # Strip the "transcript:role:" / "claude:role:" prefixes the
        # collectors prepend so the node label reads like a human chat title.
        for prefix in ("transcript:", "claude:"):
            if t.startswith(prefix):
                t = t.split(":", 2)[-1]
                break
        return t.strip().splitlines()[0][:60] or fallback

    workspaces: dict[str, int] = {}
    sessions: list[dict] = []
    seen_sessions: set[str] = set()
    for r in sess_rows:
        sid = r["session_id"]
        if sid in seen_sessions:
            # Same session was recorded under multiple workspaces (e.g.
            # workspace was reset between turns). Skip the duplicate;
            # the first occurrence wins because rows are ordered by turn_count DESC.
            continue
        seen_sessions.add(sid)
        ws = r["workspace"] or "(unscoped)"
        workspaces[ws] = workspaces.get(ws, 0) + r["turn_count"]
        is_claude = (r["mem_type"] or "").startswith("claude_")
        title = _clean_title(r["session_title"], (sid or "")[:8])
        sessions.append({
            "id": f"s:{sid}",
            "label": title,
            "title": (
                f"{'Claude Code' if is_claude else 'Copilot'} session\\n"
                f"{title}\\n"
                f"Workspace: {ws}\\n"
                f"Turns: {r['turn_count']}\\n"
                f"{(r['first_seen'] or '')[:19]} → {(r['last_seen'] or '')[:19]}"
            ),
            "value": r["turn_count"],
            "group": "claude_session" if is_claude else "session",
            "workspace": ws,
            "session_id": sid,
            "_title_lc": title.lower(),
        })

    # Claude auto-memory files become their own thematic anchors.
    memory_rows = engine.conn.execute(
        """
        SELECT id, workspace, title, metadata, timestamp
        FROM memories
        WHERE type = 'claude_memory'
        ORDER BY timestamp DESC
        """
    ).fetchall()
    memories_nodes: list[dict] = []
    for r in memory_rows:
        try:
            meta = json.loads(r["metadata"] or "{}")
        except (json.JSONDecodeError, TypeError):
            meta = {}
        if meta.get("is_index"):
            continue  # Skip MEMORY.md — it's an index, not a thematic anchor.
        kind = (meta.get("memory_kind") or "memory").lower()
        theme = (meta.get("theme") or "").strip()
        name = (meta.get("name") or r["title"] or "").strip()
        label = name or theme[:40] or "memory"
        ws = r["workspace"] or "(unscoped)"
        workspaces.setdefault(ws, 0)
        memories_nodes.append({
            "id": f"m:{r['id']}",
            "label": label,
            "title": (
                f"Auto-memory: {name}\\n"
                f"Kind: {kind}\\n"
                f"{theme}\\n"
                f"Workspace: {ws}"
            ),
            "value": 1,
            "group": "memory",
            "memory_kind": kind,
            "theme": theme,
            "workspace": ws,
            "_label_lc": (label + " " + theme).lower(),
        })

    nodes: list[dict] = []
    edges: list[dict] = []
    for ws, total in workspaces.items():
        nodes.append({
            "id": f"w:{ws}",
            "label": ws,
            "title": f"Workspace {ws}\\nTotal turns: {total}",
            "value": max(total, 1),
            "group": "workspace",
        })
    for s in sessions:
        # Strip our internal helper field from the response payload.
        nodes.append({k: v for k, v in s.items() if not k.startswith("_")})
        edges.append({
            "from": f"w:{s['workspace']}",
            "to": s["id"],
            "color": {"opacity": 0.25},
            "width": 1,
        })
    for m in memories_nodes:
        nodes.append({k: v for k, v in m.items() if not k.startswith("_")})
        edges.append({
            "from": f"w:{m['workspace']}",
            "to": m["id"],
            "color": {"opacity": 0.2},
            "dashes": [2, 4],
            "width": 1,
        })

    # Tag-based edges between sessions in different workspaces (cross-pollination).
    # Aggregate top tags per session, then connect pairs sharing ≥2 tags.
    tag_rows = engine.conn.execute(
        """
        SELECT json_extract(metadata, '$.session') as sid,
               tags
        FROM memories
        WHERE json_extract(metadata, '$.session') IS NOT NULL
          AND tags IS NOT NULL AND tags != '[]'
        """
    ).fetchall()
    from collections import defaultdict
    tags_per_session: dict[str, set[str]] = defaultdict(set)
    for tr in tag_rows:
        try:
            tag_list = json.loads(tr["tags"])
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(tag_list, list):
            tags_per_session[tr["sid"]].update(t for t in tag_list if isinstance(t, str))

    # Cross-pollination edges. Origin tags (``claude``, ``copilot``,
    # ``claude-memory``) are stamped on every session of the matching source,
    # so they would create a dense intra-source web while saying nothing
    # about topic overlap. We strip them before counting shared tags so the
    # ≥2-tags rule continues to mean "same two topics" — the original intent.
    _GENERIC_TAGS = {"claude", "copilot", "claude-memory"}
    sess_ids = [s["session_id"] for s in sessions]
    for i, a in enumerate(sess_ids):
        for b in sess_ids[i + 1:]:
            shared = (tags_per_session[a] & tags_per_session[b]) - _GENERIC_TAGS
            if len(shared) >= 2:
                edges.append({
                    "from": f"s:{a}",
                    "to": f"s:{b}",
                    "color": {"color": "#c8a84e", "opacity": 0.5},
                    "width": min(4, len(shared) / 2),
                    "title": f"Shared tags: {', '.join(sorted(shared))}",
                    "dashes": True,
                })

    # Memory ↔ session lineage: when a memory's name or theme text appears in
    # a session's title we link them — the memory was almost certainly written
    # from (or about) that conversation.
    for m in memories_nodes:
        name_tokens = [
            tok for tok in m["_label_lc"].replace("-", " ").split()
            if len(tok) >= 4
        ]
        if not name_tokens:
            continue
        for s in sessions:
            hits = sum(1 for tok in name_tokens if tok in s["_title_lc"])
            if hits >= 2 or (hits == 1 and len(name_tokens) == 1):
                edges.append({
                    "from": m["id"],
                    "to": s["id"],
                    "color": {"color": "#00ff88", "opacity": 0.45},
                    "width": 1,
                    "title": f"Memory references session ({hits} tokens matched)",
                    "dashes": [4, 2],
                })

    return {"nodes": nodes, "edges": edges}


@router.get("/admin/api/memories/{memory_id}/related", name="admin_memory_related")
async def memory_related(
    memory_id: str,
    session: AdminSession = Depends(require_admin),
):
    """Sibling memories: previous/next turn in the session, and a few neighbours."""
    engine = get_engine()
    row = engine.conn.execute(
        "SELECT * FROM memories WHERE id = ?", (memory_id,)
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Memory not found")
    try:
        meta = json.loads(row["metadata"] or "{}")
    except (json.JSONDecodeError, TypeError):
        meta = {}
    session_id = meta.get("session")
    if not session_id:
        return {"session_id": None, "prev": None, "next": None, "siblings": []}

    seq = row["sequence"] if row["sequence"] is not None else 0
    prev_row = engine.conn.execute(
        """
        SELECT id, title, sequence, json_extract(metadata, '$.role') as role
        FROM memories
        WHERE json_extract(metadata, '$.session') = ?
          AND COALESCE(sequence, 0) < ?
        ORDER BY COALESCE(sequence, 0) DESC LIMIT 1
        """,
        (session_id, seq),
    ).fetchone()
    next_row = engine.conn.execute(
        """
        SELECT id, title, sequence, json_extract(metadata, '$.role') as role
        FROM memories
        WHERE json_extract(metadata, '$.session') = ?
          AND COALESCE(sequence, 0) > ?
        ORDER BY COALESCE(sequence, 0) ASC LIMIT 1
        """,
        (session_id, seq),
    ).fetchone()
    sibling_rows = engine.conn.execute(
        """
        SELECT id, title, sequence, json_extract(metadata, '$.role') as role
        FROM memories
        WHERE json_extract(metadata, '$.session') = ? AND id != ?
        ORDER BY ABS(COALESCE(sequence, 0) - ?) ASC
        LIMIT 12
        """,
        (session_id, memory_id, seq),
    ).fetchall()
    return {
        "session_id": session_id,
        "prev": dict(prev_row) if prev_row else None,
        "next": dict(next_row) if next_row else None,
        "siblings": [dict(r) for r in sibling_rows],
    }


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
    connected = _peers_with_status()
    historical = [dict(r) for r in peer_stats]

    # Public hub URL preferred (falls back to request host)
    hub_url = config.hub_url or f"https://{request.url.netloc}"
    repo_url = "https://github.com/GuilhermeP96/animus"

    return templates.TemplateResponse(request, "peers.html", {
        "session": session,
        "peers_online": sum(1 for p in connected if p["online"]),
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


def _safe_peer_value(value: str | None, fallback: str) -> str:
    """Keep peer-derived values safe for env files, ZIP paths and filenames."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", (value or "").strip())
    return cleaned.strip(".-")[:80] or fallback


def _installer_response(
    request: Request, node_id: str, node_name: str, os_name: str = ""
) -> StreamingResponse:
    """Render the idempotent install/update kit for one resolved peer."""
    config = get_config()
    secret = config.server_secret or ""
    if not secret:
        raise HTTPException(
            status_code=409,
            detail="Hub has no ANIMUS_SERVER_SECRET configured — set it in .env first.",
        )
    if not _INSTALLER_KIT_DIR.is_dir():
        raise HTTPException(status_code=500, detail="installer_kit templates missing")

    hub_url = config.hub_url or f"https://{request.url.netloc}"
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    substitutions = {
        "{{HUB_URL}}": hub_url,
        "{{SECRET}}": secret,
        "{{NODE_ID}}": node_id,
        "{{NODE_NAME}}": node_name,
        "{{OS_NAME}}": _safe_peer_value(os_name, "unknown"),
        "{{REPO_URL}}": "https://github.com/GuilhermeP96/animus.git",
        "{{BRANCH}}": "master",
        "{{GENERATED_AT}}": generated_at,
    }

    def render(body: str) -> str:
        for key, val in substitutions.items():
            body = body.replace(key, val)
        return body

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for fname in _INSTALLER_KIT_FILES:
            src = _INSTALLER_KIT_DIR / fname
            if not src.is_file():
                logger.warning("installer_kit: missing %s", src)
                continue
            # Explorer already creates a directory from the ZIP filename when
            # using "Extract All". Keep the archive flat to avoid producing
            # animus-peer-ID/animus-peer-ID on Windows.
            info = zipfile.ZipInfo(fname)
            info.compress_type = zipfile.ZIP_DEFLATED
            now = datetime.now(timezone.utc).timetuple()
            info.date_time = (
                now.tm_year, now.tm_mon, now.tm_mday,
                now.tm_hour, now.tm_min, now.tm_sec,
            )
            mode = 0o755 if fname in _INSTALLER_KIT_EXEC else 0o644
            info.external_attr = (mode & 0xFFFF) << 16
            body = render(src.read_text(encoding="utf-8"))
            # Windows PowerShell 5 treats UTF-8 without a BOM as an ANSI code
            # page. A BOM prevents accented text from corrupting PS syntax.
            encoding = "utf-8-sig" if src.suffix.lower() == ".ps1" else "utf-8"
            zf.writestr(info, body.encode(encoding))
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="animus-peer-{node_id}.zip"',
            "Cache-Control": "no-store",
        },
    )


@router.get("/admin/api/peers/installer.zip", name="admin_installer_zip")
async def installer_zip(
    request: Request,
    node_name: str | None = None,
    node_id: str | None = None,
    session: AdminSession = Depends(require_admin),
):
    """Build a customized peer installer ZIP with pre-baked hub URL, HMAC
    secret, node id and node name. Known IDs reuse their registered identity."""
    raw_id = node_id or str(uuid.uuid4())[:12]
    nid = _safe_peer_value(raw_id, str(uuid.uuid4())[:12])
    known = _connected_peers.get(nid, {})
    raw_name = node_name or known.get("node_name") or known.get("hostname")
    nname = _safe_peer_value(raw_name, f"peer-{nid}")
    return _installer_response(request, nid, nname, str(known.get("os_name") or ""))


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

@router.get("/admin/api/obsidian/stats")
async def admin_obsidian_stats(session: AdminSession = Depends(require_admin)):
    return _obsidian_stats(_obsidian_catalog())


@router.get("/admin/api/obsidian/notes")
async def admin_obsidian_notes(
    offset: int = 0,
    limit: int = 50,
    vault: str = "",
    project: str = "",
    status: str = "",
    sensitivity: str = "",
    q: str = "",
    session: AdminSession = Depends(require_admin),
):
    offset = max(0, offset)
    limit = min(max(1, limit), 200)
    notes = _filter_obsidian(
        _obsidian_catalog(),
        vault=vault,
        project=project,
        status=status,
        sensitivity=sensitivity,
        q=q,
    )
    return {"total": len(notes), "offset": offset, "limit": limit, "notes": notes[offset:offset + limit]}

@router.get("/admin/api/stats")
async def admin_stats(session: AdminSession = Depends(require_admin)):
    engine = get_engine()
    stats = engine.get_stats()
    stats["peers_online"] = sum(1 for p in _connected_peers.values() if _peer_is_online(p))
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
