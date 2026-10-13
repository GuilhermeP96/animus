# Windows native update completion — source fix

Real Panthro recovery proved new credential/config binding, then observed an
older native daemon exit75 and remain Ready/no daemon despite RestartCount999.
No helper process/log was found. Task JobObject termination of the detached
helper is a hypothesis, not an established cause. Source now avoids depending
on a child that survives its originating task's termination.

A new independently registered current-user ScheduledTask performs the update.
The original daemon remains alive until helper task registration/action/principal
is verified AND that helper is actually Running with a private waiting receipt.
Only then Stage returns true and the caller exits75. There is no detached Popen,
no wildcard animus*.exe/taskkill and no borrow from Codex/client interpreters.
Windows Git fallback is refused: require the exact authenticated local Hub wheel.

Registration binds the existing direct native task/current-user SID, native
Python and daemon PID/creationTime, unchanged task XML (only the transient
Settings.Enabled toggle is normalized), config SHA/node, wheel SHA/exact ZIP
Name+Version, runner SHA and15minute deadline. Source package includes its own
PowerShell runner; before pip changes package files, a source-bound runner/plan
are copied to a private job directory with owner/SYSTEM/Administrators ACL.
HTTP package redirects are refused so peer/CF headers cannot be forwarded to
another origin. Download logging says hash-verified, not cryptographically signed.

The helper waits bounded for its bound original process, then temporarily
disables and stops ONLY the unchanged original task to prevent self-restart
while installing. It refuses any remaining matching daemon; does not kill other
applications/MCPs. Pip is the exact existing native interpreter, local wheel,
--no-index/--no-deps,600s cap and private output; only that child can be killed
on timeout. Existing config hash/node must remain unchanged after install.
Package-version validation and a bounded real pip check precede re-enabling/start of the original task. A blocked receipt separately preserves installed=true when version was verified but restart remains unproven.
Actual Running state plus exactly one newly created matching native process,
PID/creationTime and3second survival are required before completed receipt.
Start request alone is not restart_verified. Server reconnection remains false
until separately observed through the real Hub.

Receipts move registered→waiting_bound_source_exit→installing→completed or
blocked with constant gate/owner=agent. Failure preserves private evidence and
fresh credentials; a temporarily disabled original task requires agent-owned
reconciliation, never fallback to a revoked secret. Other unrelated processes
remain untouched even if they lock a console launcher and cause pip failure.
Dependencies are intentionally not fetched: pip check/version compatibility and
native smoke are qualification gates; unsupported runtime/task/principal fails
closed before daemon exit. This automated path targets the daemon's registered
own task; a standalone CLI process is not falsely attributed to the daemon.

## Qualification

Real local ZIP metadata/config fixtures and existing updater regressions exercise
wheel version/hash/path/node binding and refusal behavior. Pure PowerShell gate
regressions: `pwsh -NoProfile -File tests/security/Test-WindowsUpdateEvidence.ps1`.
Root must run AST/pure gates in the existing builder, then actual Windows5.1
assisted task registration/update/restart/receipts (including failure/timeouts)
before activating this source. Linux fixtures do not simulate Scheduler or
prove a native restart. No task/pip/native app was executed by source tests.

After verified corporate SharePoint upload/listing/size/streamed SHA receipt,
Root may remove only unchanged local payload; receipts/jobs/logs are not deleted
by age. No installer/client reinstall, active key rotation or e-mail is part of
this source delivery. Source/package/branch synchronization remains required.
