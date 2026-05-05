# Changelog

All notable changes to **Animus** are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.4.15] — 2026-05-05

### Added
- **Four new MCP tools** so Copilot can leverage the same session/graph
  primitives that the admin UI exposes — directly on the local peer
  database, no HTTP round-trip:
  - `animus_session_list` — enumerate Copilot Chat sessions (each is a
    full conversation), filterable by workspace and minimum turn count.
  - `animus_session` — dump the full chronologically-ordered transcript
    of a session, with paging (`limit`/`offset`) and optional `role`/
    `search` filters so 10 000-turn sessions stay manageable.
  - `animus_related` — given any memory id, return its previous and
    next turn in the same session plus the closest sibling turns.
  - `animus_neural_map` — return the workspace × session graph (nodes
    + tag-bridged edges) as JSON, the same data the `/admin/graph`
    canvas renders.
- The Animus MCP active-context blurb now lists all eleven tools so the
  agent knows about session navigation from the first message.

### Notes
- All four new tools are read-only, query the local peer SQLite, and
  share the same `metadata.session` aggregation used by the hub admin
  routes — 99.8% of synced memories are reachable through them.

## [0.4.14] — 2026-05-05

### Fixed
- **Neural Map now actually renders.** v0.4.13 grouped sessions by
  `(session_id, workspace)` in SQL, so a session whose `workspace` field
  changed mid-conversation produced two rows with the same `session_id`.
  vis-network rejects duplicate node ids and threw
  `Cannot add item: item with id s:… already exists` from the constructor,
  leaving the canvas empty even though the stats line still showed
  “20 nodes · 121 edges”. Sessions are now de-duplicated server-side
  (first occurrence wins, ordered by turn count desc).
- **Fit-after-stabilization.** Outlier workspaces with 10k+ turns dwarfed
  every other node and pushed the layout off-screen. Node values are now
  capped at the 90th percentile, scaling clamps to 12–50 px, the network
  is exposed as `window.net` for debugging, and `fit({ animation })`
  fires automatically after physics stabilization.
- Navigation buttons are enabled on the graph viewport.

## [0.4.13] — 2026-05-05

### Added
- **Sessions view (`/admin/sessions`).** Reconstructs every Copilot Chat
  conversation as a single chronologically ordered transcript. Turns are
  rendered as cards with role badges (user / assistant / tool), each turn's
  Markdown is rendered with the same `marked` + `DOMPurify` pipeline as the
  detail view, and an in-page filter lets you search across the entire
  conversation or hide tool calls. Indexed by workspace; the largest session
  in production currently spans 10 236 turns and reads as one document.
- **Neural Map (`/admin/graph`).** Force-directed graph linking workspaces
  (cyan boxes) to their sessions (gold dots, sized by turn count). Sessions
  that share at least two semantic tags are connected by dashed gold edges
  — a visual signal of cross-pollination of context. Double-click a session
  node to jump straight to its transcript. Renders ~50k memories in well
  under a second on the production dataset because aggregation happens in
  SQLite via `json_extract(metadata, '$.session')`.
- **Neural connections panel on every memory detail page.** A new card in
  the right sidebar fetches `/admin/api/memories/{id}/related` and shows
  the previous and next turns of the same session plus eight nearby
  siblings — every memory becomes navigable to its conversational neighbours.
- **New JSON endpoints** for tooling: `GET /admin/api/graph` and
  `GET /admin/api/memories/{id}/related`.

### Notes
- Of 47 365 memories in production, 99.8% carry a `metadata.session`
  identifier, so the Sessions view and Neural Map cover essentially the
  entire archive without further migrations.

## [0.4.12] — 2026-05-05

### Fixed
- **Markdown rendering on the memory detail view actually works now.** The
  Subresource Integrity hashes for the `marked@12.0.2` and `dompurify@3.1.6`
  CDN scripts in v0.4.8–0.4.11 were placeholders and never matched the
  actual files — every browser refused to execute the scripts, the catch
  block kicked in, and content fell back to monospace pre-formatted text.
  Memories with tool-call markup looked like raw source code.
  - SRI hashes corrected to the real upstream digests.
  - Added an explicit `typeof marked === 'undefined'` fallback that logs to
    the console and degrades gracefully if the CDN is ever blocked.

