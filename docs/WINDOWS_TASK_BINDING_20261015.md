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
