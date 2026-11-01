#!/usr/bin/env python3
"""Root-only native peer enrollment/staging. Never stops/restarts or activates keys."""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('local_peer_recovery',HERE/'windows-local-recovery/recover_peer.py')
r=importlib.util.module_from_spec(spec); spec.loader.exec_module(r)
LIMIT=1024**2


def private(path, directory=False):
    path=Path(path).absolute()
    if path.resolve()!=path: raise r.RecoveryError('Native private path cannot be a symlink')
    observed=path.stat()
    expected=stat.S_ISDIR(observed.st_mode) if directory else stat.S_ISREG(observed.st_mode)
    if not expected or observed.st_uid!=os.geteuid() or observed.st_mode & 0o077:
        raise r.RecoveryError('Native owner-private path required')
    if not directory and observed.st_size>LIMIT: raise r.RecoveryError('Native input is too large')
    return path


def validate_identity(data,expected_node,expected_secret_hash,config_path,effective_data_dir):
    if data.get('node_id')!=expected_node or not re.fullmatch(r'[A-Za-z0-9_.-]{1,128}',expected_node):
        raise r.RecoveryError('Native identity mismatch')
    if not re.fullmatch(r'[0-9a-f]{64}',expected_secret_hash) or hashlib.sha256(data['server_secret'].encode()).hexdigest()!=expected_secret_hash:
        raise r.RecoveryError('Native existing credential fingerprint mismatch')
    selected=Path(config_path).absolute()
    effective=Path(effective_data_dir).absolute()
    if selected.resolve()!=selected or effective.resolve()!=effective or selected!=effective/'config.json':
        raise r.RecoveryError('Selected native config differs from effective ANIMUS_DATA_DIR')
    if data.get('data_dir') and Path(data['data_dir']).absolute()!=effective:
        raise r.RecoveryError('Native data_dir field differs from actual runtime directory')


def validate_process(command,executable,python_executable):
    if Path(executable).resolve()!=Path(python_executable).resolve() or len(command)<4:
        raise r.RecoveryError('Recovery must use the existing native interpreter')
    if Path(command[0]).absolute()!=Path(python_executable).absolute():
        raise r.RecoveryError('Actual native virtualenv differs from recovery interpreter')
    if command[1:4]!=['-m','animus.cli','daemon'] or len(command)!=4:
        raise r.RecoveryError('Only exact direct native Animus daemon command is qualified')
    if any(part in str(Path(python_executable).absolute()).lower() for part in ('.codex','vscode','claude','antigravity')):
        raise r.RecoveryError('Retired/Codex client interpreter forbidden')


