#!/usr/bin/env python3
"""Animus VPS Peer — validation tests.

Tests that the collector finds ALL VS Code memory sources on this VPS,
indexes them correctly, and can sync with the hub via internal network.

Run: /opt/animus-peer/bin/python tests/test_vps_peer.py
"""

import json
import os
import sys
import hashlib
import hmac
import time
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from animus.config import AnimusConfig
from animus.collector.copilot import CopilotCollector
from animus.collector.models import Memory, MemoryType
from animus.indexer.engine import IndexEngine

# ═══════════════════════════════════════════════════════════════
#  Constants
# ═══════════════════════════════════════════════════════════════

VSCODE_USER_DIR = Path("/root/.vscode-server/data/User")
HUB_INTERNAL_URL = "http://172.18.0.19:8314"
SERVER_SECRET = os.environ.get(
    "ANIMUS_SERVER_SECRET",
    "gLRPJSaJ3JKI11UXMwh79qAuiSTFBCFBHNoRAUEU9CI",
)

# Expected data sources found during audit
EXPECTED_WORKSPACES = {
    "2b8738f1d04e299861c9f731b9fd217d",
    "2b8738f1d04e299861c9f731b9fd217d-1",
    "-58f2bec9",
    "-58f2bec9-1",
    "18a1ac19",
}

EXPECTED_MEMORY_TOOL_FILES = {
    "datalchemy-v3.md",
    "mkgp96combr-exploration.md",
    "aura_exploration_findings.md",
}

EXPECTED_TRANSCRIPT_FILES = {
    "0107a86d-8a7a-4ea5-813f-777641843e57.jsonl",
}


def _header(text: str) -> None:
    print(f"\n{'═' * 60}")
    print(f"  {text}")
    print(f"{'═' * 60}")


def _ok(msg: str) -> None:
    print(f"  ✓ {msg}")


def _fail(msg: str) -> None:
    print(f"  ✗ {msg}")


def _info(msg: str) -> None:
    print(f"  ℹ {msg}")


# ═══════════════════════════════════════════════════════════════
#  Test 1: Directory Discovery
# ═══════════════════════════════════════════════════════════════

def test_directory_discovery() -> bool:
    _header("Test 1: VS Code Directory Discovery")
    ok = True

    # Check main user dir
    if VSCODE_USER_DIR.exists():
        _ok(f"VS Code user dir exists: {VSCODE_USER_DIR}")
    else:
        _fail(f"VS Code user dir NOT found: {VSCODE_USER_DIR}")
        return False

    # Check workspaceStorage
    ws_dir = VSCODE_USER_DIR / "workspaceStorage"
    if ws_dir.exists():
        found_ws = {d.name for d in ws_dir.iterdir() if d.is_dir()}
        _ok(f"workspaceStorage found with {len(found_ws)} workspaces")
        for ws in found_ws:
            _info(f"  workspace: {ws}")
        missing = EXPECTED_WORKSPACES - found_ws
        if missing:
            _fail(f"Missing expected workspaces: {missing}")
            ok = False
    else:
        _fail("workspaceStorage not found")
        ok = False

    # Check each data source type
    copilot_dirs = list(ws_dir.rglob("GitHub.copilot-chat")) if ws_dir.exists() else []
    _ok(f"Copilot Chat dirs found: {len(copilot_dirs)}")
    for cd in copilot_dirs:
        ws_name = cd.parent.name
        subdirs = [d.name for d in cd.iterdir() if d.is_dir()] if cd.exists() else []
        files = [f.name for f in cd.iterdir() if f.is_file()] if cd.exists() else []
        _info(f"  {ws_name}: dirs={subdirs}, files={files}")

    # Debug logs (with subdirectories)
    debug_dirs = list(ws_dir.rglob("debug-logs")) if ws_dir.exists() else []
    total_debug_files = 0
    for dd in debug_dirs:
        dfiles = list(dd.rglob("*"))
        dfiles = [f for f in dfiles if f.is_file()]
        total_debug_files += len(dfiles)
    _ok(f"Debug log dirs: {len(debug_dirs)}, total files: {total_debug_files}")

    # Transcripts
    transcript_dirs = list(ws_dir.rglob("transcripts")) if ws_dir.exists() else []
    total_transcripts = 0
    for td in transcript_dirs:
        tfiles = list(td.glob("*.jsonl"))
        total_transcripts += len(tfiles)
        for tf in tfiles:
            _info(f"  transcript: {tf.name} ({tf.stat().st_size} bytes)")
    if total_transcripts > 0:
        _ok(f"Transcripts found: {total_transcripts}")
    else:
        _fail("No transcripts found")
        ok = False

    # Memory tool files
    memory_tool_dirs = list(ws_dir.rglob("memory-tool")) if ws_dir.exists() else []
    total_mem_files = 0
    found_mem_names = set()
    for mtd in memory_tool_dirs:
        md_files = list(mtd.rglob("*.md"))
        total_mem_files += len(md_files)
        for mf in md_files:
            found_mem_names.add(mf.name)
            _info(f"  memory-tool: {mf.name} (ws: {mtd.parent.parent.name})")
    if total_mem_files > 0:
        _ok(f"Memory-tool .md files found: {total_mem_files}")
        missing_mems = EXPECTED_MEMORY_TOOL_FILES - found_mem_names
        if missing_mems:
            _fail(f"Missing expected memory files: {missing_mems}")
            ok = False
        else:
            _ok("All expected memory-tool files present")
    else:
        _fail("No memory-tool files found")
        ok = False

    # Chat session resources
    csr_files = list(ws_dir.rglob("chat-session-resources/*")) if ws_dir.exists() else []
    csr_files = [f for f in csr_files if f.is_file()]
    _ok(f"Chat session resource files: {len(csr_files)}")

    return ok


