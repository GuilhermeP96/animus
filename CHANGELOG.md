# Changelog

All notable changes to **Animus** are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
