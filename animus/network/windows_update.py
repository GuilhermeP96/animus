"""Source-bound durable Windows native update jobs; no detached helper assumption."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import zipfile
from email.parser import BytesParser

RUNNER=Path(__file__).with_name('windows-update-task.ps1')
MAX_WHEEL=64*1024**2


def verified_local_wheel(path,expected_version):
    path=Path(path).absolute()
    if path.resolve()!=path or not path.is_file() or path.stat().st_size>MAX_WHEEL or path.suffix!='.whl':
        raise ValueError('Bounded local non-link wheel required')
    if not re.fullmatch(r'[0-9A-Za-z.+-]{1,64}',expected_version):
        raise ValueError('Bounded exact package version required')
    with zipfile.ZipFile(path) as archive:
        metas=[name for name in archive.namelist() if name.endswith('.dist-info/METADATA')]
        if len(metas)!=1: raise ValueError('Single Animus metadata required')
        info=archive.getinfo(metas[0])
        if info.file_size>65536: raise ValueError('Package metadata is too large')
        metadata=BytesParser().parsebytes(archive.read(metas[0]))
        if metadata.get('Name','').lower()!='animus' or metadata.get('Version')!=expected_version:
            raise ValueError('Installed target must exactly match authenticated Animus version')
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_spec(package,latest,config,python=sys.executable,pid=None):
    package=Path(package).absolute()
    digest=verified_local_wheel(package,latest)
    config_path=Path(config.config_path).absolute()
    if config_path.resolve()!=config_path or not config_path.is_file() or config_path.stat().st_size>1024**2:
        raise ValueError('Exact existing native config required')
    data=json.loads(config_path.read_text(encoding='utf-8-sig'))
    if data.get('node_id')!=config.node_id or not re.fullmatch(r'[A-Za-z0-9_.-]{1,128}',config.node_id):
        raise ValueError('Current daemon and persistent native identity differ')
    if package.parent!=Path(config.data_dir).absolute()/'updates':
        raise ValueError('Only authenticated wheel in exact native update directory is accepted')
    from ..service import SERVICE_NAME
    return {'version':1,'task_name':SERVICE_NAME,'task_path':'\\','python':str(Path(python).absolute()),
            'data_dir':str(Path(config.data_dir).absolute()),'config_path':str(config_path),
            'config_sha256':hashlib.sha256(config_path.read_bytes()).hexdigest(),'node_id':config.node_id,
            'source_pid':os.getpid() if pid is None else pid,'wheel':str(package),
            'wheel_sha256':digest,'expected_version':latest}


def stage(package,latest,config):
    if os.name!='nt': raise ValueError('Windows durable updater must run on native Windows')
    spec=build_spec(package,latest,config)
    root=os.environ.get('SystemRoot','C:\\Windows')
    powershell=str(Path(root)/'System32/WindowsPowerShell/v1.0/powershell.exe')
    result=subprocess.run([powershell,'-NoProfile','-NonInteractive','-File',str(RUNNER),'-Mode','Register'],
                          input=json.dumps(spec),capture_output=True,text=True,timeout=60)
    if result.returncode: return False
    try:
        receipt=json.loads(result.stdout.strip())
    except (ValueError,TypeError): return False
    return receipt.get('status')=='registered' and receipt.get('job_started') is True and receipt.get('installed') is False and receipt.get('restart_verified') is False
