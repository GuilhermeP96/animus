#!/usr/bin/env /opt/animus-peer/bin/python3
"""
Animus RAG Recall Script
Retrieves contextual memories from Animus Peer memory bank using multi-query decomposition,
workspace boosting, recency weighting, and token budgeting.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Imported after Animus path setup below.

# Ensure Animus package is importable
try:
    from animus.config import AnimusConfig
    from animus.indexer.engine import IndexEngine
    from animus.mcp.rag import RAGEngine
except ImportError:
    sys.path.insert(0, "/home/repo/vps-hub/projects/animus")
    from animus.config import AnimusConfig
    from animus.indexer.engine import IndexEngine
    from animus.mcp.rag import RAGEngine

from helper_config import load_config


def format_markdown(results: list[dict], detailed: bool = False) -> str:
    if not results:
        return "🦅 *Animus RAG:* No relevant memories found for the given context."

    lines = [f"### 🦅 Animus Contextual Recall ({len(results)} memories retrieved)\n"]

    for i, r in enumerate(results, 1):
        mem_type = r.get("type", "memory")
        title = r.get("title", "Untitled Memory")
        ws = r.get("workspace", "global") or "global"
        ts = r.get("timestamp", "")[:19].replace("T", " ")
        score = r.get("_score", 0.0)
        content = r.get("content", "").strip()
        tags = r.get("tags", [])
        if isinstance(tags, str):
            try:
                tags = json.loads(tags)
            except Exception:
                tags = []

        tag_str = f" `{'` `'.join(tags)}`" if tags else ""

        lines.append(f"#### {i}. [{mem_type}] {title}")
        lines.append(f"- **Workspace:** `{ws}` | **Timestamp:** {ts} | **Score:** {score:.2f}{tag_str}")
        lines.append("")
        
        if detailed or len(content) <= 500:
            lines.append("```text")
            lines.append(content)
            lines.append("```")
        else:
            lines.append("```text")
            lines.append(content[:500] + f"\n... [truncated {len(content) - 500} chars]")
            lines.append("```")
        lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="RAG-powered contextual recall from Animus Peer memory network"
    )
    parser.add_argument(
        "-c", "--context",
        type=str,
        help="Context, query, or question for RAG retrieval (reads stdin if omitted and piped)",
    )
    parser.add_argument(
        "-w", "--workspace",
        type=str,
        default="",
        help="Filter or prioritize a specific workspace (e.g. vps-hub, datano, etc.)",
    )
    parser.add_argument(
        "-t", "--max-tokens",
        type=int,
        default=2000,
        help="Approximate maximum tokens of memory context to return (default: 2000)",
    )
    parser.add_argument(
        "--detailed",
        action="store_true",
        help="Do not truncate content in markdown output",
    )
    parser.add_argument(
        "--format",
        choices=["markdown", "json", "text"],
        default="markdown",
        help="Output format (default: markdown)",
    )

    args = parser.parse_args()

    context = args.context
    if not context:
        if not sys.stdin.isatty():
            context = sys.stdin.read().strip()
        else:
            parser.error("Context is required. Provide --context '<text>' or pipe via stdin.")

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
    rag = RAGEngine(engine)

    results = rag.contextual_recall(
        context,
        workspace=args.workspace,
        max_tokens=args.max_tokens,
    )

    if args.format == "json":
        print(json.dumps(results, indent=2, ensure_ascii=False))
    elif args.format == "markdown":
        print(format_markdown(results, detailed=args.detailed))
    else:
        for r in results:
            print(f"[{r.get('type')}] ({r.get('_score', 0):.2f}) {r.get('title')}: {r.get('content')[:120]}...")


if __name__ == "__main__":
    main()
