"""Tests for animus.mcp (MCP server tools)."""

import json

import pytest

from animus.collector.models import Memory, MemoryType
from animus.config import AnimusConfig
from animus.indexer.engine import IndexEngine
from animus.mcp import AnimusMCPServer


@pytest.fixture
def mcp_server(config, populated_engine, monkeypatch):
    """Create an MCP server backed by the populated test engine."""
    server = AnimusMCPServer.__new__(AnimusMCPServer)
    server.config = config
    server.engine = populated_engine
    from animus.collector.antigravity import AntigravityCollector
    from animus.collector.claude import ClaudeCollector
    from animus.collector.copilot import CopilotCollector
    from animus.collector.copilot_cli import CopilotCliCollector
    server.collector = CopilotCollector(config)
    server.claude_collector = ClaudeCollector(config)
    server.antigravity_collector = AntigravityCollector(config)
    server.copilot_cli_collector = CopilotCliCollector(config)
    return server


class TestMCPProtocol:
    def test_initialize(self, mcp_server):
        msg = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
        resp = mcp_server.handle_message(msg)
        assert resp["id"] == 1
        assert "protocolVersion" in resp["result"]
        assert "capabilities" in resp["result"]

    def test_tools_list(self, mcp_server):
        msg = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
        resp = mcp_server.handle_message(msg)
        tools = resp["result"]["tools"]
        tool_names = {t["name"] for t in tools}
        assert "animus_search" in tool_names
        assert "animus_recall" in tool_names
        assert "animus_remember" in tool_names
        assert "animus_stats" in tool_names
        assert "animus_collect" in tool_names
        assert "animus_context" in tool_names
        assert "animus_timeline" in tool_names

    def test_resources_list(self, mcp_server):
        msg = {"jsonrpc": "2.0", "id": 3, "method": "resources/list", "params": {}}
        resp = mcp_server.handle_message(msg)
        resources = resp["result"]["resources"]
        assert len(resources) == 2

    def test_prompts_list(self, mcp_server):
        msg = {"jsonrpc": "2.0", "id": 4, "method": "prompts/list", "params": {}}
        resp = mcp_server.handle_message(msg)
        prompts = resp["result"]["prompts"]
        assert len(prompts) >= 1

    def test_unknown_method(self, mcp_server):
        msg = {"jsonrpc": "2.0", "id": 5, "method": "unknown/method", "params": {}}
        resp = mcp_server.handle_message(msg)
        assert "error" in resp

    def test_notification_returns_none(self, mcp_server):
        # Notifications have no id
        msg = {"jsonrpc": "2.0", "method": "initialized", "params": {}}
        resp = mcp_server.handle_message(msg)
        assert resp is None


class TestMCPToolSearch:
    def test_search_returns_results(self, mcp_server):
        msg = {
            "jsonrpc": "2.0", "id": 10,
            "method": "tools/call",
            "params": {"name": "animus_search", "arguments": {"query": "Docker"}},
        }
        resp = mcp_server.handle_message(msg)
        text = resp["result"]["content"][0]["text"]
        assert "Docker" in text or "memories found" in text

    def test_search_missing_query(self, mcp_server):
        msg = {
            "jsonrpc": "2.0", "id": 11,
            "method": "tools/call",
            "params": {"name": "animus_search", "arguments": {}},
        }
        resp = mcp_server.handle_message(msg)
        text = resp["result"]["content"][0]["text"]
        assert "Error" in text or "required" in text


class TestMCPToolRemember:
    def test_remember_stores_memory(self, mcp_server):
        msg = {
            "jsonrpc": "2.0", "id": 20,
            "method": "tools/call",
            "params": {
                "name": "animus_remember",
                "arguments": {
                    "title": "Test insight",
                    "content": "This is a test memory stored via MCP",
                    "tags": ["test"],
                },
            },
        }
        resp = mcp_server.handle_message(msg)
        text = resp["result"]["content"][0]["text"]
        assert "stored" in text.lower() or "remembered" in text.lower() or "saved" in text.lower() or "indexed" in text.lower()


class TestMCPToolStats:
    def test_stats_returns_data(self, mcp_server):
        msg = {
            "jsonrpc": "2.0", "id": 30,
            "method": "tools/call",
            "params": {"name": "animus_stats", "arguments": {}},
        }
        resp = mcp_server.handle_message(msg)
        text = resp["result"]["content"][0]["text"]
        assert "memor" in text.lower()  # "memories" or "memory"


class TestMCPToolCollect:
    def test_collect_runs(self, mcp_server):
        msg = {
            "jsonrpc": "2.0", "id": 40,
            "method": "tools/call",
            "params": {"name": "animus_collect", "arguments": {}},
        }
        resp = mcp_server.handle_message(msg)
        text = resp["result"]["content"][0]["text"]
        # Should not error
        assert resp["result"].get("isError") is not True


class TestMCPToolRecall:
    def test_recall_with_context(self, mcp_server):
        msg = {
            "jsonrpc": "2.0", "id": 50,
            "method": "tools/call",
            "params": {
                "name": "animus_recall",
                "arguments": {"context": "How to deploy a Django app with Docker"},
            },
        }
        resp = mcp_server.handle_message(msg)
        text = resp["result"]["content"][0]["text"]
        # Should return something (either results or "no memories")
        assert len(text) > 0


class TestMCPToolUnknown:
    def test_unknown_tool(self, mcp_server):
        msg = {
            "jsonrpc": "2.0", "id": 60,
            "method": "tools/call",
            "params": {"name": "nonexistent_tool", "arguments": {}},
        }
        resp = mcp_server.handle_message(msg)
        assert resp["result"]["isError"] is True


class TestMCPResources:
    def test_read_recent(self, mcp_server):
        msg = {
            "jsonrpc": "2.0", "id": 70,
            "method": "resources/read",
            "params": {"uri": "animus://memories/recent"},
        }
        resp = mcp_server.handle_message(msg)
        contents = resp["result"]["contents"]
        assert len(contents) == 1
        assert "application/json" in contents[0]["mimeType"]

    def test_read_stats(self, mcp_server):
        msg = {
            "jsonrpc": "2.0", "id": 71,
            "method": "resources/read",
            "params": {"uri": "animus://memories/stats"},
        }
        resp = mcp_server.handle_message(msg)
        contents = resp["result"]["contents"]
        data = json.loads(contents[0]["text"])
        assert "total_memories" in data

    def test_read_unknown_uri(self, mcp_server):
        msg = {
            "jsonrpc": "2.0", "id": 72,
            "method": "resources/read",
            "params": {"uri": "animus://unknown"},
        }
        resp = mcp_server.handle_message(msg)
        assert resp["result"]["contents"] == []
