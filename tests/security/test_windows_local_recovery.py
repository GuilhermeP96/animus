"""Real offline crypto, config preservation and disclosure regression fixtures."""
import base64
import importlib.util
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time

import pytest
from animus.config import AnimusConfig

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / 'scripts/security/windows-local-recovery/recover_peer.py'
spec = importlib.util.spec_from_file_location('local_recovery', HELPER)
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)

@pytest.fixture
def prepared(tmp_path):
    env = {k:v for k,v in os.environ.items() if k != 'PYTHONPATH' and not k.startswith('ANIMUS_')}
    old = 'old-fixture-' + secrets.token_urlsafe(32)
    script = 'from animus.config import AnimusConfig; import sys; print(AnimusConfig(_env_file=None,node_id="fixture-native-peer",node_name="Fixture",server_secret=sys.argv[1],data_dir=sys.argv[2]).model_dump_json())'
    fixture = subprocess.run([sys.executable,'-c',script,old,str(tmp_path / 'data')],cwd=tmp_path,
                             env=env,capture_output=True,text=True,timeout=10)
    assert fixture.returncode == 0
    data = json.loads(fixture.stdout)
    config = tmp_path / 'config.json'
    config.write_text(json.dumps(data))
    work = tmp_path / 'private'
    public = r.prepare(config, work)
    fresh = secrets.token_urlsafe(48)
    envelope = r.rotation.seal(public['node_id'], fresh, base64.b64decode(public['public_key']),
        public['fingerprint'], public['rotation_id'], public['expires_at'])
    packet = tmp_path / 'envelope.json'
    packet.write_text(json.dumps(envelope))
    return config, work, public, fresh, envelope, packet, data


def test_real_rotation_preserves_native_config_and_private_modes(prepared, caplog):
    config, work, public, fresh, envelope, packet, original = prepared
    assert set(public) == {'node_id','public_key','fingerprint','rotation_id','expires_at'}
    assert work.stat().st_mode & 0o777 == 0o700
    assert (work / 'recipient.key').stat().st_mode & 0o777 == 0o600
    r.stage(work, packet, r.rotation.envelope_digest(envelope))
    assert json.loads(config.read_text()) == original  # staging has no activation
    r.commit(work)
    actual = json.loads(config.read_text())
    assert actual == {**original, 'server_secret': fresh}
    assert 'secure_auth' not in actual
    assert config.stat().st_mode & 0o777 == 0o600
    loaded = AnimusConfig.load(config)
    assert loaded.server_secret == fresh and loaded.node_id == original['node_id']
    assert not caplog.records
    # Outside repository cwd/PYTHONPATH: installed old native model, not source model.
    script = 'from animus.config import AnimusConfig; import sys; from pathlib import Path; c=AnimusConfig.load(Path(sys.argv[1])); assert c.node_id=="fixture-native-peer"; assert "secure_auth" not in c.model_fields; print("old-native-load-ok")'
    env = {k:v for k,v in os.environ.items() if k != 'PYTHONPATH' and not k.startswith('ANIMUS_')}
    result = subprocess.run([sys.executable,'-c',script,str(config)],cwd=work,env=env,capture_output=True,text=True,timeout=10)
    assert result.returncode == 0 and result.stdout.strip() == 'old-native-load-ok'
    assert fresh not in result.stdout + result.stderr and 'Config validation errors' not in result.stderr
    assert json.loads((work / 'applied.json').read_text())['old_secret_rollback_allowed'] is False

@pytest.mark.parametrize('change',['digest','node','rotation','recipient','bit','expired','enrollment_expired','beyond_enrollment'])
def test_reject_altered_or_expired_envelopes(prepared, change):
    config, work, public, fresh, envelope, packet, original = prepared
    expected = r.rotation.envelope_digest(envelope)
    if change == 'digest': expected = '0' * 64
    elif change == 'node': envelope['node_id'] = 'another-peer'
    elif change == 'rotation': envelope['rotation_id'] = 'another-rotation'
    elif change == 'recipient': envelope['recipient_sha256'] = 'f' * 64
    elif change == 'expired': envelope['expires_at'] = int(time.time()) - 1
    elif change == 'beyond_enrollment': envelope['expires_at'] += 1
    elif change == 'bit':
        value = bytearray(base64.b64decode(envelope['ciphertext'])); value[0] ^= 1
        envelope['ciphertext'] = base64.b64encode(value).decode()
    elif change == 'enrollment_expired':
        state = json.loads((work / 'state.json').read_text()); state['expires_at'] = int(time.time()) - 1
        (work / 'state.json').write_text(json.dumps(state))
    if change not in {'digest','enrollment_expired'}: expected = r.rotation.envelope_digest(envelope)
    packet.write_text(json.dumps(envelope))
    with pytest.raises(r.RecoveryError): r.stage(work, packet, expected)
    assert json.loads(config.read_text()) == original

