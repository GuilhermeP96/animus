# Windows suite and local peer qualification

Date: 2026-11-10. The checks use the available Windows host, not a clean
installation or a reboot qualification. Infrastructure addresses, private
configuration and memory contents are excluded from this report.

## Corrections

- Recovery ACLs verify that the selected path already belongs to the approved
  owner, then change only the DACL. Rewriting an unchanged owner unnecessarily
  required WRITE_OWNER. The helper still rejects reparse paths and unexpected
  owners, removes inherited grants, verifies its explicit allowlist and leaves
  audit policy unchanged.
- A Python process started by PowerShell 7 can inherit an incompatible
  PSModulePath when it launches Windows PowerShell 5.1. Recovery child processes
  now discover their native modules using a process-local environment. Global
  profiles, execution policy and the parent environment remain unchanged.
  This follows [Microsoft's guidance for intermediate Python processes](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_psmodulepath?view=powershell-7.6#starting-windows-powershell-from-powershell-7).
- Recovery fixtures pass the actual Windows SID and verify owner/DACL grants
  using the native shell. POSIX service ownership, administrative registry
  generation and Linux hub registry filesystem checks retain their Linux
  coverage; Windows does not pretend that chmod bits prove ACL protection.
  Protocol rejection cases use isolated copies of a protected synthetic
  enrollment created by the real helper. The `native_recovery` cases perform
  fresh enrollment, native ACL verification and CLI operations end-to-end.
- The source recovery packager accepts Git's LF/CRLF checkout transformation
  while packaging only committed bytes. Content drift is still rejected.
- SQLite's per-lock busy timeout is distinct from the whole query budget.
  The exclusive-lock regression checks the actual two-second query budget,
  the typed failure and truthful unavailable counts; production timeouts and
  database behavior are unchanged.
  [SQLite documents the busy handler as accumulated sleep per lock wait](https://www.sqlite.org/draft/c3ref/busy_timeout.html).
- The suite validator isolates HOME, Windows profile/provider directories,
  UTF-8 pipes and an explicit fixture directory. Windows has a 900-second
  suite budget for native shell verification; Linux retains 150 seconds.
  Fixture isolation does not qualify as a clean-machine installation.

Run the complete suite with the project's prepared test interpreter:

```powershell
.\.venv\Scripts\python.exe scripts\ci\validate.py
```

Linux continues to use the registered offline VPS validator. No hosted Actions
or additional scheduled tasks are needed for this correction.

## Qualification results

The initial Windows run reproduced 11 failures and 23 setup errors. Focused
native recovery and CLI tests subsequently passed, including encrypted staging,
activation on synthetic configuration, preservation of other fields, actual
private ACL verification and compatibility with the existing installed model.
An unexpected-owner check also failed closed without changing owner or DACL.

Both complete suites qualified code commit
`d34141624b378e117da9b3e607c6b26b0c779353`:

| Environment | Passed | Skipped | Subtests passed |
| --- | ---: | ---: | ---: |
| Windows, Python 3.13, offline validator | 442 | 23 | 15 |
| Linux, registered VPS CI | 460 | 5 | 15 |

The Windows run exited successfully in 337.14 seconds with no failures or
setup errors. Its skips cover 16 POSIX-only cases, two file-symlink checks
requiring a privilege unavailable to the account, and five opt-in VPS
diagnostics. Linux retains the POSIX and symlink coverage; its five skips are
the opt-in diagnostics. There was no elevation or Developer Mode change.

The source-only recovery ZIP was also built on Windows from committed source
and read back: all six payload files matched their manifest hashes.

## Existing local peer

The installed peer is 0.9.2. Its RECORD, all 60 application files and dependency
consistency were verified against the qualified release wheel. The configured
MCP consumer exposed 16 tools and fresh statistics. Authenticated HTTP returned
200; replay and unknown-node requests were rejected with 401.

Process attribution checks the scheduled pythonw launcher, its actual Store
Python child, current owner and fresh private heartbeat. The background desktop
matches the qualified 0.9.2 executable hash. Data/configuration comparisons use
a consistent private checkpoint. The final comparison found zero missing
memories, zero altered payloads and unchanged tag membership. Configuration
bytes matched the checkpoint, and the final SQLite pending-sync count was zero.

The corrections are in test and recovery tooling. The qualified 0.9.2 peer
runtime and its running desktop remain in service with their verified bytes.
