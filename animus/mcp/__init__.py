"""Animus MCP Server — exposes memories as tools for Copilot.

This is a Model Context Protocol (MCP) server that runs via stdio,
allowing GitHub Copilot to directly query, store, and retrieve memories
in real-time during conversations.

Protocol: JSON-RPC 2.0 over stdio (MCP standard).
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import AnimusConfig
from ..indexer.engine import IndexEngine
from ..collector.copilot import CopilotCollector
from ..collector.models import Memory, MemoryType

logger = logging.getLogger("animus.mcp")


class AnimusMCPServer:
    """MCP Server that exposes Animus capabilities as tools.

    Tools exposed:
    - animus_search: Search memories (Eagle Vision)
    - animus_recall: Get memories relevant to current context (RAG)
    - animus_remember: Store a new memory from the current conversation
    - animus_forget: Remove a specific memory
    - animus_stats: Get memory statistics
    - animus_collect: Trigger a manual collection cycle
    - animus_context: Get contextual memories for a file/workspace
    - animus_timeline: Get chronological memory timeline
    - animus_session_list: List Copilot sessions (each is a full conversation)
    - animus_session: Get a full session transcript by id
    - animus_related: Get neighbouring turns of a memory in its session
    - animus_neural_map: Get the workspace × session graph (nodes + edges)
    """

    TOOL_DEFINITIONS = [
        {
            "name": "animus_search",
            "description": (
                "Search across all Copilot interaction memories using full-text search (Eagle Vision). "
                "Use this to find past conversations, code patterns, solutions, and decisions "
                "from any machine/workspace."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query — keywords, code snippets, error messages, etc.",
                    },
                    "type": {
                        "type": "string",
                        "description": "Filter by memory type: copilot_chat, copilot_debug, workspace_memory, mcp_knowledge, session_note, user_note, repo_note, prompt_file, agent_file",
                        "enum": [t.value for t in MemoryType],
                    },
                    "workspace": {
                        "type": "string",
                        "description": "Filter by workspace/project name",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum results (default: 10)",
                        "default": 10,
                    },
                },
                "required": ["query"],
            },
        },
        {
            "name": "animus_recall",
            "description": (
                "RAG-powered contextual recall — retrieves the most relevant memories "
                "based on the current conversation context. Use this when you need background "
                "knowledge, past decisions, or related code patterns to inform your response."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "context": {
                        "type": "string",
                        "description": "Current conversation context or question to find relevant memories for",
                    },
                    "workspace": {
                        "type": "string",
                        "description": "Current workspace name to prioritize",
                    },
                    "max_tokens": {
                        "type": "integer",
                        "description": "Approximate max tokens of context to return (default: 2000)",
                        "default": 2000,
                    },
                },
                "required": ["context"],
            },
        },
        {
            "name": "animus_remember",
            "description": (
                "Store a new memory — save an important decision, solution, pattern, or insight "
                "from the current conversation for future recall across all machines."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Short descriptive title for the memory",
                    },
                    "content": {
                        "type": "string",
                        "description": "The memory content — decision, solution, code pattern, etc.",
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Tags for categorization (e.g., ['python', 'docker', 'fix'])",
                    },
                    "workspace": {
                        "type": "string",
                        "description": "Associated workspace/project name",
                    },
                },
                "required": ["title", "content"],
            },
        },
        {
            "name": "animus_context",
            "description": (
                "Get contextual memories for a specific file or workspace. "
                "Returns memories related to the file's language, framework, and project."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path of the file being edited",
                    },
                    "workspace": {
                        "type": "string",
                        "description": "Workspace/project name",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum results (default: 5)",
                        "default": 5,
                    },
                },
                "required": [],
            },
        },
        {
            "name": "animus_timeline",
            "description": (
                "Get a chronological timeline of memories — see what you've been working on "
                "across all machines. Useful for resuming context after switching machines."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "hours": {
                        "type": "integer",
                        "description": "Hours to look back (default: 24)",
                        "default": 24,
                    },
                    "workspace": {
                        "type": "string",
                        "description": "Filter by workspace",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum results (default: 20)",
                        "default": 20,
                    },
                    "by_indexed": {
                        "type": "boolean",
                        "description": (
                            "Filter by local indexing time (when the memory was added "
                            "to this peer) instead of the original Copilot timestamp. "
                            "Useful right after a fresh `animus_collect` of old logs."
                        ),
                        "default": False,
                    },
                },
                "required": [],
            },
        },
        {
            "name": "animus_stats",
            "description": "Get Animus memory bank statistics — total memories, types, workspaces, sync status.",
            "inputSchema": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
        {
            "name": "animus_collect",
            "description": (
                "Trigger a manual memory collection cycle — scan Copilot logs, chat history, "
                "workspace configs, and MCP knowledge graph for new memories to index."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
        {
            "name": "animus_session_list",
            "description": (
                "List Copilot Chat sessions reconstructed from synced memories. Each session "
                "is a single conversation and may span thousands of turns. Use this to find "
                "which session a piece of work happened in before pulling its transcript with "
                "`animus_session`."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "workspace": {
                        "type": "string",
                        "description": "Filter by workspace identifier",
                    },
                    "min_turns": {
                        "type": "integer",
                        "description": "Only return sessions with at least this many turns (default: 1)",
                        "default": 1,
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum sessions returned, ordered by last activity desc (default: 25)",
                        "default": 25,
                    },
                },
                "required": [],
            },
        },
        {
            "name": "animus_session",
            "description": (
                "Get the full chronologically ordered transcript of a Copilot session. "
                "Returns every turn (user, assistant, tool) with role, sequence, timestamp "
                "and content. Use this to recover the entire context of a past conversation."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": "The session id (UUID, as returned by animus_session_list or stored in memory metadata)",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum turns to return; large sessions can have thousands (default: 200)",
                        "default": 200,
                    },
                    "offset": {
                        "type": "integer",
                        "description": "Skip the first N turns — use together with limit for paging",
                        "default": 0,
                    },
                    "role": {
                        "type": "string",
                        "description": "Optional role filter substring (e.g. 'user', 'assistant', 'tool')",
                    },
                    "search": {
                        "type": "string",
                        "description": "Optional case-insensitive substring filter on turn content",
                    },
                },
                "required": ["session_id"],
            },
        },
        {
            "name": "animus_related",
            "description": (
                "Given a memory id, return its previous and next turn in the same session "
                "plus the closest sibling turns. Use this to walk a conversation around any "
                "memory you have already located via search/recall."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "memory_id": {
                        "type": "string",
                        "description": "The id of the anchor memory",
                    },
                    "siblings": {
                        "type": "integer",
                        "description": "How many nearby siblings to return (default: 8)",
                        "default": 8,
                    },
                },
                "required": ["memory_id"],
            },
        },
        {
            "name": "animus_neural_map",
            "description": (
                "Get the Animus Neural Map — a graph linking workspaces to their sessions, "
                "with cross-session edges where they share semantic tags. Returns nodes and "
                "edges as JSON; useful to discover which conversations are related across "
                "projects without opening every transcript."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "min_turns": {
                        "type": "integer",
                        "description": "Minimum turns per session to include in the map (default: 5)",
                        "default": 5,
                    },
                },
                "required": [],
            },
        },
    ]

    RESOURCE_DEFINITIONS = [
        {
            "uri": "animus://memories/recent",
            "name": "Recent Memories",
            "description": "The 20 most recent memories across all sources",
            "mimeType": "application/json",
        },
        {
            "uri": "animus://memories/stats",
            "name": "Memory Statistics",
            "description": "Current memory bank statistics",
            "mimeType": "application/json",
        },
    ]

    def __init__(self):
        self.config = AnimusConfig.load()
        self.config.ensure_dirs()
        self.engine = IndexEngine(self.config.db_path)
        self.collector = CopilotCollector(self.config)

    def handle_message(self, message: dict) -> dict | None:
        """Handle a JSON-RPC message."""
        method = message.get("method", "")
        msg_id = message.get("id")
        params = message.get("params", {})

        handler = {
            "initialize": self._handle_initialize,
            "initialized": self._handle_initialized,
            "tools/list": self._handle_tools_list,
            "tools/call": self._handle_tools_call,
            "resources/list": self._handle_resources_list,
            "resources/read": self._handle_resources_read,
            "prompts/list": self._handle_prompts_list,
        }.get(method)

        if handler is None:
            if msg_id is not None:
                return self._error(msg_id, -32601, f"Method not found: {method}")
            return None

        try:
            result = handler(params)
            if msg_id is not None:
                return {"jsonrpc": "2.0", "id": msg_id, "result": result}
            return None
        except Exception as e:
            logger.error("Error handling %s: %s", method, e)
            if msg_id is not None:
                return self._error(msg_id, -32603, str(e))
            return None

    # ── Protocol Handlers ──

    def _handle_initialize(self, params: dict) -> dict:
        return {
            "protocolVersion": "2024-11-05",
            "capabilities": {
                "tools": {},
                "resources": {},
                "prompts": {},
            },
            "serverInfo": {
                "name": "animus",
                "version": "0.1.0",
            },
        }

    def _handle_initialized(self, params: dict) -> dict:
        return {}

    def _handle_tools_list(self, params: dict) -> dict:
        return {"tools": self.TOOL_DEFINITIONS}

    def _handle_tools_call(self, params: dict) -> dict:
        name = params.get("name", "")
        args = params.get("arguments", {})

        tool_handler = {
            "animus_search": self._tool_search,
            "animus_recall": self._tool_recall,
            "animus_remember": self._tool_remember,
            "animus_context": self._tool_context,
            "animus_timeline": self._tool_timeline,
            "animus_stats": self._tool_stats,
            "animus_collect": self._tool_collect,
            "animus_session_list": self._tool_session_list,
            "animus_session": self._tool_session,
            "animus_related": self._tool_related,
            "animus_neural_map": self._tool_neural_map,
        }.get(name)

        if tool_handler is None:
            return {
                "content": [{"type": "text", "text": f"Unknown tool: {name}"}],
                "isError": True,
            }

        try:
            result = tool_handler(args)
            return {"content": [{"type": "text", "text": result}]}
        except Exception as e:
            return {
                "content": [{"type": "text", "text": f"Error: {e}"}],
                "isError": True,
            }

    def _handle_resources_list(self, params: dict) -> dict:
        return {"resources": self.RESOURCE_DEFINITIONS}

    def _handle_resources_read(self, params: dict) -> dict:
        uri = params.get("uri", "")
        if uri == "animus://memories/recent":
            memories = self.engine.get_recent(20)
            return {
                "contents": [{
                    "uri": uri,
                    "mimeType": "application/json",
                    "text": json.dumps(memories, indent=2, default=str),
                }]
            }
        elif uri == "animus://memories/stats":
            stats = self.engine.get_stats()
            return {
                "contents": [{
                    "uri": uri,
                    "mimeType": "application/json",
                    "text": json.dumps(stats, indent=2, default=str),
                }]
            }
        return {"contents": []}

    def _handle_prompts_list(self, params: dict) -> dict:
        return {
            "prompts": [
                {
                    "name": "animus-context",
                    "description": "Inject relevant Animus memories as context for the current task",
                    "arguments": [
                        {
                            "name": "topic",
                            "description": "Topic or context to recall memories for",
                            "required": True,
                        }
                    ],
                }
            ]
        }

    # ── Tool Implementations ──

    def _tool_search(self, args: dict) -> str:
        query = args.get("query", "")
        if not query:
            return "Error: query is required"

        results = self.engine.search(
            query,
            mem_type=args.get("type"),
            workspace=args.get("workspace"),
            limit=args.get("limit", 10),
        )

        if not results:
            return f"No memories found for: {query}"

        output = [f"🦅 Eagle Vision — {len(results)} memories found for '{query}':\n"]
        for i, r in enumerate(results, 1):
            output.append(
                f"[{i}] {r.get('type', '?')} | {r.get('title', '')[:60]}\n"
                f"    Workspace: {r.get('workspace', '?')} | Node: {r.get('source_node', '?')}\n"
                f"    {r.get('content', '')[:200]}\n"
            )
        return "\n".join(output)

    def _tool_recall(self, args: dict) -> str:
        """RAG-powered contextual recall."""
        context = args.get("context", "")
        if not context:
            return "Error: context is required"

        workspace = args.get("workspace", "")
        max_tokens = args.get("max_tokens", 2000)

        # Multi-query RAG: extract key terms and search with multiple strategies
        from .rag import RAGEngine
        rag = RAGEngine(self.engine)
        results = rag.contextual_recall(context, workspace=workspace, max_tokens=max_tokens)

        if not results:
            return "No relevant memories found for this context."

        output = ["⟁ Animus Recall — relevant memories from your past interactions:\n"]
        for chunk in results:
            output.append(
                f"── {chunk['title']} ({chunk['type']}) ──\n"
                f"Source: {chunk.get('workspace', '?')} | {chunk.get('source_node', '?')}\n"
                f"{chunk['content']}\n"
            )
        return "\n".join(output)

    def _tool_remember(self, args: dict) -> str:
        title = args.get("title", "")
        content = args.get("content", "")
        if not title or not content:
            return "Error: title and content are required"

        memory = Memory(
            type=MemoryType.SESSION_NOTE,
            source_node=self.config.node_id,
            title=title,
            content=content,
            workspace=args.get("workspace", ""),
            tags=args.get("tags", []),
        )
        is_new = self.engine.index_memory(memory)
        if is_new:
            return f"✓ Memory stored: '{title}' (id: {memory.id})"
        return f"Memory already exists: '{title}'"

    def _tool_context(self, args: dict) -> str:
        file_path = args.get("file_path", "")
        workspace = args.get("workspace", "")
        limit = args.get("limit", 5)

        from .rag import RAGEngine
        rag = RAGEngine(self.engine)
        results = rag.file_context(file_path, workspace=workspace, limit=limit)

        if not results:
            return "No contextual memories found."

        output = [f"⟁ Context for {file_path or workspace}:\n"]
        for chunk in results:
            output.append(f"• {chunk['title']}: {chunk['content'][:150]}")
        return "\n".join(output)

    def _tool_timeline(self, args: dict) -> str:
        hours = args.get("hours", 24)
        workspace = args.get("workspace", "")
        limit = args.get("limit", 20)
        # When True, look at indexing time (when the memory landed locally)
        # instead of the original chat timestamp. Useful right after a
        # ``collect`` of older Copilot logs.
        by_indexed = bool(args.get("by_indexed", False))

        from datetime import timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        cutoff_str = cutoff.isoformat()

        def _query(time_col: str) -> list[Any]:
            sql = f"SELECT * FROM memories WHERE {time_col} > ? "
            sql_params: list[Any] = [cutoff_str if time_col == "timestamp"
                                     else cutoff.strftime("%Y-%m-%d %H:%M:%S")]
            if workspace:
                sql += "AND workspace = ? "
                sql_params.append(workspace)
            sql += f"ORDER BY {time_col} DESC LIMIT ?"
            sql_params.append(limit)
            return self.engine.conn.execute(sql, sql_params).fetchall()

        primary_col = "created_at" if by_indexed else "timestamp"
        rows = _query(primary_col)
        fallback_used = False
        if not rows and not by_indexed:
            # Heuristic fallback: maybe Copilot timestamps were old but the
            # rows were indexed recently — try created_at before giving up.
            rows = _query("created_at")
            fallback_used = bool(rows)

        if not rows:
            return f"No memories in the last {hours} hours."

        header = f"⟁ Timeline — last {hours}h ({len(rows)} memories"
        if fallback_used:
            header += ", by indexed time"
        elif by_indexed:
            header += ", by indexed time"
        header += "):\n"
        output = [header]
        for r in rows:
            row = dict(r)
            ts = (row.get("created_at") if (by_indexed or fallback_used)
                  else row.get("timestamp", ""))
            ts = (ts or "")[:16]
            output.append(
                f"  {ts} | {row.get('type', '?'):16s} | "
                f"{row.get('workspace', '?'):12s} | {row.get('title', '')[:40]}"
            )
        return "\n".join(output)

    def _tool_stats(self, args: dict) -> str:
        stats = self.engine.get_stats()
        lines = [
            "⟁ Animus Memory Bank",
            f"  Total memories:  {stats['total_memories']}",
            f"  Unique nodes:    {stats['unique_nodes']}",
            f"  Workspaces:      {stats['unique_workspaces']}",
            f"  Pending sync:    {stats['unsynced']}",
        ]
        if stats.get("by_type"):
            lines.append("\n  By type:")
            for t, c in sorted(stats["by_type"].items(), key=lambda x: x[1], reverse=True):
                lines.append(f"    {t:20s} {c}")
        return "\n".join(lines)

    def _tool_collect(self, args: dict) -> str:
        memories = self.collector.collect_all()
        new_count = self.engine.index_batch(memories)
        stats = self.engine.get_stats()
        return (
            f"✓ Collection complete\n"
            f"  Found: {len(memories)} | New: {new_count} | Total: {stats['total_memories']}"
        )

    # ── Session-aware tools (mirror /admin/sessions, /admin/graph) ──

    def _tool_session_list(self, args: dict) -> str:
        workspace = args.get("workspace")
        min_turns = max(1, int(args.get("min_turns") or 1))
        limit = max(1, int(args.get("limit") or 25))

        sql = (
            "SELECT json_extract(metadata, '$.session') AS session_id, "
            "       workspace, source_node, COUNT(*) AS turn_count, "
            "       MIN(timestamp) AS first_seen, MAX(timestamp) AS last_seen "
            "FROM memories "
            "WHERE json_extract(metadata, '$.session') IS NOT NULL "
        )
        params: list[Any] = []
        if workspace:
            sql += "AND workspace = ? "
            params.append(workspace)
        sql += (
            "GROUP BY session_id, workspace, source_node "
            "HAVING turn_count >= ? "
            "ORDER BY last_seen DESC LIMIT ?"
        )
        params.extend([min_turns, limit])

        rows = self.engine.conn.execute(sql, params).fetchall()
        if not rows:
            return "No sessions found."

        seen: set[str] = set()
        lines = [f"⟁ Sessions ({len(rows)}):\n"]
        for r in rows:
            d = dict(r)
            sid = d["session_id"]
            if sid in seen:
                continue
            seen.add(sid)
            lines.append(
                f"  {sid}  turns={d['turn_count']:>5}  "
                f"ws={d.get('workspace') or '-':<32}  "
                f"{(d.get('first_seen') or '')[:19]} → {(d.get('last_seen') or '')[:19]}"
            )
        return "\n".join(lines)

    def _tool_session(self, args: dict) -> str:
        session_id = args.get("session_id", "")
        if not session_id:
            return "Error: session_id is required"
        limit = max(1, int(args.get("limit") or 200))
        offset = max(0, int(args.get("offset") or 0))
        role_filter = (args.get("role") or "").lower().strip()
        search = (args.get("search") or "").lower().strip()

        rows = self.engine.conn.execute(
            "SELECT id, sequence, timestamp, workspace, content, metadata "
            "FROM memories WHERE json_extract(metadata, '$.session') = ? "
            "ORDER BY COALESCE(sequence, 0), timestamp",
            (session_id,),
        ).fetchall()
        if not rows:
            return f"No turns found for session {session_id}."

        # Apply optional filters before paging
        filtered = []
        for r in rows:
            d = dict(r)
            try:
                meta = json.loads(d.get("metadata") or "{}")
            except (json.JSONDecodeError, TypeError):
                meta = {}
            role = (meta.get("role") or "").lower()
            content = (d.get("content") or "")
            if role_filter and role_filter not in role:
                continue
            if search and search not in content.lower():
                continue
            d["_role"] = role or "?"
            filtered.append(d)

        total = len(filtered)
        page = filtered[offset:offset + limit]
        if not page:
            return (
                f"Session {session_id}: {total} turns matched filters, "
                f"but offset {offset} is past the end."
            )

        header = (
            f"⟁ Session {session_id}\n"
            f"  Total matching turns: {total} | showing {len(page)} "
            f"(offset {offset}, limit {limit})"
        )
        if role_filter or search:
            header += f" | filters: role~'{role_filter}' search~'{search}'"
        out = [header, ""]
        for d in page:
            seq = d.get("sequence")
            seq_s = f"#{seq}" if seq is not None else "#?"
            out.append(
                f"── {seq_s} [{d['_role']}] {(d.get('timestamp') or '')[:19]} "
                f"id={d['id']} ──"
            )
            content = (d.get("content") or "").rstrip()
            if len(content) > 4000:
                content = content[:4000] + f"\n…[truncated, full length {len(d['content'])}]"
            out.append(content)
            out.append("")
        return "\n".join(out)

    def _tool_related(self, args: dict) -> str:
        memory_id = args.get("memory_id", "")
        if not memory_id:
            return "Error: memory_id is required"
        sibling_count = max(1, min(50, int(args.get("siblings") or 8)))

        row = self.engine.conn.execute(
            "SELECT id, title, sequence, metadata FROM memories WHERE id = ?",
            (memory_id,),
        ).fetchone()
        if not row:
            return f"Memory {memory_id} not found."
        try:
            meta = json.loads(row["metadata"] or "{}")
        except (json.JSONDecodeError, TypeError):
            meta = {}
        session_id = meta.get("session")
        if not session_id:
            return f"Memory {memory_id} is not part of a Copilot session — no neighbours."

        seq = row["sequence"] if row["sequence"] is not None else 0
        prev_row = self.engine.conn.execute(
            "SELECT id, title, sequence, json_extract(metadata, '$.role') AS role "
            "FROM memories WHERE json_extract(metadata, '$.session') = ? "
            "AND COALESCE(sequence, 0) < ? "
            "ORDER BY COALESCE(sequence, 0) DESC LIMIT 1",
            (session_id, seq),
        ).fetchone()
        next_row = self.engine.conn.execute(
            "SELECT id, title, sequence, json_extract(metadata, '$.role') AS role "
            "FROM memories WHERE json_extract(metadata, '$.session') = ? "
            "AND COALESCE(sequence, 0) > ? "
            "ORDER BY COALESCE(sequence, 0) ASC LIMIT 1",
            (session_id, seq),
        ).fetchone()
        sibling_rows = self.engine.conn.execute(
            "SELECT id, title, sequence, json_extract(metadata, '$.role') AS role "
            "FROM memories WHERE json_extract(metadata, '$.session') = ? AND id != ? "
            "ORDER BY ABS(COALESCE(sequence, 0) - ?) ASC LIMIT ?",
            (session_id, memory_id, seq, sibling_count),
        ).fetchall()

        def fmt(r: Any) -> str:
            d = dict(r)
            seq_s = f"#{d['sequence']}" if d.get("sequence") is not None else "#?"
            return (
                f"  {seq_s:>6} [{(d.get('role') or '?'):20s}] "
                f"id={d['id']}  {(d.get('title') or '')[:60]}"
            )

        out = [
            f"⟁ Neural connections for memory {memory_id}",
            f"  Session: {session_id}  (anchor seq={seq})",
            "",
            "  Previous turn:",
            fmt(prev_row) if prev_row else "    (none — first turn)",
            "  Next turn:",
            fmt(next_row) if next_row else "    (none — last turn)",
            "",
            f"  Nearby turns ({len(sibling_rows)}):",
        ]
        out.extend(fmt(s) for s in sibling_rows)
        return "\n".join(out)

    def _tool_neural_map(self, args: dict) -> str:
        min_turns = max(1, int(args.get("min_turns") or 5))

        sess_rows = self.engine.conn.execute(
            "SELECT json_extract(metadata, '$.session') AS sid, workspace, "
            "       COUNT(*) AS turn_count, MIN(timestamp) AS first_seen, "
            "       MAX(timestamp) AS last_seen "
            "FROM memories WHERE json_extract(metadata, '$.session') IS NOT NULL "
            "GROUP BY sid, workspace "
            "HAVING turn_count >= ? ORDER BY turn_count DESC",
            (min_turns,),
        ).fetchall()
        if not sess_rows:
            return f"No sessions with at least {min_turns} turns."

        workspaces: dict[str, int] = {}
        sessions: list[dict] = []
        seen: set[str] = set()
        for r in sess_rows:
            sid = r["sid"]
            if sid in seen:
                continue
            seen.add(sid)
            ws = r["workspace"] or "(unscoped)"
            workspaces[ws] = workspaces.get(ws, 0) + r["turn_count"]
            sessions.append({
                "session_id": sid,
                "workspace": ws,
                "turns": r["turn_count"],
                "first_seen": r["first_seen"],
                "last_seen": r["last_seen"],
            })

        # Tag-based cross-session edges
        tag_rows = self.engine.conn.execute(
            "SELECT json_extract(metadata, '$.session') AS sid, tags FROM memories "
            "WHERE json_extract(metadata, '$.session') IS NOT NULL "
            "AND tags IS NOT NULL AND tags != '[]'"
        ).fetchall()
        from collections import defaultdict
        tags_per_session: dict[str, set[str]] = defaultdict(set)
        for tr in tag_rows:
            try:
                tags = json.loads(tr["tags"])
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(tags, list):
                tags_per_session[tr["sid"]].update(t for t in tags if isinstance(t, str))

        sids = [s["session_id"] for s in sessions]
        edges: list[dict] = []
        for i, a in enumerate(sids):
            for b in sids[i + 1:]:
                shared = tags_per_session[a] & tags_per_session[b]
                if len(shared) >= 2:
                    edges.append({
                        "from": a,
                        "to": b,
                        "shared_tags": sorted(shared),
                    })

        graph = {
            "workspaces": [
                {"id": ws, "total_turns": total} for ws, total in workspaces.items()
            ],
            "sessions": sessions,
            "tag_edges": edges,
        }

        # Compact human-readable summary plus the JSON for the agent.
        summary = [
            f"⟁ Animus Neural Map (min_turns={min_turns})",
            f"  Workspaces: {len(workspaces)} | Sessions: {len(sessions)} | "
            f"Tag-bridged edges: {len(edges)}",
            "",
            json.dumps(graph, indent=2, default=str),
        ]
        return "\n".join(summary)

    # ── Helpers ──

    @staticmethod
    def _error(msg_id: Any, code: int, message: str) -> dict:
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "error": {"code": code, "message": message},
        }

    def run(self) -> None:
        """Run the MCP server on stdio."""
        logger.info("Animus MCP Server starting (stdio)")

        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
                response = self.handle_message(message)
                if response is not None:
                    sys.stdout.write(json.dumps(response) + "\n")
                    sys.stdout.flush()
            except json.JSONDecodeError:
                err = self._error(None, -32700, "Parse error")
                sys.stdout.write(json.dumps(err) + "\n")
                sys.stdout.flush()


def main():
    """Entry point for the MCP server."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(message)s",
        stream=sys.stderr,  # Logs go to stderr, protocol on stdout
    )
    server = AnimusMCPServer()
    server.run()


if __name__ == "__main__":
    main()
