# Local independent recovery kit (2026-10-13)

The compromised shared HMAC cannot authenticate replacement-key delivery. This
source-only kit uses an owner-confirmed existing native config and a fresh local
X25519 recipient key, then an independently authenticated administrative chat
approves the public fingerprint and the canonical encrypted-envelope SHA256.
It never contacts provisioning endpoints or uses old HMAC/license as recovery trust.

Source: scripts/security/windows-local-recovery/. Build a private ZIP after
committing using `scripts/security/package-local-recovery.py --output /private/new-kit.zip`.
The ZIP includes the exact qualified credential_rotation.py, per-file hashes and
source commit. Owner must independently verify ZIP SHA256 before extraction.
No credentials, Python binaries, runtime node identities or pre-expiring packets
are embedded. Parent coordinates private GitHub release and verified SharePoint
upload; a source commit alone does not prove artifact distribution.

Prepare emits only node_id/public_key/fingerprint/rotation_id/expires_at; 1-hour
validity begins at runtime, configurable 60–3600 seconds. Private files are
owner/SYSTEM/Administrators only, ACL applied while file is empty. Existing config
and workspace parents must reject mutation grants to other principals; paths
reject symlinks/reparse points. Parent ACLs are checked, never silently rewritten.
Apply validates independent canonical digest, X25519/HKDF/AES-GCM, enrollment
recipient, identity, rotation, expiration, native model and config drift.
Only existing server_secret changes: no secure_auth JSON field or load fallback.
Exact task executable/arguments/principal/WorkingDirectory fingerprint and .env
hash must remain unchanged; observed non-1 secure auth is refused. Native client
must produce nonce authentication. Backup and protected replacement exist before
stop; replacement uses os.replace after exact task and attributed process stop.
Before restarting, authentication/.env are checked again. No revoked-key rollback.

Initial supported runtime is one directly attributed ScheduledTask Python/Animus
action. Service/wrapper/multiple-action/ambiguous-process installations fail
closed pending specific administrator qualification. Owner explicitly confirms
actual config, including runtime ANIMUS_DATA_DIR; default profile is not evidence.
Task Ready/start request never implies native process/reconnection success.
Admin must verify real peer acceptance before resolving the recovery pending item.

## VPS qualification

Run on the VPS using existing `/opt/animus-peer/bin/python`, without installation,
network, Docker, DB access or live config/credential changes:

```
/opt/animus-peer/bin/python -m pytest tests/security/test_windows_local_recovery.py -q --disable-warnings
```

18 kit tests plus 28 crypto tests passed together in 4.94 seconds: real seal/unseal and full CLI, one-bit AEAD failure,
independent digest, wrong node/rotation/recipient, expiry/window, traversal/symlink,
size limit, drift, POSIX private mode, staging without activation, only-secret
replacement, source-only ZIP manifest, real Git source-drift refusal and no CLI/validation secret disclosure. Packager reads committed blobs and refuses different worktree bytes.
Fixtures derive compatible fields from the installed older native Config outside
the source checkout and prove its load accepts the replacement without ValidationError
logging. New-source defaults include CF Access fields absent from that older model;
those are intentionally never introduced into an existing config.

Linux fixtures do not prove Windows ACL application, PowerShell runtime, task
stop/start or online reconnection. PowerShell AST and real Windows assisted smoke
remain distinct gates; do not claim native qualification before owner execution.
Private native key/config backup retention follows corporate verified offsite
receipt policy; no automatic age eviction. No secrets may enter Git/issues/email.

## Authorized authenticated SSH automation

Optional `-NonInteractive` is allowed only with explicit TaskName/TaskPath/
absolute local ConfigPath/ExpectedNodeId in both phases. It never establishes
SSH trust: Root must independently authenticate the host/key and have owner
permission. Default interactive confirmations remain. Expected node is matched
against inspected config, enrollment and persisted runtime; Apply rechecks exact
task/path/config and current node before stage/stop. Old runtime metadata lacking
node binding requires fresh preparation. Separate PowerShell pure selection
regressions: `pwsh -NoProfile -File tests/security/Test-RecoverySelection.ps1`.
PowerShell AST/tests are distinct from actual Windows ACL/task/native smoke.
