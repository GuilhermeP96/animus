# Codex collection

Collection requires `collect_codex_chat=true` and a nonempty
`codex_allowed_workspaces` allowlist. `collect_codex_memories` defaults to true
inside that consent boundary and can disable generated-memory collection
independently. Existing configuration files need not be rewritten.

## Supported sources

- `sessions/**/*.jsonl` and `archived_sessions/**/*.jsonl`: user messages and
  assistant final answers. Workspace consent follows each turn's context.
- `state_5.sqlite` plus `thread_history_1.sqlite`: paginated user/final messages
  for scoped main threads whose rollout file is no longer available. Subagent
  projections, reasoning, commands and tool results are excluded. Connections
  use SQLite read-only mode, query-only protection and a query deadline;
  uncheckpointed WAL data remains visible. Unsupported schemas are reported in
  collector diagnostics while independent sources continue working.
- Both `memories/rollout_summaries/*.md` and
  `memories_v2/rollout_summaries/*.md`: generated summaries with an explicit
  `thread_id`, timezone-aware `updated_at`, and authorized `cwd` header.

Global `MEMORY.md`, `memory_summary.md`, raw extraction databases, extension
notes without workspace provenance, and internal Git/baseline directories are
not imported. Global summaries can mix unauthorized projects. All imported
artifacts remain **candidates**, never verified Obsidian knowledge.

## Progress and deduplication

JSONL is read in bounded slices, including files larger than 64 MiB and files
older than seven days. Each cycle reads at most 64 MiB, with a 4 MiB slice per
session and at most 20 sessions. Oldest-visited scheduling prevents busy files
from monopolizing collection. Partial append records are retried intact;
oversized records are drained incrementally. Session metadata and turn context
are carried across slices. Initial historical backfill takes multiple cycles.

SQLite uses indexed per-thread update cursors and bounded pages. Collection
retains the existing `codex://<thread>/<rollout-ordinal>` identity across JSONL
and the history projection, with content-dependent memory IDs. An unchanged
message is not reinserted when its source migrates; a revised message is retained
as another version. Existing indexed memories are never deleted or rewritten.

Generated summaries use a thread ID plus a hash of their normalized text chunks,
independent of store version, filename, header timestamp and line endings.
Identical v1/v2 content deduplicates; changed summaries remain distinct evidence.
They use the existing `codex_chat` wire type for hub compatibility, identified by
`metadata.artifact=generated_memory`, `role=summary`, and a `codex-memory://` URI.
They are split at paragraph boundaries; oversized paragraphs are excluded rather
than truncated. Recognized secrets reject the whole summary before splitting.

Hub pull marks incoming records as already synchronized. Remote note revisions
therefore do not re-enter the upload queue or override a colliding local vault's
authority.

Checkpoints contain offsets and source metadata, not conversation bodies. They
are stored atomically in the Animus data directory, separately from configuration
and Codex state. Peer, CLI and MCP acknowledge checkpoints **after** successful
indexing. Failure before acknowledgment replays safely. Changing source directory,
workspace consent or summary opt-out selects a separate checkpoint namespace.
Corrupt checkpoints restart collection without deleting indexed data. Concurrent
stale checkpoint writers may cause replay, not skipped unindexed batches.

## Validation

Synthetic tests cover checkpoint replay/resume, archive fairness, oversized and
partial records, Windows extended paths, v1/v2 deduplication and revisions,
workspace/secret exclusions, live SQLite WAL reads, cross-source message IDs,
updated history items, read-only enforcement and unsupported-schema fallback.
Run the full isolated Windows suite with `python scripts/ci/validate.py`.
