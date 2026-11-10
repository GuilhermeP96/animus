#!/usr/bin/env python3
"""Offline local peer recovery. Print public enrollment or generic status only."""
from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import time

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives import serialization

HERE = Path(__file__).resolve().parent
helper = HERE / 'credential_rotation.py'
if not helper.exists():  # Tracked repository execution; packaged kit includes exact helper.
    helper = HERE.parents[2] / 'animus/network/credential_rotation.py'
spec = importlib.util.spec_from_file_location('qualified_rotation', helper)
rotation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rotation)
MAX_JSON = 1024**2


class RecoveryError(Exception):
    pass


def windows_powershell_env():
    # A Python child of PowerShell 7 inherits its module search path. Windows
    # PowerShell 5.1 must discover its own inbox Security module, not PS7 DLLs.
    # This affects this child process only, without changing profiles/policy.
    return {key: value for key, value in os.environ.items()
            if key.casefold() != 'psmodulepath'}


def safe_path(path: Path, exists=True) -> Path:
    path = Path(path).absolute()
    if path.resolve() != path or (exists and not path.is_file()):
        raise RecoveryError('Selected file must be an existing regular non-link file')
    for item in [path, *path.parents]:
        if item.exists() and getattr(item.stat(), 'st_file_attributes', 0) & 0x400:
            raise RecoveryError('Windows reparse paths are forbidden')
    return path


def protect(path: Path, owner_sid: str | None = None, directory=False):
    if os.name == 'nt':
        if not owner_sid or not re.fullmatch(r'S-1-[0-9-]+', owner_sid):
            raise RecoveryError('Verified Windows owner SID required')
        command = ['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'RemoteSigned', '-File',
                   str(HERE / 'Protect-PrivateState.ps1'), '-LiteralPath', str(path), '-OwnerSid', owner_sid]
        if directory:
            command.append('-Directory')
        result = subprocess.run(command, capture_output=True, timeout=30,
                                env=windows_powershell_env())
        if result.returncode:
            raise RecoveryError('Private Windows ACL could not be established')
    else:
        path.chmod(0o700 if directory else 0o600)


def verify_parent(path: Path, owner_sid):
    safe_path(path, exists=False)
    if not path.is_dir():
        raise RecoveryError('Existing parent directory required')
    if os.name == 'nt':
        result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'RemoteSigned', '-File',
             str(HERE / 'Protect-PrivateState.ps1'), '-LiteralPath', str(path),
             '-OwnerSid', owner_sid or '', '-VerifyParent'], capture_output=True, timeout=30,
             env=windows_powershell_env())
        if result.returncode:
            raise RecoveryError('Parent ACL permits unsafe mutation')


def write_private(path: Path, data: bytes, owner_sid=None):
    safe_path(path, exists=False)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        # Establish ACL on the EMPTY file before writing private bytes.
        protect(path, owner_sid)
        with os.fdopen(descriptor, 'wb') as stream:
            descriptor = None
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        if descriptor is not None:
            os.close(descriptor)


def read_json(path: Path):
    safe_path(path)
    if path.stat().st_size > MAX_JSON:
        raise RecoveryError('Recovery input exceeds size limit')
    data = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(data, dict):
        raise RecoveryError('Recovery JSON must be an object')
    return data


def digest(path):
    safe_path(path)
    if path.stat().st_size > MAX_JSON:
        raise RecoveryError('Config exceeds size limit')
    return hashlib.sha256(path.read_bytes()).hexdigest()


def native_validate(data):
    # Do not call load(): it can auto-migrate/save or log validation input.
    from animus.config import AnimusConfig
    try:
        AnimusConfig(_env_file=None, **data)
    except Exception:
        raise RecoveryError('Selected config is not accepted by the existing native Animus') from None


def config(path):
    path = safe_path(path)
    data = read_json(path)
    if not isinstance(data.get('node_id'), str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,128}', data['node_id']):
        raise RecoveryError('Existing stable node identity required')
    if not isinstance(data.get('server_secret'), str):
        raise RecoveryError('Existing server_secret field is required')
    native_validate(data)
    return path, data


def prepare(config_path, work, owner_sid=None, config_owner_sid=None, ttl=3600, rotation_id=None):
    if not 60 <= ttl <= 3600:
        raise RecoveryError('Local enrollment validity must be60–3600 seconds')
    verify_parent(Path(config_path).absolute().parent, config_owner_sid)
    path, data = config(config_path)
    work = Path(work).absolute()
    if work.resolve() != work:
        raise RecoveryError('Recovery workspace symlinks forbidden')
    verify_parent(work.parent, owner_sid)
    work.mkdir(mode=0o700, parents=False, exist_ok=False)
    protect(work, owner_sid, directory=True)
    identifier = rotation_id or 'recovery-' + secrets.token_hex(12)
    if not re.fullmatch(r'[A-Za-z0-9_.-]{1,128}', identifier):
        raise RecoveryError('Invalid rotation identity')
    private = X25519PrivateKey.generate()
    public = rotation.public_bytes(private.public_key())
    expires = int(time.time()) + ttl
    state = {'node_id': data['node_id'], 'rotation_id': identifier, 'expires_at': expires,
             'config_path': str(path), 'owner_sid': owner_sid, 'config_owner_sid': config_owner_sid,
             'public_key': base64.b64encode(public).decode(), 'fingerprint': rotation.fingerprint(public)}
    raw = private.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
                               serialization.NoEncryption())
    write_private(work / 'recipient.key', raw, owner_sid)
    write_private(work / 'state.json', json.dumps(state).encode(), owner_sid)
    # Only these public metadata fields may be pasted to the owner chat.
    return {key: state[key] for key in ('node_id', 'public_key', 'fingerprint', 'rotation_id', 'expires_at')}