## [0.4.11] — 2026-05-05

### Added
- **Tool calls are now captured in transcript memories.** Assistant turns
  often consist of one short sentence ("I'll create the script and run it")
  plus a tool call whose ``arguments`` field carries the actual payload
  (e.g. a ``create_file`` body). The pre-0.4.11 collector kept only the
  text and discarded the tool call entirely — producing memories that
  read like the assistant said almost nothing.
  Each tool call is now appended to the memory body as a fenced block:
  ``**🔧 Tool call: `create_file`**`` followed by the pretty-printed
  arguments. Double-encoded JSON arguments are detected and unwrapped
  before formatting.

### Changed
- Transcript content cap raised from 50 KB to 256 KB. The 50 KB ceiling
  was cutting large tool call bodies (long Python scripts, big diffs)
  mid-string, producing the unrecoverable JSON we had to migrate around
  in v0.4.9 / v0.4.10. The Memory model still enforces the 512 KB hard
  ceiling.

## [0.4.10] — 2026-05-05

### Fixed
- **Truncated transcript memories now recover too.** The pre-0.4.9 collector
  also capped each JSONL line at 50 KB, which meant assistant messages
  containing large tool arguments (e.g. a `create_file` call with a long
  script body) were stored as *invalid* JSON — the unwrap migration in
  v0.4.9 silently skipped them. The migration now falls back to a regex
  extraction of the first `"content": "…"` field when `json.loads` fails,
  recovering the human-readable body and discarding the truncated tool
  payload tail.

## [0.4.9] — 2026-05-05

### Fixed
- **Transcript memories no longer arrive as raw JSON.** The Copilot
  collector probed `data.get("content")` at the top level of each JSONL
  line, but VS Code's transcript format wraps the message inside
  `{"type": ..., "data": {"content": ...}}`. Every row missed the probe
  and fell back to writing the *raw* JSON line as the memory body, which
  is what produced the heavily-escaped backslash-soup in the admin UI.
  - Collector now traverses both shapes and supports list-of-parts
    payloads (`[{type:"text", text:"..."}, ...]`).
  - Envelope-only events (`session.start`, `session.end`, `ping` with no
    body) are skipped instead of being stored as noise.
  - Hub lifespan startup runs a one-shot migration that detects rows
    where `content` is a JSON envelope and rewrites them in place with
    the unwrapped message text. Idempotent.

### Added
- **Defensive smart-unescape in the memory detail view.** Even after
  the migration, individual records can arrive double-escaped from
  external peers running an older collector. The detail page now detects
  literal `\\n`, `\\"`, `\\\\` sequences and runs them through `JSON.parse`
  before handing the text to the Markdown renderer. The Raw view also
  shows the cleaned text so copy-paste yields readable content.

## [0.4.8] — 2026-05-05

### Added
- **Markdown rendering in the memory detail view.** The admin UI now renders
  the `content` field with `marked.js` (GFM, line-break-as-`<br>`) sanitized
  by `DOMPurify`. A "Raw" toggle keeps the original monospace pre-formatted
  view a click away. Code blocks, headings, lists, blockquotes, tables and
  inline code now display with proper formatting and preserved line breaks.
- Search-result preview now uses `white-space: pre-wrap`, so line breaks in
  the first 300 chars no longer collapse to a single line.

### Fixed
- **Hub no longer reports every memory as `Pending`.** The `synced` flag was
  defaulting to `0` even on the hub, where there is no upstream to push to.
  - `IndexEngine.index_memory(..., synced=False)` and
    `index_batch(..., synced=False)` now accept an explicit flag.
  - The hub's `/api/sync/push` ingest path passes `synced=True`.
  - Lifespan startup runs a one-shot backfill
    (`UPDATE memories SET synced = 1 WHERE synced = 0`) so the existing
    archive is corrected on first boot of 0.4.8.
  - Peer behaviour is unchanged — `synced` still defaults to `0` for locally
    collected memories until they are pushed.



