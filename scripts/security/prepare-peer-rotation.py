#!/usr/bin/env python3
"""Prepare private registry/encrypted envelopes offline; never activate keys."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from animus.network.credential_rotation import seal, envelope_digest


def prepare(approved: Path, output: Path, rotation_id: str):
    if approved.stat().st_size > 65536:
        raise ValueError('Recipient approval input is too large')
    recipients = json.loads(approved.read_text())
    if not isinstance(recipients, dict) or not 1 <= len(recipients) <= 64:
        raise ValueError('Expected1–64 independently approved recipients')
    if not re.fullmatch(r'[A-Za-z0-9_.-]{1,128}', rotation_id):
        raise ValueError('Invalid rotation identifier')
    # Validate every approval before creating any private credential artifact.
    allowed_methods = {'existing-ssh-publickey', 'verified-native-admin',
                       'verified-device-license-credential', 'verified-cloudflare-access'}
    for node, record in recipients.items():
        if not re.fullmatch(r'[A-Za-z0-9_.-]{1,128}', node) or not isinstance(record, dict):
            raise ValueError('Every recipient requires a valid independently approved identity')
        channel = record.get('independent_channel')
        if not isinstance(channel, dict) or channel.get('method') not in allowed_methods or not channel.get('evidence_id'):
            raise ValueError('Every recipient requires a supported independent verification method and evidence')
        key = base64.b64decode(record['public_key'], validate=True)
        if len(key) != 32 or hashlib.sha256(key).hexdigest() != record['verified_sha256']:
            raise ValueError('Independent recipient approval mismatch')
    output.mkdir(mode=0o700, parents=False, exist_ok=False)
    registry = {'version': 1, 'peers': {}}
    expires_at = int(time.time()) + 3600
    hashes = {}
    for node, record in recipients.items():
        secret = secrets.token_urlsafe(48)
        registry['peers'][node] = {'enabled': True, 'secret': secret}
        envelope = seal(node, secret, base64.b64decode(record['public_key']),
                        record['verified_sha256'], rotation_id, expires_at)
        hashes[node] = envelope_digest(envelope)
        path = output / f'{node}.rotation.json'
        path.write_text(json.dumps(envelope, sort_keys=True) + '\n')
        path.chmod(0o600)
    path = output / 'peer-keys.json'
    path.write_text(json.dumps(registry, sort_keys=True) + '\n')
    path.chmod(0o600)
    # Only metadata is returned; never display credentials or encrypted payloads.
    return {'rotation_id': rotation_id, 'peer_count': len(recipients), 'expires_at': expires_at,
            'activated': False, 'output': str(output), 'envelope_sha256': hashes}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--approved-recipients', type=Path, required=True)
    parser.add_argument('--private-output', type=Path, required=True)
    parser.add_argument('--rotation-id', required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.approved_recipients, args.private_output, args.rotation_id)))
