"""Actual wheel/config fixtures; no Windows scheduled-task simulation."""
import hashlib
import json
from pathlib import Path
import secrets
import zipfile

import pytest
from animus.config import AnimusConfig
from animus.network.windows_update import build_spec, verified_local_wheel, RUNNER


def wheel(path,name='animus',version='99.0.0'):
    with zipfile.ZipFile(path,'w') as z:
        z.writestr('animus-99.0.0.dist-info/METADATA',f'Name: {name}\nVersion: {version}\n')
    return path


def test_real_wheel_version_hash_and_exact_native_config_binding(tmp_path):
    config=AnimusConfig(_env_file=None,node_id='update-fixture',data_dir=tmp_path,server_secret=secrets.token_urlsafe(48))
    config.save(); updates=tmp_path/'updates'; updates.mkdir()
    package=wheel(updates/'animus-99.0.0-py3-none-any.whl')
    before=config.config_path.read_bytes()
    spec=build_spec(package,'99.0.0',config,python='/existing/native/python',pid=123)
    assert spec['wheel_sha256']==hashlib.sha256(package.read_bytes()).hexdigest()
    assert spec['config_sha256']==hashlib.sha256(before).hexdigest()
    assert config.server_secret not in json.dumps(spec)
    assert spec['source_pid']==123 and spec['node_id']==config.node_id
    assert config.config_path.read_bytes()==before

@pytest.mark.parametrize('name,version',[('other','99.0.0'),('animus','98.0.0')])
def test_wrong_package_identity_version_refused(tmp_path,name,version):
    package=wheel(tmp_path/'candidate.whl',name,version)
    with pytest.raises(ValueError): verified_local_wheel(package,'99.0.0')


def test_ambiguous_wheel_metadata_refused(tmp_path):
    good=wheel(tmp_path/'good.whl')
    with zipfile.ZipFile(good,'a') as z: z.writestr('other.dist-info/METADATA','Name: animus\nVersion:99.0.0')
    with pytest.raises(ValueError): verified_local_wheel(good,'99.0.0')


def test_wheel_links_refused(tmp_path):
    good=wheel(tmp_path/'good.whl'); link=tmp_path/'link.whl'
    try:
        link.symlink_to(good)
    except OSError as exc:
        if getattr(exc, 'winerror', None) != 1314:
            raise
        pytest.skip('Windows account lacks file-symlink creation privilege')
    with pytest.raises(ValueError): verified_local_wheel(link,'99.0.0')


def test_external_update_path_and_node_drift_refused(tmp_path):
    data=tmp_path/'native'; config=AnimusConfig(_env_file=None,node_id='update-fixture',data_dir=data)
    config.save(); outside=wheel(tmp_path/'outside.whl')
    with pytest.raises(ValueError): build_spec(outside,'99.0.0',config)
    updates=data/'updates'; updates.mkdir(); package=wheel(updates/'candidate.whl')
    saved=json.loads(config.config_path.read_text()); saved['node_id']='other-peer'; config.config_path.write_text(json.dumps(saved))
    with pytest.raises(ValueError): build_spec(package,'99.0.0',config)


def test_runner_has_no_broad_kill_or_detached_completion_assumption():
    script=RUNNER.read_text()
    assert 'taskkill.exe' not in script and 'animus*.exe' not in script
    assert 'restart_verified=$true' in script and 'server_reconnection_verified=$false' in script
    assert 'source_creation_ticks' in script and 'expected_version' in script
    assert '--no-index --no-deps' in script


def test_persistent_native_data_directory_drift_refused(tmp_path):
    data=tmp_path/'native'; config=AnimusConfig(_env_file=None,node_id='update-fixture',data_dir=data)
    config.save(); updates=data/'updates';updates.mkdir();package=wheel(updates/'candidate.whl')
    saved=json.loads(config.config_path.read_text());saved['data_dir']=str(tmp_path/'other-native')
    config.config_path.write_text(json.dumps(saved))
    with pytest.raises(ValueError):build_spec(package,'99.0.0',config)