### Fixed
- **`AnimusConfig.load(path)` no longer clobbers `~/.animus/config.json`.**
  When `load()` was called with an explicit path that didn't exist,
  the auto-generated `node_id` fallback was being persisted to
  `cfg.config_path` (the *default* path), not to the path the
  caller asked for. The test `test_load_generates_node_id` was
  silently wiping the live peer's `node_id`, `hub_url`, and
  `server_secret` on every `pytest` run. Auto-save now only fires
  when `load()` was called without an explicit path.
- New regression test
  `test_load_with_explicit_path_does_not_touch_home_config`
  asserts that `load(some_tmp_path)` never writes under
  `Path.home() / .animus`.

### Internal
- 250 tests passing.

## [0.4.6] — 2026-05-05

### Security
- **Body-bound HMAC.** Request bodies are now hashed (SHA-256) and
  the digest is part of the signed payload. A proxy or middlebox
  that swaps `memories[]` while keeping a stolen header is now
  rejected with HTTP 401. The optional `X-Animus-Body-SHA256`
  header lets the server reject mismatches before signature
  verification even runs.
- **Replay protection (nonce cache).** Every signed request now
  carries `X-Animus-Nonce` (16 random bytes hex). The hub remembers
  recently-seen `(node_id, nonce)` pairs for the duration of the
  freshness window and rejects duplicates with 401. Bounded LRU at
  100k entries. Set `ANIMUS_REQUIRE_NONCE=1` once all peers are on
  0.4.6+ to make the nonce mandatory.
- **WebSocket handshake signed with HMAC.** `/ws/sync` no longer
  accepts a bearer token equal to the shared secret on the wire.
  The handshake message itself is the signed body, with the same
  `node_id|node_name|timestamp|nonce` payload format. Comparison is
  constant-time (closes a timing-attack vector on the previous `!=`
  check).
- **WebSocket Origin allowlist.** `ANIMUS_WS_ALLOWED_ORIGINS`
  controls which browser Origins may open `/ws/sync`. Empty
  allowlist means "native clients only" (no Origin header). `*`
  disables the check (dev only). Browsers from rogue tabs can no
  longer drift onto a configured hub.
- **Admin panel fails closed.** The legacy default of
  `admin/admin` + `animus-default-secret-change-me` no longer
  authenticates. The panel refuses logins unless
  `ANIMUS_ADMIN_PASSWORD` AND a session secret
  (`ANIMUS_ADMIN_SECRET` or `ANIMUS_SERVER_SECRET`) are both set.
  `ANIMUS_ADMIN_INSECURE=1` re-enables the old behaviour for
  local-dev only.

### Changed
- `create_auth_header(secret, node_id)` gained an optional `body=`
  parameter. The peer client now signs every POST body it sends to
  the hub.
- `verify_auth_header(secret, headers)` gained `body=` and
  `require_nonce=` parameters and a small thread-safe replay
  cache (`_replay_cache`).
- `SyncProtocol.handshake(...)` accepts `shared_secret=` and emits
  a signed handshake when set.

### Internal
- 13 new tests in `tests/test_crypto.py` (nonce uniqueness, replay
  rejection within window, body hash determinism, tamper
  detection, body-hash header mismatch, empty-body round-trip).
- 5 new HTTP integration tests in `tests/test_server.py`
  (`TestSecureAuth`) hitting `/api/sync/pull` with `TestClient`:
  unsigned -> 401, signed -> 200, tampered body -> 401, replay ->
  401, wrong secret -> 401.
- New `tests/test_admin_auth.py` (5 tests) verifying fail-closed
  defaults and the explicit `ANIMUS_ADMIN_INSECURE` bypass.
- 249 tests passing (was 229).

### Migration notes
- Peers running 0.4.5 keep working unchanged: the verifier accepts
  requests without nonce/body-hash for backwards compatibility.
  Once your fleet is fully on 0.4.6, set `ANIMUS_REQUIRE_NONCE=1`
  on the hub to harden the freshness check.
