# Changelog

All notable changes to **Animus** are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
