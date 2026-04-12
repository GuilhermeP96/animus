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

        # Query by time
        from datetime import timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        cutoff_str = cutoff.isoformat()

        query = "SELECT * FROM memories WHERE timestamp > ? "
        params: list[Any] = [cutoff_str]

        if workspace:
            query += "AND workspace = ? "
            params.append(workspace)

        query += "ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        rows = self.engine.conn.execute(query, params).fetchall()

        if not rows:
            return f"No memories in the last {hours} hours."

        output = [f"⟁ Timeline — last {hours}h ({len(rows)} memories):\n"]
        for r in rows:
            row = dict(r)
            ts = row.get("timestamp", "")[:16]
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
