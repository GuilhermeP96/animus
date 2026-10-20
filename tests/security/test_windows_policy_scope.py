from pathlib import Path


def test_native_helpers_use_process_local_policy_and_no_audit_acl_write():
    root = Path(__file__).resolve().parents[2]
    runner = (root/'animus/network/windows-update-task.ps1').read_text()
    stage = (root/'animus/network/windows_update.py').read_text()
    recovery = (root/'scripts/security/windows-local-recovery/recover_peer.py').read_text()
    acl = (root/'scripts/security/windows-local-recovery/Protect-PrivateState.ps1').read_text()
    assert "'-ExecutionPolicy','RemoteSigned'" in stage
    assert "'-ExecutionPolicy', 'RemoteSigned'" in recovery
    assert '-ExecutionPolicy RemoteSigned -EncodedCommand' in runner
    assert '[IO.Directory]::SetAccessControl' in acl and '[IO.File]::SetAccessControl' in acl
    assert 'Set-ExecutionPolicy' not in stage+runner+recovery+acl
    assert 'Bypass' not in stage+runner+recovery+acl
