"""Tests for animus.mcp.rag (RAG Engine)."""

import pytest

from animus.mcp.rag import EXT_MAP, RAGEngine


class TestRAGEngine:
    @pytest.fixture
    def rag(self, populated_engine):
        return RAGEngine(populated_engine)

    def test_contextual_recall_returns_results(self, rag):
        results = rag.contextual_recall("Docker deployment with FastAPI")
        assert isinstance(results, list)

    def test_contextual_recall_workspace_filter(self, rag):
        results = rag.contextual_recall("Django migration", workspace="aura-erp")
        assert isinstance(results, list)

    def test_contextual_recall_max_tokens(self, rag):
        results = rag.contextual_recall("python", max_tokens=100)
        total_len = sum(len(r.get("content", "")) for r in results)
        # Should roughly respect budget (chars ~= tokens * 4)
        assert total_len < 1000  # 100 tokens * ~4-10 chars

    def test_file_context_by_extension(self, rag):
        results = rag.file_context("src/main.py", workspace="test")
        assert isinstance(results, list)

    def test_file_context_unknown_ext(self, rag):
        results = rag.file_context("README.txt")
        assert isinstance(results, list)

    def test_empty_context(self, rag):
        results = rag.contextual_recall("")
        assert isinstance(results, list)


class TestQueryDecomposition:
    @pytest.fixture
    def rag(self, populated_engine):
        return RAGEngine(populated_engine)

    def test_decompose_extracts_multiple_queries(self, rag):
        queries = rag._decompose_context(
            "How to fix the Django model migration issue on PostgreSQL?"
        )
        assert len(queries) >= 1
        assert len(queries) <= 8

    def test_decompose_short_context(self, rag):
        queries = rag._decompose_context("FastAPI")
        assert len(queries) >= 1

    def test_decompose_long_context(self, rag):
        long_text = "This is about " + "Django REST framework " * 50
        queries = rag._decompose_context(long_text)
        assert len(queries) <= 8  # Capped

    def test_extract_technical_terms(self, rag):
        terms = rag._extract_technical_terms(
            "Use FastAPI with PostgreSQL and docker-compose"
        )
        assert any("FastAPI" in t for t in terms)

    def test_extract_camelcase(self, rag):
        terms = rag._extract_technical_terms("The IndexEngine handles FTS queries")
        assert "IndexEngine" in terms

    def test_extract_snake_case(self, rag):
        terms = rag._extract_technical_terms("Call extract_searchable_text on the input")
        assert "extract_searchable_text" in terms

    def test_extract_error_patterns(self, rag):
        errors = rag._extract_error_patterns(
            "Got ImportError: No module named 'celery'"
        )
        assert len(errors) > 0

    def test_extract_key_phrases(self, rag):
        phrases = rag._extract_key_phrases(
            "How to deploy a Docker container. Use nginx as reverse proxy."
        )
        assert len(phrases) >= 1

    def test_no_duplicate_queries(self, rag):
        queries = rag._decompose_context("python Python PYTHON")
        lowered = [q.lower() for q in queries]
        assert len(lowered) == len(set(lowered))


class TestExtMap:
    def test_python_extension(self):
        assert ".py" in EXT_MAP
        assert "python" in EXT_MAP[".py"]

    def test_javascript_extension(self):
        assert ".js" in EXT_MAP
        assert "javascript" in EXT_MAP[".js"]

    def test_docker_extension(self):
        assert ".dockerfile" in EXT_MAP
        assert "docker" in EXT_MAP[".dockerfile"]
