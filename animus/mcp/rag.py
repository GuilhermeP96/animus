"""RAG Engine — Retrieval-Augmented Generation for contextual memory recall.

Uses multi-query decomposition and re-ranking to find the most relevant
memories for the current conversation context.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from ..indexer.engine import IndexEngine


# ── File extension to language/framework mapping ──
EXT_MAP: dict[str, list[str]] = {
    ".py": ["python", "django", "fastapi", "flask"],
    ".js": ["javascript", "node", "react", "vue"],
    ".ts": ["typescript", "react", "angular", "node"],
    ".tsx": ["typescript", "react"],
    ".jsx": ["javascript", "react"],
    ".rs": ["rust", "cargo"],
    ".go": ["golang", "go"],
    ".java": ["java", "spring"],
    ".rb": ["ruby", "rails"],
    ".php": ["php", "laravel"],
    ".cs": ["csharp", "dotnet"],
    ".swift": ["swift", "ios"],
    ".kt": ["kotlin", "android"],
    ".dart": ["dart", "flutter"],
    ".sql": ["sql", "database", "postgres"],
    ".yml": ["yaml", "docker", "ci/cd", "deploy"],
    ".yaml": ["yaml", "docker", "ci/cd", "deploy"],
    ".dockerfile": ["docker", "container", "deploy"],
    ".sh": ["bash", "shell", "deploy"],
    ".md": ["markdown", "docs"],
    ".html": ["html", "frontend"],
    ".css": ["css", "frontend", "design"],
    ".scss": ["sass", "css", "frontend"],
    ".vue": ["vue", "javascript", "frontend"],
    ".svelte": ["svelte", "javascript", "frontend"],
}


class RAGEngine:
    """RAG engine for contextual memory retrieval.

    Strategies:
    1. Multi-query decomposition — break context into search terms
    2. Workspace-aware boosting — prioritize same-workspace memories
    3. Recency weighting — newer memories ranked higher
    4. De-duplication — merge overlapping results
    5. Token budgeting — fit within context window limits
    """

    def __init__(self, engine: IndexEngine):
        self.engine = engine

    def contextual_recall(
        self,
        context: str,
        *,
        workspace: str = "",
        max_tokens: int = 2000,
    ) -> list[dict]:
        """Find memories most relevant to the given context.

        Uses multi-query strategy: extract key terms from context,
        search each independently, then merge + re-rank.
        """
        queries = self._decompose_context(context)
        all_results: dict[str, dict] = {}  # id -> result with score

        for i, query in enumerate(queries):
            weight = 1.0 - (i * 0.1)  # First queries get higher weight

            # Search with workspace filter first (higher relevance)
            if workspace:
                results = self.engine.search(query, workspace=workspace, limit=5)
                for r in results:
                    self._accumulate(all_results, r, weight * 1.5)

            # Search globally
            results = self.engine.search(query, limit=8)
            for r in results:
                self._accumulate(all_results, r, weight)

        # Sort by accumulated score
        ranked = sorted(all_results.values(), key=lambda x: x.get("_score", 0), reverse=True)

        # Token budgeting
        return self._budget_tokens(ranked, max_tokens)

    def file_context(
        self,
        file_path: str,
        *,
        workspace: str = "",
        limit: int = 5,
    ) -> list[dict]:
        """Get memories relevant to a specific file."""
        queries = self._file_queries(file_path)
        all_results: dict[str, dict] = {}

        for query in queries:
            if workspace:
                for r in self.engine.search(query, workspace=workspace, limit=3):
                    self._accumulate(all_results, r, 1.5)
            for r in self.engine.search(query, limit=5):
                self._accumulate(all_results, r, 1.0)

        ranked = sorted(all_results.values(), key=lambda x: x.get("_score", 0), reverse=True)
        return ranked[:limit]

    # ── Query Decomposition ──

    def _decompose_context(self, context: str) -> list[str]:
        """Break context into multiple search queries.

        Strategy:
        1. Use full context as first query (most specific)
        2. Extract key phrases (2-4 word chunks)
        3. Extract technical terms (CamelCase, snake_case, etc.)
        4. Extract error patterns
        """
        queries = []

        # 1. Full context (truncated)
        clean = context.strip()
        if len(clean) > 200:
            clean = clean[:200]
        queries.append(clean)

        # 2. Key technical terms
        tech_terms = self._extract_technical_terms(context)
        for term in tech_terms[:5]:
            queries.append(term)

        # 3. Error patterns
        errors = self._extract_error_patterns(context)
        for err in errors[:3]:
            queries.append(err)

        # 4. Key phrases (noun phrases / important sequences)
        phrases = self._extract_key_phrases(context)
        for phrase in phrases[:3]:
            queries.append(phrase)

        # Deduplicate while preserving order
        seen = set()
        unique = []
        for q in queries:
            q_lower = q.lower().strip()
            if q_lower and q_lower not in seen and len(q_lower) > 3:
                seen.add(q_lower)
                unique.append(q)

        return unique[:8]  # Cap at 8 queries

    def _extract_technical_terms(self, text: str) -> list[str]:
        """Extract technical terms — CamelCase, snake_case, dotted.paths, etc."""
        terms = []

        # CamelCase identifiers
        terms.extend(re.findall(r'\b[A-Z][a-z]+(?:[A-Z][a-z]+)+\b', text))

        # snake_case identifiers
        terms.extend(re.findall(r'\b[a-z]+(?:_[a-z]+){1,}\b', text))

        # Dotted paths (module.class.method)
        terms.extend(re.findall(r'\b[a-zA-Z_]\w*(?:\.\w+){1,}\b', text))

        # Package names with hyphens
        terms.extend(re.findall(r'\b[a-z]+(?:-[a-z]+){1,}\b', text))

        # Framework/tool names (common ones)
        known = re.findall(
            r'\b(?:Django|FastAPI|React|Vue|Docker|Kubernetes|PostgreSQL|Redis|'
            r'Celery|nginx|gunicorn|pytest|Pydantic|SQLAlchemy|Express|Next\.js|'
            r'Tailwind|WireGuard|SSH|MCP|RAG|WebSocket|REST|GraphQL|gRPC)\b',
            text, re.IGNORECASE
        )
        terms.extend(known)

        return list(dict.fromkeys(terms))  # Deduplicate preserving order

    def _extract_error_patterns(self, text: str) -> list[str]:
        """Extract error messages and stack trace patterns."""
        patterns = []

        # Python exceptions
        patterns.extend(re.findall(r'(?:Error|Exception|Warning):\s*.+', text))
        # Traceback file references
        patterns.extend(re.findall(r'File ".+?", line \d+', text))
        # HTTP errors
        patterns.extend(re.findall(r'HTTP\s+\d{3}\b.*', text))
        # Generic error lines
        patterns.extend(re.findall(r'(?:error|failed|failure|fatal)[\s:]+.{10,60}', text, re.I))

        return patterns

    def _extract_key_phrases(self, text: str) -> list[str]:
        """Extract meaningful multi-word phrases."""
        # Remove code blocks
        clean = re.sub(r'```[\s\S]*?```', ' ', text)
        clean = re.sub(r'`[^`]+`', ' ', clean)

        # Split into sentences and take significant ones
        sentences = re.split(r'[.!?\n]', clean)
        phrases = []
        for s in sentences:
            s = s.strip()
            words = s.split()
            if 3 <= len(words) <= 12:
                phrases.append(s)

        return phrases

    def _file_queries(self, file_path: str) -> list[str]:
        """Generate search queries from a file path."""
        queries = []
        if not file_path:
            return queries

        p = Path(file_path)

        # File name
        queries.append(p.name)
        queries.append(p.stem)

        # Extension-based terms
        ext = p.suffix.lower()
        if ext in EXT_MAP:
            queries.extend(EXT_MAP[ext][:2])

        # Parent directory (often the module/feature name)
        if p.parent.name and p.parent.name not in (".", "src", "lib", "app"):
            queries.append(p.parent.name)

        return queries

    # ── Scoring & Budgeting ──

    def _accumulate(self, results: dict[str, dict], result: dict, weight: float) -> None:
        """Accumulate a result with weighted scoring."""
        rid = result.get("id", "")
        if not rid:
            return

        if rid in results:
            results[rid]["_score"] = results[rid].get("_score", 0) + weight
        else:
            result["_score"] = weight
            results[rid] = result

    def _budget_tokens(self, results: list[dict], max_tokens: int) -> list[dict]:
        """Select results that fit within the token budget."""
        budgeted = []
        used = 0
        # Rough estimate: 1 token ≈ 4 characters
        chars_budget = max_tokens * 4

        for r in results:
            content = r.get("content", "")
            title = r.get("title", "")
            size = len(content) + len(title) + 50  # overhead
            if used + size > chars_budget:
                # Try truncating
                remaining = chars_budget - used
                if remaining > 200:
                    r = dict(r)
                    r["content"] = content[:remaining] + "..."
                    budgeted.append(r)
                break
            budgeted.append(r)
            used += size

        return budgeted
