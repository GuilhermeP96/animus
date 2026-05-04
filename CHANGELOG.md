# Changelog

All notable changes to **Animus** are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