def stage(work, envelope_path, expected_digest):
    work = Path(work).absolute()
    state = read_json(work / 'state.json')
    if time.time() >= state['expires_at']:
        raise RecoveryError('Enrollment expired; generate a fresh public packet')
    if not re.fullmatch(r'[0-9a-f]{64}', expected_digest):
        raise RecoveryError('Independent operator digest is required')
    verify_parent(work, state.get('owner_sid'))
    verify_parent(Path(state['config_path']).parent, state.get('config_owner_sid'))
    path, current = config(Path(state['config_path']))
    if current['node_id'] != state['node_id']:
        raise RecoveryError('Selected config identity changed')
    key_path = safe_path(work / 'recipient.key')
    if key_path.stat().st_size != 32:
        raise RecoveryError('Invalid local recipient key')
    recipient = X25519PrivateKey.from_private_bytes(key_path.read_bytes())
    own = rotation.public_bytes(recipient.public_key())
    if state['fingerprint'] != rotation.fingerprint(own) or state['public_key'] != base64.b64encode(own).decode():
        raise RecoveryError('Enrollment public identity changed')
    envelope = read_json(Path(envelope_path))
    if envelope.get('expires_at', 0) > state['expires_at']:
        raise RecoveryError('Envelope exceeds locally approved enrollment validity')
    try:
        new_secret = rotation.unseal(envelope, recipient, state['node_id'], state['rotation_id'], expected_digest)
    except Exception:
        raise RecoveryError('Envelope identity, integrity or validity verification failed') from None
    if secrets.compare_digest(new_secret, current['server_secret']):
        raise RecoveryError('Recovery must rotate the credential')
    candidate = {**current, 'server_secret': new_secret}
    # No new strict-auth config field: older native models reject extra fields
    # and load() can log their input. Native nonce preflight stays in launcher.
    native_validate(candidate)
    original_sha = digest(path)
    backup = work / ('config-before-' + secrets.token_hex(6) + '.json')
    write_private(backup, path.read_bytes(), state.get('owner_sid'))
    if digest(path) != original_sha:
        raise RecoveryError('Config changed during backup; stop and reconcile')
    temporary = path.with_name('.animus-recovery-' + secrets.token_hex(12) + '.tmp')
    write_private(temporary, (json.dumps(candidate, indent=2) + '\n').encode(), state.get('config_owner_sid'))
    staged = {'node_id': state['node_id'], 'config_path': str(path), 'original_sha256': original_sha,
              'candidate_path': str(temporary), 'candidate_sha256': digest(temporary),
              'backup_path': str(backup), 'expires_at': state['expires_at']}
    write_private(work / 'staged.json', json.dumps(staged).encode(), state.get('owner_sid'))
    return {'status': 'staged', 'node_id': state['node_id'], 'secret_disclosed': False}


def commit(work):
    work = Path(work).absolute()
    state = read_json(work / 'state.json')
    staged = read_json(work / 'staged.json')
    if staged['expires_at'] != state['expires_at'] or staged['node_id'] != state['node_id'] or staged['config_path'] != state['config_path']:
        raise RecoveryError('Staged enrollment changed')
    if time.time() >= staged['expires_at']:
        raise RecoveryError('Staged recovery expired; do not activate')
    verify_parent(work, state.get('owner_sid'))
    verify_parent(Path(state['config_path']).parent, state.get('config_owner_sid'))
    path, current = config(Path(state['config_path']))
    temporary = safe_path(Path(staged['candidate_path']))
    if temporary.parent != path.parent or not temporary.name.startswith('.animus-recovery-'):
        raise RecoveryError('Staged replacement path is invalid')
    if current['node_id'] != staged['node_id'] or digest(path) != staged['original_sha256']:
        raise RecoveryError('Config drift: keep stopped and reconcile; no blind replacement')
    if digest(temporary) != staged['candidate_sha256']:
        raise RecoveryError('Staged config changed')
    candidate = read_json(temporary)
    if set(candidate) != set(current) or any(candidate[key] != value for key, value in current.items() if key != 'server_secret'):
        raise RecoveryError('Recovery may only replace the selected server_secret field')
    native_validate(candidate)
    os.replace(temporary, path)
    receipt = {'status': 'applied', 'node_id': state['node_id'], 'config_sha256': digest(path),
               'restart_required': True, 'old_secret_rollback_allowed': False}
    write_private(work / 'applied.json', json.dumps(receipt).encode(), state.get('owner_sid'))
    return {'status': 'applied', 'node_id': state['node_id'], 'restart_required': True, 'secret_disclosed': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['inspect', 'prepare', 'stage', 'commit'])
    parser.add_argument('--config', type=Path)
    parser.add_argument('--work-dir', type=Path)
    parser.add_argument('--owner-sid')
    parser.add_argument('--config-owner-sid')
    parser.add_argument('--ttl-seconds', type=int, default=3600)
    parser.add_argument('--rotation-id')
    parser.add_argument('--envelope', type=Path)
    parser.add_argument('--expected-digest')
    args = parser.parse_args()
    if args.phase == 'inspect':
        path, data = config(args.config)
        result = {'config_path': str(path), 'node_id': data['node_id']}
    elif args.phase == 'prepare':
        result = prepare(args.config, args.work_dir, args.owner_sid, args.config_owner_sid,
                         args.ttl_seconds, args.rotation_id)
    elif args.phase == 'stage':
        result = stage(args.work_dir, args.envelope, args.expected_digest or '')
    else:
        result = commit(args.work_dir)
    print(json.dumps(result))


if __name__ == '__main__':
    try:
        main()
    except Exception:
        # Never print exception text, traceback, config or provider values.
        print(json.dumps({'status': 'blocked', 'secret_disclosed': False}), file=sys.stderr)
        raise SystemExit(1)