@pytest.mark.parametrize('change',['config_drift','temp_drift','traversal','stage_expired'])
def test_commit_refuses_drift_and_path_escape(prepared, change):
    config, work, public, fresh, envelope, packet, original = prepared
    r.stage(work, packet, r.rotation.envelope_digest(envelope))
    staged_path = work / 'staged.json'; staged = json.loads(staged_path.read_text())
    if change == 'config_drift':
        original['node_name'] = 'Changed'; config.write_text(json.dumps(original))
    elif change == 'temp_drift': Path(staged['candidate_path']).write_text('{}')
    elif change == 'traversal': staged['candidate_path'] = str(work / '.animus-recovery-evil.tmp')
    else: staged['expires_at'] = 0
    staged_path.write_text(json.dumps(staged))
    with pytest.raises((r.RecoveryError, FileNotFoundError)): r.commit(work)
    assert json.loads(config.read_text()) == original


def test_symlinks_and_size_bounds(prepared, tmp_path):
    config, work, _, _, envelope, packet, _ = prepared
    link = tmp_path / 'linked'; link.symlink_to(config)
    with pytest.raises(r.RecoveryError): r.config(link)
    packet.write_bytes(b' ' * (r.MAX_JSON + 1))
    with pytest.raises(r.RecoveryError): r.stage(work, packet, r.rotation.envelope_digest(envelope))


def test_invalid_native_fields_never_disclose_cli_values(prepared):
    config, work, _, fresh, _, _, original = prepared
    original['unknown_provider_key'] = 'PROVIDER-SECRET-SENTINEL'
    original['server_secret'] = fresh
    config.write_text(json.dumps(original))
    result = subprocess.run([sys.executable,str(HELPER),'inspect','--config',str(config)],
                            capture_output=True,text=True,timeout=10)
    assert result.returncode == 1
    assert fresh not in result.stdout + result.stderr
    assert 'PROVIDER-SECRET-SENTINEL' not in result.stdout + result.stderr
    assert result.stdout == '' and json.loads(result.stderr)['secret_disclosed'] is False


def test_source_only_package(tmp_path):
    spec = importlib.util.spec_from_file_location('package_recovery', ROOT / 'scripts/security/package-local-recovery.py')
    pack = importlib.util.module_from_spec(spec); spec.loader.exec_module(pack)
    archive = tmp_path / 'kit.zip'; result = pack.package(archive)
    import zipfile
    with zipfile.ZipFile(archive) as z:
        assert set(z.namelist()) == {'Recovery-Selection.ps1','Recover-Animus.ps1','Protect-PrivateState.ps1','recover_peer.py',
                                   'credential_rotation.py','README_PTBR.md','manifest.json'}
        manifest = json.loads(z.read('manifest.json'))
        for name, sha in manifest['files'].items():
            import hashlib
            assert hashlib.sha256(z.read(name)).hexdigest() == sha
    assert result['source_only'] and archive.stat().st_mode & 0o777 == 0o600


def test_cli_end_to_end_uses_existing_installed_native_config(prepared, tmp_path):
    config, _, _, fresh, _, _, original = prepared
    work = tmp_path / 'cli-private'
    env = {k:v for k,v in os.environ.items() if k != 'PYTHONPATH' and not k.startswith('ANIMUS_')}
    def call(*args):
        result = subprocess.run([sys.executable,str(HELPER),*args],cwd=tmp_path,env=env,
                                capture_output=True,text=True,timeout=10)
        assert result.returncode == 0 and fresh not in result.stdout + result.stderr
        assert 'Config validation errors' not in result.stderr
        return json.loads(result.stdout)
    public = call('prepare','--config',str(config),'--work-dir',str(work))
    envelope = r.rotation.seal(public['node_id'], fresh, base64.b64decode(public['public_key']),
                              public['fingerprint'],public['rotation_id'],public['expires_at'])
    packet = tmp_path / 'cli-envelope.json'; packet.write_text(json.dumps(envelope))
    call('stage','--work-dir',str(work),'--envelope',str(packet),'--expected-digest',r.rotation.envelope_digest(envelope))
    assert json.loads(config.read_text()) == original
    call('commit','--work-dir',str(work))
    assert json.loads(config.read_text()) == {**original,'server_secret':fresh}