- If you exposed the admin panel with the legacy default
  credentials and have not set `ANIMUS_ADMIN_PASSWORD`, the panel
  will reject all logins after upgrade. Set the env vars on the
  hub before deploying 0.4.6.

## [0.4.5] — 2026-05-04

### Fixed
- **Windows AppX virtualization trap.** When Animus runs under the
  Microsoft Store Python (`PythonSoftwareFoundation.Python.*`), every
  write under `%APPDATA%` and `%LOCALAPPDATA%` is silently redirected
  to the package's `LocalCache\Roaming\…`. The daemon worked, but
  `Test-Path "$env:APPDATA\animus\config.json"` returned `False`,
  `animus config-set` appeared to no-op, and the data directory
  forked between PowerShell's view and the running peer's view —
  producing identity drift on reinstall.

### Changed
- **`data_dir` default on Windows is now `%USERPROFILE%\.animus\`.**
  The user profile root is not subject to AppX redirection, so the
  daemon, the CLI, the MCP server, and PowerShell all see the same
  files regardless of which Python launched the process.
- **One-shot migration on first load.** `AnimusConfig.load()` detects
  legacy data directories (`%APPDATA%\animus\` and the AppX-virtualized
  `…\Packages\PythonSoftwareFoundation.Python.*\LocalCache\Roaming\animus\`)
  and copies them into the new home before continuing. The migrated
  `config.json` has its `data_dir` field rewritten to point at the
  new location so a stale absolute path can't pull the daemon back
  into the trap. Idempotent: existing destination files are never
  overwritten.

### Internal
- New helpers `_legacy_data_dirs()` and `_migrate_legacy_data_dir()`
  in `animus/config.py` with 6 dedicated tests in `tests/test_config.py`
  (default-home path, legacy candidate enumeration including AppX
  glob, idempotent copy, post-migration `data_dir` rewrite, end-to-end
  `load()` migration).

## [0.4.4] — 2026-05-04

### Added
- **`animus service` command group** — cross-platform installer for the
  daemon. Wraps Scheduled Task on Windows, `systemctl --user` on Linux,
  and `launchctl` on macOS behind the same surface:
  - `animus service install` — register and start the daemon
  - `animus service status` — show installed/running state
  - `animus service start` / `stop` — control without touching the OS
  - `animus service uninstall` — remove the unit
  - `animus service logs --tail N --follow` — tail the daemon log
  No more "is the peer actually running?" mystery — the answer is now one
  command away.
- **Daemon log redirection.** `animus daemon --log-file <path>` switches
  from stdout to a `RotatingFileHandler` (5 MB × 5 backups, UTF-8). The
  service installer wires this automatically so headless peers always
  leave a trail at `<data_dir>/daemon.log`.
- New module `animus/service.py` with platform-agnostic `install`,
  `uninstall`, `status`, `start`, `stop`, plus a `ServiceInfo`
  dataclass. Designed to be unit-testable: every backend goes through
  `subprocess.run`, so the tests inject fakes instead of touching the
  host's real service manager.

### Changed
- `_setup_logging(verbose, log_file=None)` now accepts an optional
  `log_file` and forces a clean handler set (`force=True`), so callers
  swapping between console and file logging in the same process don't
  leak stale handlers.
- The `daemon` command emits its banner via the logger (so it lands in
  the log file) instead of `console.print`, which is invisible under a
  service supervisor.

### Internal
- 19 new tests in `tests/test_service.py` covering `detect_platform`,
  unsupported-OS fallbacks, the systemd unit/state lifecycle, and the
  Windows PowerShell call surface (mocked).
- Suite: **210 passing** locally on Windows + Python 3.13.

## [0.4.3] — 2026-05-03

### Fixed
- **`animus_recall` returned "No relevant memories found" even with hundreds
  of indexed memories.** `IndexEngine.search` used to wrap the user's query
  in double quotes and feed it to FTS5 as a phrase match, which required
  every word to appear contiguously and in order. RAG-decomposed contexts
  (multi-word strings like *"animus peer installer kit"*) therefore matched
  zero rows, and `RAGEngine.contextual_recall` had nothing to return. The
  query is now normalized into a safe FTS5 expression: metacharacters
  stripped, stopwords removed, single tokens become prefix matches
  (`token*`), and multi-token queries are OR-joined so BM25 ranks the rows
  hitting the most terms first. **Recall now actually works.**
- **`animus_search` failed on natural language queries** for the same
  reason — single-word queries worked, but anything like
  `"docker compose deploy"` returned an empty list. Same fix applies.
- **`animus_timeline --hours N` reported "No memories" right after a fresh
  `animus_collect`.** The collector imports Copilot chat logs whose original
  `timestamp` is the chat date (often days/weeks old), but the index only
  just received them. The timeline now (a) accepts a new `by_indexed`
  argument that filters on `created_at` (when the row landed in the local
  DB), and (b) automatically falls back to `created_at` when filtering on
  `timestamp` returns nothing — so post-collect recall just works.

### Added
- New `IndexEngine._build_fts_query` helper, isolated and unit-tested
  (7 new test cases in `tests/test_engine.py`).
- `by_indexed` parameter on the `animus_timeline` MCP tool, surfaced in the
  tool's input schema for the client.

### Internal
- Suite: **191 passing** (test_e2e/test_server skipped due to a pre-existing
  unrelated `jinja2` import in the dev env).

## [0.4.2] — 2026-05-03

### Documentation
- **`hub_url` must be reachable from where the peer runs.** README and
  `installer_kit/COPILOT.md` now warn that a Docker bridge IP (`172.x`,
  `10.x`) is **not** a valid `hub_url` for peers running on the host or on
  another machine — use the public HTTPS URL (e.g.
  `https://animus.datano.com.br`). Docker bridge IPs also change across
  `docker restart`, so even an in-network peer should prefer the service
  name (`http://animus:8314`) over a hard-coded IP.
