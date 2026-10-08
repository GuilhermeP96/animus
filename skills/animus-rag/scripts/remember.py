#!/usr/bin/env /opt/animus-peer/bin/python3
"""
Animus Remember Script
Stores a new memory, decision, architecture note, or insight into the Animus memory network.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Imported after Animus path setup below.

try:
    from animus.config import AnimusConfig
    from animus.collector.models import Memory, MemoryType
    from animus.indexer.engine import IndexEngine
except ImportError:
    sys.path.insert(0, "/home/repo/vps-hub/projects/animus")
    from animus.config import AnimusConfig
    from animus.collector.models import Memory, MemoryType
    from animus.indexer.engine import IndexEngine

from helper_config import load_config


def main():
    parser = argparse.ArgumentParser(description="Store a new memory in Animus Peer")
    parser.add_argument("-t", "--title", type=str, required=True, help="Memory title")
    content_group = parser.add_mutually_exclusive_group()
    content_group.add_argument("-c", "--content", type=str, help="Short plain-text content")
    content_group.add_argument(
        "--content-file",
        type=Path,
        help="Read UTF-8 Markdown from a file (recommended for structured notes)",
    )
    parser.add_argument("-w", "--workspace", type=str, default="", help="Workspace/project name")
    parser.add_argument("--tags", type=str, default="", help="Comma-separated tags (e.g. 'nginx,docker,security')")
    parser.add_argument("--type", type=str, default="user_note", choices=[t.value for t in MemoryType], help="Memory type")
    parser.add_argument(
        "--allow-escaped-newlines",
        action="store_true",
        help="Allow literal \\n sequences when they are intentional code/data",
    )

    args = parser.parse_args()

    if args.content_file:
        try:
            content = args.content_file.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError) as exc:
            parser.error(f"cannot read --content-file: {exc}")
    else:
        content = args.content
    if not content:
        if not sys.stdin.isatty():
            content = sys.stdin.read().strip()
        else:
            parser.error("Content is required. Use --content-file or pipe UTF-8 text via stdin.")

    escaped_breaks = content.count("\\n") + content.count("\\r\\n")
    looks_like_markdown = re.search(
        r"(?:^|\\n)(?:#{1,6}\s|[-*+]\s|\d+[.)]\s|```)", content
    )
    if (
        not args.allow_escaped_newlines
        and content.count("\n") <= 1
        and escaped_breaks >= 2
        and looks_like_markdown
    ):
        parser.error(
            "content looks like Markdown with literal \\n escapes; use --content-file "
            "or stdin with real line breaks (or --allow-escaped-newlines for intentional data)"
        )

    tags = [t.strip() for t in args.tags.split(",") if t.strip()] if args.tags else []

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
    
    mem_type = MemoryType(args.type)
    memory = Memory(
        type=mem_type,
        source_node=config.node_id,
        title=args.title,
        content=content,
        workspace=args.workspace,
        tags=tags,
    )

    is_new = engine.index_memory(memory)
    if is_new:
        print(f"✓ Memory stored successfully in Animus:")
        print(f"  ID:        {memory.id}")
        print(f"  Title:     {memory.title}")
        print(f"  Type:      {memory.type.value}")
        print(f"  Workspace: {memory.workspace or '(global)'}")
        print(f"  Tags:      {', '.join(memory.tags) if memory.tags else '(none)'}")
    else:
        print(f"⚠️ Memory with ID {memory.id} or identical content already exists.")


if __name__ == "__main__":
    main()
