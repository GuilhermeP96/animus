# MCP statistics diagnostic — review candidate, 2026-10-26

Delivery update, 2026-11-01: this historical source-only status is superseded
by [the 0.8.15 rollout and native MCP acceptance](ROLLOUT_0.8.15_20261101.md).
The original 0.8.14 artifact was preserved; it was not overwritten.

Tracking: [issue #8](https://github.com/GuilhermeP96/animus/issues/8).
The installed 0.8.14 MCP returns `Statistics: unavailable` without the engine's
safe reason or retry interval. A single bounded native read using the configured
MCP database returned `query_timeout` in 2038 ms, with `SELECT 1` successful and
no writer connection opened. This diagnoses that invocation, not every earlier
MCP response. Production query limits and database/indexes remain unchanged.

The candidate adds `Reason` and `Retry after seconds` only when statistics carry
a reason or are degraded. Only the known engine codes are rendered:
`query_timeout`, `database_busy`, `database_unavailable`, `refresh_busy`,
`index_changed`, `ttl_expired`. Unknown reasons and invalid retry values render
`unknown`; exception text, SQL and paths must not cross this boundary. Fresh
responses remain unchanged, and stale counts retain their age and value.
The interval is diagnostic information, not an instruction to retry or a new
scheduler. Missing counts remain unavailable rather than becoming zero.

Regression: the focused group had eight failures and one pass before the patch;
nine pass afterward. Two cases use actual SQLite interruption in an isolated
database (cold and stale), not a mocked SQLite exception. Other fixtures cover
known codes and rejection of private diagnostic text. Reproduce on the VPS:

```bash
PYTHONDONTWRITEBYTECODE=1 /opt/animus-peer/bin/python -m pytest -q -p no:cacheprovider tests/test_mcp.py tests/test_mcp_federated.py tests/security/test_bounded_stats.py
ANIMUS_TEST_PYTHON=/opt/animus-peer/bin/python bash scripts/ci/validate.sh
```

## Source, distribution and rollback

Canonical repo is `GuilhermeP96/animus`, installed source baseline a9acbaf on
`licensing-managment`. Reused the existing detached source-only worktree
`/home/repo/animus-peer-recovery-git-20261020`, same common Git directory, with no
other process using that cwd, and created review branch
`fix/mcp-stats-diagnostic-20261026`. No clone/worktree or runtime branch was changed.
Owner: agent. Keep the branch remotely recoverable until integration/distribution
is resolved; do not automatically remove the worktree.

Source `animus/mcp/__init__.py` feeds the existing wheel packaging and all MCP
consumers. This change is not an installed replacement wheel: project version
0.8.14 is still the base version in an unreleased branch. Do not rebuild or
publish a different artifact under the immutable 0.8.14 identity. The existing
release pipeline must select its next version, preserve previous artifacts,
validate the distributed hash/provenance and qualify a new consumer connection
before claiming delivery. No changes to signing trust, entitlement or channels.

Current production remains installed wheel 0.8.14, hash
`c417708a5da16dd4417fc1840f883ac3072d4a6a222179b97b114b9eab0995bf`.
No peer restart, package installation, memory collection/export, migration,
credential rotation or Academy artifact change occurred. The timeout itself
remains a separate unresolved diagnostic/performance question within #8.
Rollback for this review state is to withhold integration or revert the candidate
commit in a versioned branch. Active data/package rollback is unnecessary because
they were not modified. Native Windows/server/package-consumer acceptance remains
pending; unit and local protocol tests cannot stand in for it.
