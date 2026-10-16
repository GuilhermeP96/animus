# Windows task binding: implicit Enabled

Issue5. A fresh, pinned SSH read on Panthro confirmed the same task owner,
interpreter/action and production node, with the task Running on Animus0.8.10.
The native updater fixture refused before creating any fixture task or venv:
Export-ScheduledTask omitted Settings/Enabled, while the runtime Enabled flag
was true. Production task/configuration/credentials were not changed.

The Windows schema makes this element optional with default true:
[Microsoft task schema](https://learn.microsoft.com/en-us/windows/win32/taskschd/taskschedulerschema-enabled-settingstype-element).
The binding now removes only this permitted temporary flag from the exported
XML before hashing. It supports implicit/explicit true and the helper's own
temporary disable without depending on the element's insertion position.
Exactly one Settings element is still required; duplicate or non-boolean
Enabled values fail closed. Interpreter, arguments, principal and every other
exported task field remain bound. ACL/identity/selector/config guards are intact.

Run `tests/security/Test-WindowsTaskBinding.ps1` on native PowerShell5.1. It tests
the actual XML/hash function with a mocked export boundary, including implicit
default, all XML boolean forms, other-field drift and invalid/duplicate XML.
This is not the real scheduled helper lifecycle or a production update. Those
remain separate gates before shipping a new wheel or lifting the0.8.10 pin.

Rollback is the prior source revision. No existing task, schema, credential,
interpreter or endpoint-security setting needs alteration for source rollback.

## Native redirected process completion

A private Windows PowerShell5.1 fixture reproduced a second issue: `Start-Process`
with redirected stdout/stderr completed `pip --version` but returned a null
`ExitCode`. The same interpreter without redirection returned0. This matches
[PowerShell issue5421](https://github.com/PowerShell/PowerShell/issues/5421).
A null result remains failure; it is never coerced to a successful zero.

The runner now owns a Diagnostics.Process from launch, drains both pipes with
concurrent bounded ReadAsync buffers, caps combined log bytes before writing,
closes stdin, and enforces monotonic execution/drain deadlines. Files are private
before launch and opened exclusively. Timeout/output failure can terminate only
the child created by this operation. No shell, RunAs, process-name kill or
unbounded `-Wait` is introduced.

`tests/security/Test-WindowsPrivateChild.ps1 -NativePython EXISTING_NATIVE_PYTHON
-Workspace PRIVATE_NATIVE_WORKSPACE` executed on Panthro PowerShell5.1: eight real
checks passed (exit0/7; both pipes131072bytes;200ms timeout;1024byte combined cap;
absent executable, actual launch failure with closed logs, and a descendant
retaining both pipes beyond the5s drain deadline). These are disposable scripts/children, not a package install
or production task update. The lifecycle fixture advanced through baseline pip
and created its private daemon task, but independent helper start/completion
remains a separate qualification gate. No native production update is claimed.

## Atomic native receipts

The independent Scheduler job entered the source-exit gate but its waiting and
blocked receipts stayed registered. Native comparison proved File.Replace with
PowerShell `$null` throws an invalid-path error; NullString.Value produces the
actual null backup argument required by .NET. The writer now passes
System.Management.Automation.Language.NullString.Value. Four native create/replace
cycles read back exact JSON, preserved protected owner ACL and left no tmp file.
See tests/security/Test-WindowsPrivateJson.ps1. Private independent-job console
files now preserve loader/runtime diagnostics without becoming success proof.

The next private lifecycle advanced through task termination and actually
installed the target package, then correctly blocked on pip check. Diagnosis
showed the fixture's system_site_packages inherited the GLOBAL base Python,
including unrelated Streamlit conflicts and PyJWT2.13, rather than the native
venv. A direct read-only production-native pip check passed with PyJWT2.15.1.
The Hub fixture therefore uses a separate venv with global/user sites disabled,
references only the protected native venv library path, and hashes native code
before/after. No production dependency has been rewritten to make the test pass.
Automatic recovery after an actual production install failure remains separate.

## Final assisted qualification / source preview

The corrected Hub fixture completed the real independent Scheduler helper on
Panthro: baseline0.8.10 to target0.8.11 inside a private venv, source task stopped,
wheel installed, pip check passed, task restarted with a new PID/creationTime and
read-back package version. Its own task was then stopped/unregistered. Production
task/config/credentials/processes and native package code remained unchanged.
This used an explicitly SHA-bound corrected runner outside the historical wheel.

Version0.8.12a1 is a SOURCE PREVIEW containing these fixes. No replacement0.8.11
wheel is published. The production server/native VPS stay0.8.11, Windows peer
production stays0.8.10, and server pin0.8.10 remains. The scheduled automatic
exit75 path, production reconnection and automatic failure recovery remain gates
before stable native promotion. This preview release does not activate them.
Rollback: retain prior source1220082 or its parents and existing authenticated
recovery artifacts; do not restore revoked credentials or overwrite live data.