# ═══════════════════════════════════════════════════════════════
#  Test 2: Collector Coverage
# ═══════════════════════════════════════════════════════════════

def test_collector_coverage() -> bool:
    _header("Test 2: Collector Coverage")
    ok = True

    config = AnimusConfig(
        node_id="vps-peer-test",
        node_name="vps-peer-test",
        node_role="peer",
        data_dir=Path("/tmp/animus-test"),
        vscode_user_dir=VSCODE_USER_DIR,
    )

    collector = CopilotCollector(config)

    # Test each collector method individually
    debug_mems = collector._collect_debug_logs()
    _ok(f"Debug logs collected: {len(debug_mems)}")
    for m in debug_mems[:3]:
        _info(f"  [{m.type.value}] {m.title[:60]}")

    chat_mems = collector._collect_chat_history()
    _ok(f"Chat history collected: {len(chat_mems)}")
    for m in chat_mems[:3]:
        _info(f"  [{m.type.value}] {m.title[:60]}")

    transcript_mems = collector._collect_transcripts()
    if transcript_mems:
        _ok(f"Transcripts collected: {len(transcript_mems)}")
        # Check we got turns from the transcript
        roles = set(m.metadata.get("role", "?") for m in transcript_mems)
        _info(f"  Roles found in transcripts: {roles}")
        sessions = set(m.metadata.get("session", "?") for m in transcript_mems)
        _info(f"  Sessions: {sessions}")
        for m in transcript_mems[:3]:
            _info(f"  [{m.type.value}] {m.title[:80]}")
    else:
        _fail("No transcripts collected — collector._collect_transcripts() returned empty")
        ok = False

    memory_tool_mems = collector._collect_memory_tool()
    if memory_tool_mems:
        _ok(f"Memory-tool files collected: {len(memory_tool_mems)}")
        for m in memory_tool_mems:
            _info(f"  [{m.type.value}] {m.title} (ws: {m.workspace})")
    else:
        _fail("No memory-tool files collected")
        ok = False

    ws_mems = collector._collect_workspace_memories()
    _ok(f"Workspace memories collected: {len(ws_mems)}")
    for m in ws_mems[:3]:
        _info(f"  [{m.type.value}] {m.title[:60]}")

    mcp_mems = collector._collect_mcp_memory()
    _ok(f"MCP memories collected: {len(mcp_mems)}")

    # Full collect
    all_mems = collector.collect_all()
    _ok(f"Total collect_all(): {len(all_mems)}")

    # Type breakdown
    by_type: dict[str, int] = {}
    for m in all_mems:
        by_type[m.type.value] = by_type.get(m.type.value, 0) + 1
    _info("Type breakdown:")
    for t, c in sorted(by_type.items()):
        _info(f"  {t}: {c}")

    # Verify no duplicates by id
    ids = [m.id for m in all_mems]
    unique_ids = set(ids)
    if len(ids) != len(unique_ids):
        dupes = len(ids) - len(unique_ids)
        _fail(f"Found {dupes} duplicate memory IDs")
        ok = False
    else:
        _ok("No duplicate memory IDs")

    # Check that memories from different workspaces are captured
    ws_set = set(m.workspace for m in all_mems if m.workspace)
    _info(f"Workspaces with data: {ws_set}")
    if len(ws_set) >= 2:
        _ok(f"Memories from {len(ws_set)} different workspaces (multi-session coverage)")
    else:
        _fail(f"Only {len(ws_set)} workspace(s) have memories — expected ≥2")
        ok = False

    return ok


