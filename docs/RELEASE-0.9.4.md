# Animus 0.9.4

## Changes

- Faster hub startup: legacy transcript repair is explicit maintenance instead
  of a mandatory startup step.
- Bounded statistics queries and indexed counting reduce statistics timeouts.
- Incremental Codex collection covers active and archived JSONL sessions,
  paginated SQLite history, and scoped generated memories from both v1/v2 stores.
- Acknowledged checkpoints resume after indexing; unchanged v1/v2 content
  deduplicates while revisions remain distinct evidence.
- Windows extended and UNC workspace paths are normalized consistently.
- Records received from the hub stay synchronized; remote note revisions cannot
  override a colliding local vault's authority.
- The compiled Windows desktop and installer identify themselves as 0.9.4 and
  retain the high-resolution animated tray icon and Datano/GitHub credits.

Codex collection still requires opt-in and workspace consent. Generated summaries
remain unverified candidates. Global memory indexes, instructions, reasoning,
tool results and recognized secrets are excluded. See
[Codex collection](CODEX-COLLECTION.md) for sources and limits.

## Upgrade

Back up the Animus SQLite database and configuration before upgrading. Keep the
existing data directory, identity and credentials. Historical collection may need
several cycles; checkpoints make subsequent cycles incremental.

Release assets include the Python wheel, Windows desktop ZIP, source-only local
recovery ZIP and `SHA256SUMS`. Obtain them from the official GitHub release and
verify their hashes. The existing peer update channel continues using authenticated
hub downloads, TLS and package checksum verification. No trust-key rotation is
required by this release.