- README's *Instalação → Peer* section gained an **"After install"**
  subsection covering daemon control commands and how to switch `hub_url`.

## [0.4.1] — 2026-05-03

### Fixed
- **`SyncProtocol.memories_from_push` rejected every pulled memory.** Hub-side
  rows store `metadata` and `tags` as JSON-encoded strings (SQLite has no
  native dict/list type); the client used to pass those raw strings into
  `Memory(...)` and got `dict_type` / `list_type` validation errors on every
  record, so `pull_from_hub` always indexed 0 new memories and the logs were
  flooded with `Skipping malformed memory` warnings. The method now decodes
  `metadata` and `tags` transparently before constructing the model, also
  treating `None` and empty strings as the model's defaults. Verified
  end-to-end against `https://animus.datano.com.br`: 200 pulled / 0 skipped
  (was 0 indexed / 200 skipped before).
- **Windows console crash on `cp1252`.** Any Rich-formatted CLI command
  (`animus --help`, `animus init`, …) raised
  `UnicodeEncodeError: 'charmap' codec can't encode character '\U0001f985'`
  unless the user manually exported `PYTHONUTF8=1`. The CLI now reconfigures
  `sys.stdout`/`sys.stderr` to UTF-8 on `win32` at import time, so the kit's
  PowerShell/`.bat` wrappers and a vanilla `cmd.exe` Just Work.

### Added
- 4 regression tests in `tests/test_sync.py` covering the
  `metadata`/`tags` JSON-string round-trip and `None` / empty fallbacks.

### Internal
- Full test suite: **191 passing** locally on Windows + Python 3.13.

## [0.4.0] — 2026-05-03

Self-contained peer installer kit (admin UI "Recruit a New Assassin" + ZIP
generator at `animus/server/installer_kit/`, plus
`scripts/install-peer.{sh,ps1,bat}`).

## [0.3.0]

Admin web UI, permissive pull, collector enhancements.

## [0.2.0]

Security hardening, test suite expansion & quality improvements.

## [0.1.0]

Initial release — Animus: Copilot Memory Synchronization Network.