# ═══════════════════════════════════════════════════════════════
#  Test 3: Indexer
# ═══════════════════════════════════════════════════════════════

def test_indexer() -> bool:
    _header("Test 3: Index Engine")
    ok = True

    db_path = Path("/tmp/animus-test/animus-test.db")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()

    config = AnimusConfig(
        node_id="vps-peer-test",
        node_name="vps-peer-test",
        node_role="peer",
        data_dir=Path("/tmp/animus-test"),
        vscode_user_dir=VSCODE_USER_DIR,
    )

    collector = CopilotCollector(config)
    all_mems = collector.collect_all()

    engine = IndexEngine(db_path)
    new_count = engine.index_batch(all_mems)
    _ok(f"Indexed {new_count} new memories (from {len(all_mems)} collected)")

    stats = engine.get_stats()
    _ok(f"Total in index: {stats['total_memories']}")
    if stats.get("by_type"):
        _info("By type:")
        for t, c in sorted(stats["by_type"].items()):
            _info(f"  {t}: {c}")

    # Test search
    search_results = engine.search("DataAlchemy")
    if search_results:
        _ok(f"Search 'DataAlchemy' returned {len(search_results)} results")
        for r in search_results[:3]:
            _info(f"  {r.get('title', '?')[:60]}")
    else:
        _fail("Search 'DataAlchemy' returned no results")
        ok = False

    # Test re-indexing idempotency
    new_count2 = engine.index_batch(all_mems)
    if new_count2 == 0:
        _ok("Re-indexing same data: 0 new (idempotent)")
    else:
        _fail(f"Re-indexing added {new_count2} — expected 0")
        ok = False

    engine.close()
    return ok


# ═══════════════════════════════════════════════════════════════
#  Test 4: Hub Connectivity (loopback)
# ═══════════════════════════════════════════════════════════════

