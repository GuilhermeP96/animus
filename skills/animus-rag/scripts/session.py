#!/usr/bin/env /opt/animus-peer/bin/python3
"""
Animus Session Inspector Script
Lists and reads full conversation sessions / transcripts from Copilot, Claude Code, and Antigravity.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Imported after Animus path setup below.

try:
    from animus.config import AnimusConfig
    from animus.indexer.engine import IndexEngine
except ImportError:
    sys.path.insert(0, "/home/repo/vps-hub/projects/animus")
    from animus.config import AnimusConfig
    from animus.indexer.engine import IndexEngine

from helper_config import load_config


def get_engine() -> IndexEngine:
    config = load_config()
    db_path = config.data_dir / "animus.db"
    if not db_path.exists():
        alt_paths = [
            Path("/root/.local/share/animus/animus.db"),
            Path("/opt/animus-peer/data/animus.db"),
        ]
        for p in alt_paths:
            if p.exists():
                db_path = p
                break
    return IndexEngine(db_path)


def list_sessions(workspace: str = "", limit: int = 20, min_turns: int = 2) -> None:
    engine = get_engine()
    sql = (
        "SELECT json_extract(metadata, '$.session') AS session_id, "
        "       workspace, source_node, COUNT(*) AS turn_count, "
        "       MIN(timestamp) AS first_seen, MAX(timestamp) AS last_seen "
        "FROM memories "
        "WHERE json_extract(metadata, '$.session') IS NOT NULL "
    )
    params = []
    if workspace:
        sql += "AND workspace LIKE ? "
        params.append(f"%{workspace}%")
    sql += (
        "GROUP BY session_id, workspace, source_node "
        "HAVING turn_count >= ? "
        "ORDER BY last_seen DESC LIMIT ?"
    )
    params.extend([min_turns, limit])

    rows = engine.conn.execute(sql, params).fetchall()
    if not rows:
        print("🦅 *Animus:* No sessions found matching criteria.")
        return

    print(f"### 🦅 Animus Conversation Sessions ({len(rows)} found)\n")
    print("| Session ID | Turns | Workspace | Node | Period |")
    print("| :--- | :--- | :--- | :--- | :--- |")
    for r in rows:
        d = dict(r)
        sid = d["session_id"]
        turns = d["turn_count"]
        ws = (d.get("workspace") or "-").split("/")[-1] or "/"
        node = (d.get("source_node") or "")[:8]
        p_start = (d.get("first_seen") or "")[:10]
        p_end = (d.get("last_seen") or "")[:10]
        period = f"{p_start} → {p_end}" if p_start != p_end else p_start
        print(f"| `{sid}` | {turns} | `{ws}` | `{node}` | {period} |")


def get_session(session_id: str, limit: int = 100, role_filter: str = "") -> None:
    engine = get_engine()
    rows = engine.conn.execute(
        "SELECT id, type, sequence, timestamp, workspace, content, metadata "
        "FROM memories WHERE json_extract(metadata, '$.session') = ? "
        "ORDER BY COALESCE(sequence, 0), timestamp",
        (session_id,),
    ).fetchall()

    if not rows:
        # Fallback: check if session_id is a substring or memory id
        rows = engine.conn.execute(
            "SELECT id, type, sequence, timestamp, workspace, content, metadata "
            "FROM memories WHERE json_extract(metadata, '$.session') LIKE ? "
            "ORDER BY COALESCE(sequence, 0), timestamp",
            (f"%{session_id}%",),
        ).fetchall()

    if not rows:
        print(f"🦅 *Animus:* No turns found for session `{session_id}`.")
        return

    first_row = dict(rows[0])
    ws = first_row.get("workspace", "")
    mtype = first_row.get("type", "")

    print(f"### 🦅 Session: `{session_id}`\n")
    print(f"- **Type:** `{mtype}` | **Workspace:** `{ws}` | **Total Turns:** {len(rows)}\n")

    shown = 0
    for r in rows:
        if shown >= limit:
            print(f"\n*... [truncated after {limit} turns]*")
            break

        d = dict(r)
        try:
            meta = json.loads(d.get("metadata") or "{}")
        except Exception:
            meta = {}

        role = meta.get("role", "message")
        if role_filter and role_filter.lower() not in role.lower():
            continue

        ts = (d.get("timestamp") or "")[:19].replace("T", " ")
        content = (d.get("content") or "").strip()

        print(f"#### 👤 **{role.upper()}** (`{ts}`)")
        print("```text")
        print(content)
        print("```\n")
        shown += 1


def main():
    parser = argparse.ArgumentParser(description="Inspect Animus conversation sessions and transcripts")
    parser.add_argument("-l", "--list", action="store_true", help="List recent conversation sessions")
    parser.add_argument("-s", "--session-id", type=str, help="Get full transcript for a specific session ID")
    parser.add_argument("-w", "--workspace", type=str, default="", help="Filter sessions by workspace")
    parser.add_argument("-n", "--limit", type=int, default=25, help="Limit number of sessions or turns")
    parser.add_argument("-r", "--role", type=str, default="", help="Filter turns by role (user/assistant)")

    args = parser.parse_args()

    if args.session_id:
        get_session(args.session_id, limit=args.limit, role_filter=args.role)
    elif args.list or not sys.argv[1:]:
        list_sessions(workspace=args.workspace, limit=args.limit)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
