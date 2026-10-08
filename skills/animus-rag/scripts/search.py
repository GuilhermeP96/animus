#!/usr/bin/env /opt/animus-peer/bin/python3
"""
Animus Eagle Vision Search Script
Fast full-text search (SQLite FTS5) across all interaction memories (Copilot, Claude Code, Antigravity).
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


def format_markdown(results: list[dict], query: str, detailed: bool = False) -> str:
    if not results:
        return f"🦅 *Eagle Vision:* No memories found matching query `{query}`."

    lines = [f"### 🦅 Eagle Vision Search: `{query}` ({len(results)} matches)\n"]

    for i, r in enumerate(results, 1):
        mem_id = r.get("id", "")
        mem_type = r.get("type", "memory")
        title = r.get("title", "Untitled")
        ws = r.get("workspace", "global") or "global"
        ts = r.get("timestamp", "")[:19].replace("T", " ")
        content = r.get("content", "").strip()
        tags = r.get("tags", [])
        if isinstance(tags, str):
            try:
                tags = json.loads(tags)
            except Exception:
                tags = []

        tag_str = f" `{'` `'.join(tags)}`" if tags else ""

        lines.append(f"#### {i}. [{mem_type}] {title}")
        lines.append(f"- **ID:** `{mem_id}` | **Workspace:** `{ws}` | **Timestamp:** {ts}{tag_str}")
        lines.append("")

        if detailed:
            lines.append("```text")
            lines.append(content)
            lines.append("```")
        else:
            snippet = content[:350].replace("\n", " ")
            if len(content) > 350:
                snippet += "..."
            lines.append(f"> {snippet}")
        lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Search memories across all nodes and workspaces using Animus FTS5 (Eagle Vision)"
    )
    parser.add_argument("query", type=str, nargs="?", help="Search query")
    parser.add_argument("-q", "--query-opt", dest="query_opt", type=str, help="Search query (option form)")
    parser.add_argument("-t", "--type", type=str, help="Filter by memory type (e.g. claude_chat, copilot_chat, antigravity_chat, user_note, etc.)")
    parser.add_argument("-w", "--workspace", type=str, help="Filter by workspace/project")
    parser.add_argument("--node", type=str, help="Filter by source node")
    parser.add_argument("-n", "--limit", type=int, default=15, help="Max results (default: 15)")
    parser.add_argument("--detailed", "--full", action="store_true", help="Include full content in markdown")
    parser.add_argument("--format", choices=["markdown", "json", "text"], default="markdown", help="Output format")

    args = parser.parse_args()
    query = args.query or args.query_opt
    if not query:
        if not sys.stdin.isatty():
            query = sys.stdin.read().strip()
        else:
            parser.error("Query is required. Specify query as argument or pipe via stdin.")

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

    engine = IndexEngine(db_path)
    results = engine.search(
        query=query,
        mem_type=args.type,
        workspace=args.workspace,
        node=args.node,
        limit=args.limit,
    )

    if args.format == "json":
        print(json.dumps(results, indent=2, ensure_ascii=False))
    elif args.format == "markdown":
        print(format_markdown(results, query=query, detailed=args.detailed))
    else:
        for r in results:
            print(f"[{r.get('type')}] {r.get('workspace')}: {r.get('title')} ({r.get('timestamp')})")


if __name__ == "__main__":
    main()