def test_hub_connectivity() -> bool:
    _header("Test 4: Hub Connectivity (internal network)")
    ok = True

    try:
        import httpx
    except ImportError:
        _fail("httpx not installed")
        return False

    # Test unauthenticated endpoints
    try:
        resp = httpx.get(f"{HUB_INTERNAL_URL}/health", timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            _ok(f"Health OK: {data}")
        else:
            _fail(f"Health returned {resp.status_code}")
            ok = False
    except Exception as e:
        _fail(f"Cannot reach hub at {HUB_INTERNAL_URL}: {e}")
        return False

    # Test authenticated endpoint
    from animus.network.crypto import create_auth_header
    node_id = "vps-peer-test"
    headers = create_auth_header(SERVER_SECRET, node_id)

    try:
        resp = httpx.get(f"{HUB_INTERNAL_URL}/api/stats", headers=headers, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            _ok(f"Authenticated /api/stats OK: {json.dumps(data, indent=2)[:200]}")
        else:
            _fail(f"/api/stats returned {resp.status_code}: {resp.text[:200]}")
            ok = False
    except Exception as e:
        _fail(f"Auth request failed: {e}")
        ok = False

    # Test without auth → should get 401
    try:
        resp = httpx.get(f"{HUB_INTERNAL_URL}/api/stats", timeout=5)
        if resp.status_code == 401:
            _ok("Unauthenticated /api/stats correctly returns 401")
        else:
            _fail(f"Expected 401, got {resp.status_code}")
            ok = False
    except Exception as e:
        _fail(f"Unauth request failed: {e}")
        ok = False

    return ok


# ═══════════════════════════════════════════════════════════════
#  Test 5: Full Sync Loop
# ═══════════════════════════════════════════════════════════════

def test_sync_loop() -> bool:
    _header("Test 5: Full Sync Loop (collect → index → push → pull)")
    ok = True

    import asyncio

    config = AnimusConfig(
        node_id="vps-peer-local",
        node_name="vps-peer-local",
        node_role="peer",
        data_dir=Path("/tmp/animus-peer-data"),
        vscode_user_dir=VSCODE_USER_DIR,
        hub_url=HUB_INTERNAL_URL,
        server_secret=SERVER_SECRET,
    )
    config.ensure_dirs()

    # Clean previous test data
    db = config.db_path
    if db.exists():
        db.unlink()

    from animus.network.peer import AnimusPeer

    peer = AnimusPeer(config)

    # Step 1: Collect and index
    new_count = asyncio.run(peer.collect_and_index())
    _ok(f"Collected and indexed: {new_count} new memories")

    if new_count == 0:
        _fail("No memories collected — nothing to sync")
        return False

    # Step 2: Push to hub
    pushed = asyncio.run(peer.sync_to_hub())
    if pushed > 0:
        _ok(f"Pushed {pushed} memories to hub")
    else:
        _fail(f"Push returned {pushed}")
        ok = False

    # Step 3: Pull from hub
    pulled = asyncio.run(peer.pull_from_hub())
    _ok(f"Pulled {pulled} memories from hub")

    # Step 4: Verify via API
    try:
        import httpx
        from animus.network.crypto import create_auth_header
        headers = create_auth_header(SERVER_SECRET, config.node_id)
        resp = httpx.get(f"{HUB_INTERNAL_URL}/api/stats", headers=headers, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            _ok(f"Hub stats after sync: {json.dumps(data)[:300]}")
        else:
            _fail(f"Stats check failed: {resp.status_code}")
    except Exception as e:
        _fail(f"Stats verification failed: {e}")
        ok = False

    # Step 5: Search on hub
    try:
        from animus.network.crypto import create_auth_header
        headers = create_auth_header(SERVER_SECRET, config.node_id)
        resp = httpx.post(
            f"{HUB_INTERNAL_URL}/api/search",
            json={"query": "DataAlchemy", "node_id": config.node_id},
            headers=headers,
            timeout=5,
        )
        if resp.status_code == 200:
            results = resp.json().get("results", [])
            _ok(f"Hub search 'DataAlchemy': {len(results)} results")
            for r in results[:3]:
                _info(f"  {r.get('title', '?')[:60]}")
        else:
            _fail(f"Hub search failed: {resp.status_code}")
            ok = False
    except Exception as e:
        _fail(f"Hub search failed: {e}")
        ok = False

    return ok


# ═══════════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("⟁ Animus VPS Peer — Validation Tests")
    print(f"  VS Code dir: {VSCODE_USER_DIR}")
    print(f"  Hub URL:     {HUB_INTERNAL_URL}")

    results = {}
    results["1_directory_discovery"] = test_directory_discovery()
    results["2_collector_coverage"] = test_collector_coverage()
    results["3_indexer"] = test_indexer()
    results["4_hub_connectivity"] = test_hub_connectivity()
    results["5_sync_loop"] = test_sync_loop()

    _header("RESULTS")
    all_ok = True
    for name, passed in results.items():
        status = "PASS ✓" if passed else "FAIL ✗"
        print(f"  {status}  {name}")
        if not passed:
            all_ok = False

    print()
    if all_ok:
        print("  ⟁ ALL TESTS PASSED — Animus peer is fully operational")
    else:
        print("  ⚠ Some tests failed — review above")

    sys.exit(0 if all_ok else 1)
