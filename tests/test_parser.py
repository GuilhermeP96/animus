"""Tests for animus.indexer.parser."""

import pytest

from animus.collector.models import Memory, MemoryType
from animus.indexer.parser import (
    _clean_knowledge_graph,
    _clean_log_content,
    _clean_markdown,
    extract_searchable_text,
    extract_tags,
)


class TestExtractSearchableText:
    def test_copilot_chat_json(self):
        mem = Memory(
            type=MemoryType.COPILOT_CHAT,
            source_node="n1",
            content='{"content": "How to use Docker", "type": "question"}',
        )
        text = extract_searchable_text(mem)
        assert "Docker" in text

    def test_copilot_chat_plaintext(self):
        mem = Memory(
            type=MemoryType.COPILOT_CHAT,
            source_node="n1",
            content="This is plain text content about FastAPI",
        )
        text = extract_searchable_text(mem)
        assert "FastAPI" in text

    def test_workspace_memory_strips_frontmatter(self):
        mem = Memory(
            type=MemoryType.WORKSPACE_MEMORY,
            source_node="n1",
            content="---\ntitle: X\n---\n# Heading\nBody text here.",
        )
        text = extract_searchable_text(mem)
        assert "title" not in text
        assert "Body text here" in text

    def test_workspace_memory_strips_code_blocks(self):
        mem = Memory(
            type=MemoryType.WORKSPACE_MEMORY,
            source_node="n1",
            content="Before ```python\nprint('hi')\n``` After",
        )
        text = extract_searchable_text(mem)
        assert "[code]" in text
        assert "After" in text

    def test_mcp_knowledge_json(self):
        mem = Memory(
            type=MemoryType.MCP_KNOWLEDGE,
            source_node="n1",
            content='{"name": "Redis", "entityType": "tool", "observations": ["Fast cache"]}',
        )
        text = extract_searchable_text(mem)
        assert "Redis" in text
        assert "Fast cache" in text

    def test_empty_content(self):
        mem = Memory(
            type=MemoryType.COPILOT_CHAT,
            source_node="n1",
            content="",
        )
        text = extract_searchable_text(mem)
        assert text == ""


class TestExtractTags:
    def test_detects_python(self):
        mem = Memory(
            type=MemoryType.COPILOT_CHAT,
            source_node="n1",
            content="Write a Python script with FastAPI",
        )
        tags = extract_tags(mem)
        assert "python" in tags

    def test_detects_docker(self):
        mem = Memory(
            type=MemoryType.COPILOT_CHAT,
            source_node="n1",
            content="Build a Dockerfile for the app",
        )
        tags = extract_tags(mem)
        assert "docker" in tags

    def test_detects_debug_topic(self):
        mem = Memory(
            type=MemoryType.COPILOT_CHAT,
            source_node="n1",
            content="Got an error: traceback in line 42",
        )
        tags = extract_tags(mem)
        assert "debug" in tags

    def test_detects_security_topic(self):
        mem = Memory(
            type=MemoryType.COPILOT_CHAT,
            source_node="n1",
            content="Configure authentication token for OWASP compliance",
        )
        tags = extract_tags(mem)
        assert "security" in tags

    def test_preserves_existing_tags(self):
        mem = Memory(
            type=MemoryType.COPILOT_CHAT,
            source_node="n1",
            content="Just some text",
            tags=["custom"],
        )
        tags = extract_tags(mem)
        assert "custom" in tags

    def test_deduplicates_tags(self):
        mem = Memory(
            type=MemoryType.COPILOT_CHAT,
            source_node="n1",
            content="Python python PYTHON",
            tags=["python"],
        )
        tags = extract_tags(mem)
        assert tags.count("python") == 1

    def test_detects_multiple_languages(self):
        mem = Memory(
            type=MemoryType.COPILOT_CHAT,
            source_node="n1",
            content="Use Python for the backend and JavaScript for the frontend with React",
        )
        tags = extract_tags(mem)
        assert "python" in tags
        assert "javascript" in tags

    def test_no_tags_for_generic_content(self):
        mem = Memory(
            type=MemoryType.COPILOT_CHAT,
            source_node="n1",
            content="Hello world",
            tags=[],
        )
        tags = extract_tags(mem)
        # ``copilot`` origin tag is always stamped on copilot turns; nothing
        # else fires for this generic content.
        assert tags == ["copilot"]

    @pytest.mark.parametrize("mem_type, expected_origin", [
        (MemoryType.CLAUDE_CHAT, "claude"),
        (MemoryType.CLAUDE_MEMORY, "claude"),
        (MemoryType.COPILOT_CHAT, "copilot"),
        (MemoryType.COPILOT_DEBUG, "copilot"),
        (MemoryType.COPILOT_INLINE, "copilot"),
    ])
    def test_origin_tag_per_type(self, mem_type, expected_origin):
        mem = Memory(type=mem_type, source_node="n1", content="hello", tags=[])
        assert expected_origin in extract_tags(mem)

    def test_no_origin_tag_for_non_chat_types(self):
        mem = Memory(
            type=MemoryType.WORKSPACE_MEMORY,
            source_node="n1",
            content="hello",
            tags=[],
        )
        tags = extract_tags(mem)
        assert "claude" not in tags
        assert "copilot" not in tags


class TestCleanLogContent:
    def test_valid_json_extracts_fields(self):
        result = _clean_log_content('{"content": "hello", "type": "user"}')
        assert "hello" in result
        assert "user" in result

    def test_invalid_json_returns_raw(self):
        result = _clean_log_content("not json at all")
        assert result == "not json at all"

    def test_json_without_known_keys(self):
        result = _clean_log_content('{"foo": "bar"}')
        assert result == '{"foo": "bar"}'


class TestCleanMarkdown:
    def test_strips_yaml_frontmatter(self):
        result = _clean_markdown("---\ntitle: X\n---\nBody text")
        assert "title: X" not in result
        assert "Body text" in result

    def test_strips_html_tags(self):
        result = _clean_markdown("Text <strong>bold</strong> end")
        assert "<strong>" not in result
        assert "bold" in result

    def test_collapses_whitespace(self):
        result = _clean_markdown("one   two\n\n\nthree")
        assert "  " not in result


class TestCleanKnowledgeGraph:
    def test_extracts_entity_info(self):
        result = _clean_knowledge_graph(
            '{"name": "Redis", "entityType": "cache", "observations": ["Fast", "In-memory"]}'
        )
        assert "Redis" in result
        assert "cache" in result
        assert "Fast" in result
        assert "In-memory" in result
