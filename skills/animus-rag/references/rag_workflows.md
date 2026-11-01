# Animus RAG Workflows & Best Practices

## 1. Contextual Retrieval During Tasks (RAG)
When solving ambiguous bugs, refactoring legacy services, or investigating server configurations:
1. Formulate a query containing the technical terms (service names, configuration keys, error messages).
2. Run `rag_recall.py -c "<context>" -w "<workspace>"`.
3. Animus decomposes the context into sub-queries, executes full-text search against the SQLite FTS5 index, re-ranks matching memories with recency and workspace weighting, and fits the best memories into your token budget.

## 2. Searching Past Decisions & Code Changes (Eagle Vision)
When you need exact past tool invocations, bash commands, or specific errors:
- Use `search.py "<query>" -w "<workspace>" --limit 10`.
- Filter by memory type (e.g. `-t claude_chat` or `-t antigravity_chat`) to focus on terminal sessions or assistant reasoning.

## 3. Reviewing Full Past Sessions
If a search hit belongs to an important past debug session:
- Run `session.py -s "<session_id>"` to reconstruct the entire chronological dialog and see step-by-step how an issue was resolved.

## 4. Persisting New Learnings & Decisions
When you complete a major task or make an architectural decision:
- Run `remember.py -t "<Title>" -c "<Description/Decision>" -w "<workspace>" --tags "tag1,tag2"` to synchronize it across all nodes in the Animus network.
