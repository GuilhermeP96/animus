# Root-native VPS peer recovery (source only)

`prepare-native-peer-recovery.py` has only prepare/verify/stage phases. It never
stops/starts a service, commits replacement, changes active registry or activates
a key. Run using the existing native `/opt/animus-peer/bin/python`; no installs.
Root must have independently confirmed the active node, existing credential
SHA256 and actual config. No fallback to a guessed profile/default DataDir.

Prepare requires active Root-owned exact direct native service process:
python -m animus.cli daemon. It binds actual process executable/cmdline/PID/start,
systemd unit properties, actual process ANIMUS_DATA_DIR, private cwd .env and
systemd EnvironmentFiles hashes. The selected existing config must equal this
DataDir/config.json, node and fingerprint. Credential environment overrides or
conflicting raw data_dir fields require a separate typed migration; no guessing.
Files/config/state/parents must be owner-private, regular and non-link. Explicit
insecure auth is refused. Raw env, config/provider values and errors never emit.

```
/opt/animus-peer/bin/python scripts/security/prepare-native-peer-recovery.py prepare --unit animus-peer.service --config /EXACT/NATIVE/DATA/config.json --expected-node-id VERIFIED_NODE --expected-secret-sha256 VERIFIED_OLD_SHA256 --work-dir /PRIVATE_PARENT/new-native-enrollment
```

Public result has only node_id/public_key/fingerprint/rotation_id/expires_at.
Root registers this through independently verified-native-admin evidence in the
private approved-recipient input. Batch generator uses each recipient's exact
rotation/expiry. Global HMAC is not a recovery transport. Private X25519 stays
local0700/0600; preserve provider/queue/license/node/data settings exactly.

```
/opt/animus-peer/bin/python scripts/security/prepare-native-peer-recovery.py verify --work-dir /PRIVATE_PARENT/new-native-enrollment
/opt/animus-peer/bin/python scripts/security/prepare-native-peer-recovery.py stage --work-dir /PRIVATE_PARENT/new-native-enrollment --envelope /PRIVATE/envelope.json --expected-digest INDEPENDENT_CANONICAL_SHA256
```

Verify/stage reread actual active process and exact private config, comparing all
bound evidence. Drift aborts; prepare fresh enrollment. Stage writes only private
backup/staged candidate and checks runtime again, leaving active config unchanged.
Root owns final sequence: verified offsite server/native-config/image backup
receipt, new authoritative per-node registry, exact service stop, qualified helper
atomic commit, exact service start, actual same-node authenticated reconnection,
permanent old-global revocation and clean failure reconciliation. Never rollback
to revoked secret; pending external recovery must remain explicit.

Pure policy/private-file fixtures validate identity/fingerprint/DataDir/process
attribution/private modes/symlink/size; they do not assert actual systemd runtime
qualification. No live service/env/config was read or changed by those tests.
Native service variations, other users and EnvironmentFile path escaping are
refused until explicitly qualified. Source delivery alone is not a rotation.

## Persistent Unix permissions

For a Root-owned existing native data directory0755, Root records its private
before-mode evidence, then hardens **only that exact directory** to0700; config
must be0600. Do not relax the recovery gate, chmod recursively or touch peers'
other data. Existing JSON/node/provider/license fields remain unchanged.

Source persistence: Unix installer uses umask077 and explicitly calls qualified
Config.ensure_dirs; it hardens only its service-owned data_dir0700. Config.save
writes owner-private0600 temp, fsyncs and atomically replaces only config.json;
refuses symlink targets and foreign directory ownership. Existing nested data,
index files and sibling projects are never chmodded recursively. Docker image
creates /data/animus0700; mounted runtime directory is checked by Config logic.
Windows source keeps its separate ACL-based qualified recovery path.
Fixture regression confirms modes and unchanged neighboring/nested files, and
refuses a config symlink without changing its target. No installer or live chmod
was executed by these source tests.
