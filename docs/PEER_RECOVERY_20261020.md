# Peer recovery and governed feedback — 2026-10-20

The HP peer was installed as0.8.9, not present in the current per-node registry,
and stopped after its old detached updater exited75. Queue size zero did not
prove authentication or collection. Never reinstate the retired shared secret.
Use the independently authenticated local recovery kit to provision that exact
node, preserving all other registry entries and private backups. A file-mounted
registry must be remounted by the targeted container recreation after atomic
replacement; replacing the host inode alone does not refresh an existing bind.

Native update fixes retain the scheduled independent helper and exact
task/config/wheel/PID binding. Reviewed local scripts use process-local
RemoteSigned, respecting machine/group policy; no machine-wide policy change.
ACL persistence writes only owner/DACL sections, avoiding the extra SACL
privilege requested by Set-Acl. Helper logon type is inherited from the native
Interactive/S4U task; unsupported credential-based types remain refused.
Install the native daemon under an owner-private writable runtime, independent
of the active MCP console launcher. Do not kill a chat/client to update a peer.

Codex collection is separately opt-in: collect_codex_chat=true AND an explicit
codex_allowed_workspaces list. It reads only user and final-answer messages,
not developer/system instructions, reasoning, tools, images or usage records.
Recognized secrets and context envelopes are excluded. The current bounded
window is seven days by file modification, at most20 files/64MiB per cycle,
1MiB per record and40 retained messages per session. Incomplete appends are
tolerated. This is recent context recovery, not a complete history archive;
bounded secret pattern checks cannot guarantee detection of every secret.
Source paths use codex:// identifiers, stable IDs prevent duplicate indexing.

collect_obsidian plus an explicit vault config enables note indexing.
obsidian_auto_export_candidates is another independent opt-in, disabled by
default. The daemon exports at most20 recent eligible Codex messages per cycle
into managed .animus/exported only, with audit and idempotent retries. Failures
do not block hub sync. Existing human notes are not overwritten. Candidates are
not automatically verified or approved for training. Verify facts against sources
before promoting knowledge; regenerate the catalog and validate search afterward.

Production acceptance must separately prove public authenticated push/pull and
package download, exact hash/version, native helper waiting/completed receipts,
new daemon PID/creationTime, preserved config/database and actual sync. HTTP
health, a task-start request, unit tests and MCP stats are not substitutes.
Changing the VPS image only updates the advertised package when the explicit
ANIMUS_PIN_VERSION matches that image; clear/reconcile an older operational pin.

Rollback keeps previous images, package artifacts, task/config snapshots and
SQLite backups. Never restore revoked credentials or delete private recovery
material as part of this rollout. A stopped old daemon needs a supervised initial
bootstrap; do not claim it updated itself from a broken prior updater.
