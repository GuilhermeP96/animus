"""Operator-installed per-node keys, never provisioned with peer HMAC trust."""
from __future__ import annotations

from functools import lru_cache
import json
import os
from pathlib import Path
import re
import stat

from ..config import AnimusConfig
from ..network.crypto import secret_is_revoked


@lru_cache(maxsize=4)
def _read_registry(path: str, inode: int, modified: int, size: int) -> dict[str, str]:
    del inode, modified, size  # File identity invalidates the bounded parse cache.
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
            raise ValueError('Peer registry must be a private regular file')
        if info.st_uid not in {0, os.getuid()} or info.st_size > 65536:
            raise ValueError('Peer registry ownership or size is unsafe')
        data = json.loads(stream.read(65537))
    if not isinstance(data, dict) or data.get('version') != 1 or not isinstance(data.get('peers'), dict) or len(data['peers']) > 1024:
        raise ValueError('Invalid peer registry')
    keys = {}
    for node, record in data['peers'].items():
        if not re.fullmatch(r'[A-Za-z0-9_.-]{1,128}', node) or not isinstance(record, dict):
            raise ValueError('Invalid peer registry record')
        if record.get('enabled') is not True:
            continue
        secret = record.get('secret')
        if not isinstance(secret, str) or not re.fullmatch(r'[A-Za-z0-9_-]{43,256}', secret) or len(set(secret)) < 8 or secret_is_revoked(secret):
            raise ValueError('Unsafe or revoked peer registry credential')
        keys[node] = secret
    if not keys:
        raise ValueError('Peer registry has no enabled credentials')
    return keys


def peer_secret(config: AnimusConfig, node_id: str) -> str:
    """Configured registry is authoritative: unknown nodes never fall back."""
    if config.server_peer_keys_file is not None:
        path = Path(config.server_peer_keys_file)
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_uid not in {0, os.getuid()}:
            raise ValueError('Peer registry must remain a private operator-owned regular file')
        keys = _read_registry(str(path), info.st_ino, info.st_mtime_ns, info.st_size)
        return keys.get(node_id, '')
    secret = config.server_secret
    return secret if secret and not secret_is_revoked(secret) else ''


def insecure_local_test(config: AnimusConfig) -> bool:
    return (config.allow_insecure_dev_auth and config.server_host in {'localhost', '127.0.0.1', '::1'}
            and config.server_peer_keys_file is None and not config.server_secret)