def test_packager_refuses_source_drift_in_real_git_fixture(tmp_path):
    spec = importlib.util.spec_from_file_location('package_fixture', ROOT / 'scripts/security/package-local-recovery.py')
    pack = importlib.util.module_from_spec(spec); spec.loader.exec_module(pack)
    repo = tmp_path / 'fixture-repo'; repo.mkdir()
    subprocess.run(['git','init','-q',str(repo)],check=True)
    for name in pack.FILES:
        path = repo / 'scripts/security/windows-local-recovery' / name
        path.parent.mkdir(parents=True,exist_ok=True); path.write_text('fixture committed source')
    crypto = repo / 'animus/network/credential_rotation.py'
    crypto.parent.mkdir(parents=True); crypto.write_text('fixture canonical crypto')
    subprocess.run(['git','-C',str(repo),'add','.'],check=True)
    subprocess.run(['git','-C',str(repo),'-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-qm','fixture'],check=True)
    pack.ROOT = repo
    pack.package(tmp_path / 'before.zip')
    crypto.write_text('altered uncommitted crypto')
    with pytest.raises(ValueError): pack.package(tmp_path / 'after.zip')
    assert not (tmp_path / 'after.zip').exists()



def test_batch_generator_respects_actual_enrollment_rotation_and_expiry(prepared,tmp_path):
    config, work, public, _, _, _, original=prepared
    spec=importlib.util.spec_from_file_location('batch_generator',ROOT/'scripts/security/prepare-peer-rotation.py')
    generator=importlib.util.module_from_spec(spec); spec.loader.exec_module(generator)
    approved=tmp_path/'approved.json'
    record={**public,'verified_sha256':public['fingerprint'],
            'independent_channel':{'method':'existing-ssh-publickey','evidence_id':'fixture-independent-owner-key'}}
    approved.write_text(json.dumps({public['node_id']:record})); approved.chmod(0o600)
    out=tmp_path/'batch-private'; receipt=generator.prepare(approved,out,'administrative-batch-rotation')
    registry=json.loads((out/'peer-keys.json').read_text())
    assert registry['rotation_id']=='administrative-batch-rotation'
    packet=out/(public['node_id']+'.rotation.json'); envelope=json.loads(packet.read_text())
    assert envelope['rotation_id']==public['rotation_id'] and envelope['expires_at']==public['expires_at']
    assert receipt['expires_at']==public['expires_at'] and not receipt['activated']
    r.stage(work,packet,receipt['envelope_sha256'][public['node_id']])
    r.commit(work)
    assert json.loads(config.read_text())=={**original,'server_secret':registry['peers'][public['node_id']]['secret']}


@pytest.mark.parametrize('change',['rotation_missing','expired','too_short','extended','boolean_expiry','node_mismatch'])
def test_generator_rejects_invalid_enrollment_before_artifacts(prepared,tmp_path,change):
    _,_,public,_,_,_,_=prepared
    spec=importlib.util.spec_from_file_location('reject_generator',ROOT/'scripts/security/prepare-peer-rotation.py')
    generator=importlib.util.module_from_spec(spec); spec.loader.exec_module(generator)
    record={**public,'verified_sha256':public['fingerprint'],
            'independent_channel':{'method':'existing-ssh-publickey','evidence_id':'fixture-independent-key'}}
    if change=='rotation_missing': record.pop('rotation_id')
    elif change=='expired': record['expires_at']=int(time.time())-1
    elif change=='too_short': record['expires_at']=int(time.time())+30
    elif change=='extended': record['expires_at']=int(time.time())+3601
    elif change=='boolean_expiry': record['expires_at']=True
    else: record['node_id']='wrong-peer'
    approved=tmp_path/'approved-invalid.json'; approved.write_text(json.dumps({public['node_id']:record})); approved.chmod(0o600)
    out=tmp_path/'not-created'
    with pytest.raises(ValueError): generator.prepare(approved,out,'fixture-batch')
    assert not out.exists()



def test_launcher_exact_synthetic_probe_works_in_old_installed_native_crypto(tmp_path):
    import re
    launcher=(ROOT/'scripts/security/windows-local-recovery/Recover-Animus.ps1').read_text()
    probe=re.search(r"\$probe=@\(& \$script:PythonExe -c '([^']+)'",launcher).group(1)
    env={k:v for k,v in os.environ.items() if k!='PYTHONPATH' and not k.startswith('ANIMUS_')}
    result=subprocess.run([sys.executable,'-c',probe],cwd=tmp_path,env=env,capture_output=True,text=True,timeout=10)
    assert result.returncode==0 and result.stdout.strip()=='native-ok'
    assert result.stderr==''
