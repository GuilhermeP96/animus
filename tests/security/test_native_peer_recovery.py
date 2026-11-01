"""Pure actual gates/real private file fixtures; no claim of live service control."""
import hashlib
import importlib.util
import os
from pathlib import Path
import secrets
import sys

import pytest

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('native_recovery',ROOT/'scripts/security/prepare-native-peer-recovery.py')
n=importlib.util.module_from_spec(spec); spec.loader.exec_module(n)


def test_exact_native_node_secret_and_effective_datadir(tmp_path):
    secret=secrets.token_urlsafe(48); digest=hashlib.sha256(secret.encode()).hexdigest()
    data={'node_id':'native-fixture','server_secret':secret,'data_dir':str(tmp_path)}
    config=tmp_path/'config.json'; config.write_text('fixture'); config.chmod(0o600)
    n.validate_identity(data,'native-fixture',digest,config,tmp_path)
    invalid=[('other-node',digest,config,tmp_path),('native-fixture','0'*64,config,tmp_path),
             ('native-fixture',digest,config,tmp_path/'different'),('native-fixture',digest,tmp_path/'backup.json',tmp_path)]
    for node,keyhash,path,directory in invalid:
        with pytest.raises(n.r.RecoveryError): n.validate_identity(data,node,keyhash,path,directory)
    with pytest.raises(n.r.RecoveryError):
        n.validate_identity({**data,'data_dir':str(tmp_path/'different')},'native-fixture',digest,config,tmp_path)


def test_existing_native_interpreter_command_attribution():
    n.validate_process([sys.executable,'-m','animus.cli','daemon'],sys.executable,sys.executable)
    for command in ([sys.executable,'-m','other.app','daemon'],[sys.executable,'-m','animus.cli','daemon','--other'],[sys.executable,'shell.py']):
        with pytest.raises(n.r.RecoveryError): n.validate_process(command,sys.executable,sys.executable)
    with pytest.raises(n.r.RecoveryError):
        n.validate_process([sys.executable,'-m','animus.cli','daemon'],sys.executable,'/usr/bin/retired-python')


def test_owner_private_regular_files_required(tmp_path):
    good=tmp_path/'private.json'; good.write_text('fixture'); good.chmod(0o600)
    assert n.private(good)==good
    good.chmod(0o644)
    with pytest.raises(n.r.RecoveryError): n.private(good)
    good.chmod(0o600); link=tmp_path/'linked'; link.symlink_to(good)
    with pytest.raises(n.r.RecoveryError): n.private(link)
    with pytest.raises(n.r.RecoveryError): n.private(tmp_path)
    directory=tmp_path/'state'; directory.mkdir(mode=0o700)
    assert n.private(directory,directory=True)==directory
    directory.chmod(0o755)
    with pytest.raises(n.r.RecoveryError): n.private(directory,directory=True)


def test_oversized_native_private_input_refused(tmp_path):
    path=tmp_path/'oversized'; path.write_bytes(b' '*(n.LIMIT+1)); path.chmod(0o600)
    with pytest.raises(n.r.RecoveryError): n.private(path)


def test_unix_save_hardens_only_datadir_and_config_preserving_other_data(tmp_path):
    from animus.config import AnimusConfig
    data_dir=tmp_path/'native-data'; data_dir.mkdir(mode=0o755)
    existing=data_dir/'existing-memory.txt'; existing.write_text('existing fixture'); existing.chmod(0o640)
    sibling=tmp_path/'other-project'; sibling.mkdir(mode=0o755)
    config=AnimusConfig(_env_file=None,node_id='native-mode-fixture',data_dir=data_dir,
                        server_secret=secrets.token_urlsafe(48))
    config.save()
    assert data_dir.stat().st_mode & 0o777==0o700
    assert config.config_path.stat().st_mode & 0o777==0o600
    assert existing.stat().st_mode & 0o777==0o640 and sibling.stat().st_mode & 0o777==0o755
    assert AnimusConfig.load(config.config_path).node_id=='native-mode-fixture'
    assert not list(data_dir.glob('.config-*.tmp'))


def test_unix_save_refuses_config_symlink_without_mutating_target(tmp_path):
    from animus.config import AnimusConfig
    data_dir=tmp_path/'native-data'; data_dir.mkdir(mode=0o700)
    target=tmp_path/'other-config'; target.write_text('must stay unchanged')
    (data_dir/'config.json').symlink_to(target)
    config=AnimusConfig(_env_file=None,node_id='native-symlink-fixture',data_dir=data_dir)
    with pytest.raises(ValueError): config.save()
    assert target.read_text()=='must stay unchanged'
