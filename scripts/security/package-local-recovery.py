#!/usr/bin/env python3
"""Create a source-only local recovery ZIP. No credentials or runtime state."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[2]
FILES = ['Recover-Animus.ps1', 'Protect-PrivateState.ps1', 'recover_peer.py', 'README_PTBR.md']

def package(destination):
    destination = Path(destination).absolute()
    if destination.resolve() != destination or destination.exists():
        raise ValueError('Require a new non-link output path')
    revision = subprocess.check_output(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], text=True).strip()
    paths = {name: 'scripts/security/windows-local-recovery/' + name for name in FILES}
    paths['credential_rotation.py'] = 'animus/network/credential_rotation.py'
    entries = {}
    for name, relative in paths.items():
        tracked = subprocess.check_output(['git', '-C', str(ROOT), 'show', revision + ':' + relative], stderr=subprocess.DEVNULL)
        source = ROOT / relative
        if source.resolve() != source or source.read_bytes() != tracked:
            raise ValueError('Package source must exactly match committed tracked blobs')
        entries[name] = tracked
    manifest = {'version': 1, 'source_commit': revision, 'expires_when': 'runtime_prepare_plus_60_to_3600_seconds',
                'files': {name: hashlib.sha256(data).hexdigest() for name, data in entries.items()}}
    entries['manifest.json'] = (json.dumps(manifest, indent=2) + '\n').encode()
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'wb') as output:
        with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            for name, data in sorted(entries.items()):
                entry = zipfile.ZipInfo(name, (2026, 10, 13, 0, 0, 0))
                entry.external_attr = 0o100600 << 16
                entry.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(entry, data)
        output.flush()
        os.fsync(output.fileno())
    return {'source_commit': revision, 'sha256': hashlib.sha256(destination.read_bytes()).hexdigest(),
            'bytes': destination.stat().st_size, 'source_only': True}

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    print(json.dumps(package(parser.parse_args().output)))
