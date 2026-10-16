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
