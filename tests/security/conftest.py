"""Native fixture ownership; production credentials and ACLs are never touched."""
import base64
import json
import os
from pathlib import Path
import subprocess

import pytest


def native_shell_environment():
    return {key: value for key, value in os.environ.items()
            if key.casefold() != 'psmodulepath'}


def powershell_json(source):
    encoded = base64.b64encode(source.encode('utf-16-le')).decode('ascii')
    result = subprocess.run(
        ['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy',
         'RemoteSigned', '-EncodedCommand', encoded],
        capture_output=True, text=True, encoding='utf-8', timeout=30,
        env=native_shell_environment(),
    )
    assert result.returncode == 0, 'Owned fixture ACL inspection failed'
    return json.loads(result.stdout)


@pytest.fixture(scope='session')
def windows_owner_sid():
    if os.name != 'nt':
        return None
    return powershell_json(
        '[Security.Principal.WindowsIdentity]::GetCurrent().User.Value | ConvertTo-Json'
    )


@pytest.fixture
def private_recovery_owner(tmp_path, windows_owner_sid):
    if windows_owner_sid:
        helper = Path(__file__).parent.parent.parent / 'scripts/security/windows-local-recovery/Protect-PrivateState.ps1'
        subprocess.run(
            ['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy',
             'RemoteSigned', '-File', str(helper), '-LiteralPath', str(tmp_path),
             '-OwnerSid', windows_owner_sid, '-Directory'],
            check=True, capture_output=True, timeout=30,
            env=native_shell_environment(),
        )
    return windows_owner_sid


@pytest.fixture
def assert_owner_private(windows_owner_sid):
    def check(path, directory=False):
        if os.name != 'nt':
            assert path.stat().st_mode & 0o777 == (0o700 if directory else 0o600)
            return
        literal = str(path).replace("'", "''")
        acl = powershell_json(
            "$a=Get-Acl -LiteralPath '" + literal + "';"
            "@{owner=$a.GetOwner([Security.Principal.SecurityIdentifier]).Value;"
            "protected=$a.AreAccessRulesProtected;rules=@($a.Access | ForEach-Object {"
            "@{sid=$_.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value;"
            "inherited=$_.IsInherited;allow=($_.AccessControlType -eq 'Allow');"
            "full=($_.FileSystemRights -eq [Security.AccessControl.FileSystemRights]::FullControl)}"
            "})} | ConvertTo-Json -Depth 4"
        )
        assert acl['owner'] == windows_owner_sid and acl['protected']
        assert {r['sid'] for r in acl['rules']} == {windows_owner_sid, 'S-1-5-18', 'S-1-5-32-544'}
        assert all(r['allow'] and r['full'] and not r['inherited'] for r in acl['rules'])
    return check
