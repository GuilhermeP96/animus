# Animus 0.8.15

This immutable release distributes the MCP statistics diagnostic from PR #9.
Degraded statistics expose only an allowlisted reason and a validated retry
interval. Missing counts stay unavailable; stale counts retain their age.
SQL budgets, refresh policy and memory/configuration formats are unchanged.

The release also includes the integrated public-source security changes and
AGPL-3.0-only licensing with Guilherme Pinheiro / Datano attribution in NOTICE.
The previous 0.8.14 wheel remains a separate rollback artifact.

Upgrade acceptance requires matching the authenticated hub wheel SHA-256 to
the published asset, checking installed RECORD and source files, preserving
configuration and SQLite backups, and testing new native MCP connections.
Peer queue length alone is not evidence of daemon or authenticated hub health.
Rollout evidence and remaining host limitations are recorded separately.
