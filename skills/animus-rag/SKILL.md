---
name: animus-rag
description: >-
  Retrieves contextual memories, past solutions, architecture decisions, and transcripts from the local Animus Peer memory network (indexing Copilot, Claude Code, and Antigravity). Use this skill whenever you need context from past work, troubleshooting history, server configs, codebase background, or want to persist new decisions and insights.
---

# Animus RAG Skill (Eagle Vision Memory Network)

This skill connects the agent to the **Animus Peer** running on this server (`vps-hub-cc`), providing Retrieval-Augmented Generation (RAG) and Full-Text Search (Eagle Vision) across 100,000+ interactions from GitHub Copilot, Claude Code, Antigravity, and developer notes.

---

## Capabilities & Available Helpers

The skill provides executable Python scripts located in [`scripts/`](./scripts/):

1. **Contextual RAG Recall** ([`scripts/rag_recall.py`](./scripts/rag_recall.py)):
   Multi-query decomposition, workspace-aware boosting, recency weighting, and token budgeting.
   ```bash
   .agents/skills/animus-rag/scripts/rag_recall.py -c "<context or query>" [-w "<workspace>"] [-t <max_tokens>] [--detailed]
   ```

2. **Full-Text Search / Eagle Vision** ([`scripts/search.py`](./scripts/search.py)):
   Direct SQLite FTS5 search across all nodes, memory types, and tags.
   ```bash
   .agents/skills/animus-rag/scripts/search.py "<query>" [-t <memory_type>] [-w <workspace>] [-n <limit>]
   ```

3. **Session & Transcript Inspector** ([`scripts/session.py`](./scripts/session.py)):
   List conversation sessions or view full chronological turns from past AI assistant sessions.
   ```bash
   .agents/skills/animus-rag/scripts/session.py --list [-w <workspace>]
   .agents/skills/animus-rag/scripts/session.py -s "<session_id>" [--limit <turns>]
   ```

4. **Remember & Persist** ([`scripts/remember.py`](./scripts/remember.py)):
   Store new memories, insights, runbooks, or architectural decisions that automatically sync to the Brotherhood network.
   ```bash
   printf '%s\n' '<Content>' | .agents/skills/animus-rag/scripts/remember.py -t "<Title>" -w "<workspace>" --tags "<tag1,tag2>"
   .agents/skills/animus-rag/scripts/remember.py -t "<Title>" --content-file /path/to/note.md -w "<workspace>" --tags "<tag1,tag2>"
   ```
   Use `--content-file` or stdin for Markdown so line breaks remain real LF
   characters. Reserve `--content` for short plain text; suspicious Markdown
   containing literal `\\n` escapes is rejected unless explicitly allowed.

5. **Peer Stats & Health** ([`scripts/stats.py`](./scripts/stats.py)):
   View memory bank totals, node counts, sync state, and memory distribution.
   ```bash
   .agents/skills/animus-rag/scripts/stats.py
   ```

---

## When to Use This Skill

- **Resolving Complex or Ambiguous Errors**: Search for previous occurrences of similar error logs or stack traces.
- **Understanding Architecture Decisions**: Retrieve why a specific service, proxy, port, or database schema was configured in a certain way.
- **Revisiting Past Assistant Sessions**: Check commands executed, configurations written, or issues resolved in Claude Code, Copilot, or Antigravity sessions.
- **Saving Critical Learnings**: When a complex problem is solved or an important decision is taken, persist it via `remember.py`.

---

## Supporting Documentation

- [Memory Types Reference](./references/memory_types.md) — Explains each memory type (`copilot_chat`, `claude_chat`, `antigravity_chat`, etc.).
- [RAG Workflows & Best Practices](./references/rag_workflows.md) — Patterns for effective search and recall.
- [Sample Queries](./examples/sample_queries.md) — Reference examples and CLI commands.
