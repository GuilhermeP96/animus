#!/usr/bin/env /opt/animus-peer/bin/python3
"""
Animus Stats Script
Displays current status, memory counts, nodes, and sync statistics of the Animus Peer.
"""

from __future__ import annotations

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


def main():
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
    stats = engine.get_stats()

    print("### 🦅 Animus Peer Status & Statistics\n")
    print(f"- **Node Name:** `{config.node_name}` (`{config.node_id[:8]}...`)")
    print(f"- **Node Role:** `{config.node_role}`")
    print(f"- **Hub URL:** `{config.hub_url}`")
    print(f"- **Data Directory:** `{config.data_dir}`")
    print(f"- **Total Memories:** **{stats['total_memories']:,}**")
    print(f"- **Unique Nodes:** {stats['unique_nodes']}")
    print(f"- **Indexed Workspaces:** {stats['unique_workspaces']}")
    print(f"- **Pending Sync to Hub:** {stats['unsynced']}")
    print("\n#### Memory Distribution by Type:")
    print("| Type | Count | Percentage |")
    print("| :--- | :--- | :--- |")
    total = max(1, stats['total_memories'])
    for t, c in sorted(stats.get("by_type", {}).items(), key=lambda x: x[1], reverse=True):
        pct = (c / total) * 100
        print(f"| `{t}` | {c:,} | {pct:.1f}% |")


if __name__ == "__main__":
    main()