def runtime(unit,config_path,expected_node,expected_secret_hash):
    if os.name!='posix' or os.geteuid()!=0: raise r.RecoveryError('Native VPS helper requires independent Root administration')
    if not re.fullmatch(r'animus[-_.A-Za-z0-9]*\.service',unit): raise r.RecoveryError('Explicit native Animus service required')
    properties=('MainPID','ActiveState','SubState','LoadState','User','ExecStart','WorkingDirectory','Environment','EnvironmentFiles','FragmentPath','DropInPaths')
    command=['systemctl','show',unit,*['--property='+p for p in properties]]
    result=subprocess.run(command,capture_output=True,check=True,timeout=10,text=True)
    values=dict(line.split('=',1) for line in result.stdout.splitlines() if '=' in line)
    if values.get('LoadState')!='loaded' or values.get('ActiveState')!='active' or values.get('SubState')!='running' or values.get('User') not in {'','root'}:
        raise r.RecoveryError('Expected active Root-owned native service')
    pid=int(values.get('MainPID','0'))
    if pid<=1: raise r.RecoveryError('Actual native process required; inactive metadata is insufficient')
    process=Path('/proc')/str(pid)
    if process.stat().st_uid!=0: raise r.RecoveryError('Native process owner changed')
    cmdline=(process/'cmdline').read_bytes()
    command=[x.decode() for x in cmdline.split(b'\0') if x]
    validate_process(command,(process/'exe').resolve(),sys.executable)
    cwd=(process/'cwd').resolve()
    raw_environment=(process/'environ').read_bytes()
    if len(raw_environment)>LIMIT: raise r.RecoveryError('Native process environment exceeds limit')
    observed=dict(item.decode().split('=',1) for item in raw_environment.split(b'\0') if b'=' in item)
    # Only native settings below are consulted. Never emit the raw environment.
    file_env={}; dotenv=cwd/'.env'; env_hash=None
    if dotenv.exists():
        private(dotenv)
        from dotenv import dotenv_values
        file_env=dotenv_values(dotenv)
        env_hash=hashlib.sha256(dotenv.read_bytes()).hexdigest()
    env_file_hashes={}
    listed=values.get('EnvironmentFiles','')
    if listed:
        matches=list(re.finditer(r'(/[^\s]+) \(ignore_errors=(?:yes|no)\)',listed))
        if not matches or re.sub(r'(/[^\s]+) \(ignore_errors=(?:yes|no)\)','',listed).strip():
            raise r.RecoveryError('Native systemd EnvironmentFiles require explicit safe paths')
        from dotenv import dotenv_values
        for match in matches:
            path=private(Path(match.group(1)))
            contents=dotenv_values(path)
            if contents.get('ANIMUS_SECURE_AUTH','1')!='1' or contents.get('ANIMUS_SERVER_SECRET'):
                raise r.RecoveryError('Native environment-file auth override requires separate migration')
            if contents.get('ANIMUS_DATA_DIR') and contents['ANIMUS_DATA_DIR']!=observed.get('ANIMUS_DATA_DIR'):
                raise r.RecoveryError('Native environment-file DataDir differs from active process')
            env_file_hashes[str(path)]=hashlib.sha256(path.read_bytes()).hexdigest()
    secure=observed.get('ANIMUS_SECURE_AUTH',file_env.get('ANIMUS_SECURE_AUTH','1'))
    if secure!='1' or file_env.get('ANIMUS_SECURE_AUTH','1')!='1': raise r.RecoveryError('Explicit insecure native authentication forbidden')
    if observed.get('ANIMUS_SERVER_SECRET') or file_env.get('ANIMUS_SERVER_SECRET'):
        raise r.RecoveryError('Credential environment override requires separate typed migration; no guessed precedence')
    effective=observed.get('ANIMUS_DATA_DIR') or file_env.get('ANIMUS_DATA_DIR')
    if not effective or not Path(effective).is_absolute(): raise r.RecoveryError('Actual explicit ANIMUS_DATA_DIR evidence required')
    config_path=private(config_path); private(config_path.parent,directory=True)
    _,data=r.config(config_path)
    validate_identity(data,expected_node,expected_secret_hash,config_path,effective)
    # Hash non-exported systemd/proc evidence, preserving confidentiality.
    proof={'unit':unit,'pid':pid,'config_path':str(config_path),'node_id':expected_node,
           'secret_sha256':expected_secret_hash,'effective_data_dir':str(Path(effective)),
           'service_sha256':hashlib.sha256(result.stdout.encode()).hexdigest(),
           'cmdline_sha256':hashlib.sha256(cmdline).hexdigest(),
           'process_start':(process/'stat').read_text().rsplit(')',1)[1].split()[19],
           'cwd':str(cwd),'dotenv_sha256':env_hash,'environment_file_sha256':env_file_hashes,'config_sha256':r.digest(config_path)}
    return proof


def prepare(unit,config_path,node,secret_hash,work,ttl=3600):
    proof=runtime(unit,config_path,node,secret_hash)
    private(Path(work).absolute().parent,directory=True)
    public=r.prepare(config_path,work,ttl=ttl)
    if public['node_id']!=node: raise r.RecoveryError('Native enrollment identity changed')
    r.write_private(Path(work)/'native-runtime.json',json.dumps(proof).encode())
    return public


def verify(work):
    work=private(work,directory=True)
    before=r.read_json(private(work/'native-runtime.json'))
    current=runtime(before['unit'],before['config_path'],before['node_id'],before['secret_sha256'])
    if current!=before: raise r.RecoveryError('Native process/config/unit/environment drift; prepare a fresh packet')
    private(work/'state.json'); private(work/'recipient.key')
    return before


def stage(work,envelope,digest):
    before=verify(work)
    result=r.stage(work,envelope,digest)
    # Recheck before leaving a staged credential, never activate it here.
    if runtime(before['unit'],before['config_path'],before['node_id'],before['secret_sha256'])!=before:
        raise r.RecoveryError('Native runtime drift after staging; do not activate')
    return {**result,'activated':False,'unit_unchanged':True}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase',choices=['prepare','verify','stage'])
    parser.add_argument('--unit'); parser.add_argument('--config',type=Path)
    parser.add_argument('--expected-node-id'); parser.add_argument('--expected-secret-sha256')
    parser.add_argument('--work-dir',type=Path,required=True)
    parser.add_argument('--ttl-seconds',type=int,default=3600)
    parser.add_argument('--envelope',type=Path); parser.add_argument('--expected-digest')
    args=parser.parse_args()
    try:
        if args.phase=='prepare': result=prepare(args.unit,args.config,args.expected_node_id,args.expected_secret_sha256,args.work_dir,args.ttl_seconds)
        elif args.phase=='stage': result=stage(args.work_dir,args.envelope,args.expected_digest)
        else:
            proof=verify(args.work_dir); result={'verified':True,'node_id':proof['node_id'],'activated':False}
        print(json.dumps(result))
    except Exception:
        print(json.dumps({'status':'blocked','secret_disclosed':False,'activated':False}),file=sys.stderr)
        raise SystemExit(1)
