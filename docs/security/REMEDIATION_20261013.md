# Animus security and latency remediation

Tracks [Animus #5](https://github.com/GuilhermeP96/animus/issues/5), [Animus #2](https://github.com/GuilhermeP96/animus/issues/2) and Hub #48. This source work preserves the Cloudflare Access client-header feature 52ba409 and imports the earlier fallback removal ce2e49. No active key, service, external peer, data or configuration has been changed by this workstream.

## Cheap truthful readiness and bounded statistics

`/health` opens a separate read-only SQLite connection with 250 ms busy timeout and reads the real schema plus SELECT 1. It does not wait for the application's writer/count lock or scan memories. A missing/corrupt/unreadable DB returns 503 with a generic unavailable status. Liveness remains the separate cheap process endpoint `/health/live`.

Counts in readiness are nullable: they are included only when a valid 30-second stats cache exists, with explicit age. Missing/expired counts do not invent zero. Readiness does not claim integrity verification, backlog completion or proof of a successful backup/restore. SQLite schema readability is a narrow operational check.

`get_stats` uses covering-index counts rather than reading large content rows into a combined aggregation, caches for 30 seconds, bounds lock wait to 250 ms and SQL work to a two-second progress budget. Owned writes invalidate counts. The authenticated stats routes and admin pages offload counts to a worker thread so they do not block the async event loop. A failed detailed stats request returns 503; no healthy flag or fresh counts are fabricated. A push acknowledgement may return null total when no current counts are cached; pushed memory acknowledgement remains authoritative.

Performance proof here is isolated SQLite fixtures (including real writer-lock contention and corruption). The reported production 9–11.6s baseline still requires before/after probes on the actual deployed artifact. Fixture timings are not production SLO or capacity-under-peak evidence.

## Fail-closed peer trust, nonce and replay

Missing credentials now deny REST/WS. An unsigned local fixture requires explicit `ANIMUS_ALLOW_INSECURE_DEV_AUTH=True`, loopback server_host and no registry/secret. This is a test setting, not network isolation: bind loopback/private ingress and never enable it on published hosts.

Nonce is strict by default (`ANIMUS_REQUIRE_NONCE=1`). Legacy mode requires explicit opt-out and is unsuitable for production. Invalid signatures are rejected before consuming a nonce; successful verification consumes it atomically. Live replay-cache entries cannot be evicted to make an older nonce reusable: saturation rejects new authenticated requests until expiry. Future timestamp skew remains covered for its entire validity interval. Header identity/nonce/signature sizes and shapes are bounded. WS handshake waits at most 10 seconds and is bounded to 8 KiB; established sockets check the current per-node credential before each new message.

The replay store is process-local. Deploy the current single-worker profile; this does not prove replay persistence across process restarts or independent multiworker instances. A multiworker/restart-persistent nonce store remains a separate hardening requirement if that topology is introduced. Historical requests also do not bind HTTP method/path; the existing wire format binds node, time, nonce and body, so route-bound signing would require a coordinated protocol upgrade. Do not claim that these remaining protocol limits were independently pentested.

The former leaked fallback's SHA256 fingerprint is permanently denied by source verification/signing. The raw value is not reproduced in source or documentation. Removing a secret from Git history does not rotate any runtime; it remains compromised forever. Do not re-enable it during staged delivery or rollback.

## Operator-installed per-node registry

`ANIMUS_SERVER_PEER_KEYS_FILE` enables a version1 JSON registry installed by the operator through an independently authenticated path. It must be a regular non-symlink 0600 file owned by root or the service UID, no larger than 64 KiB and with at most 1024 entries. Each enabled entry contains its own generated base64url credential. No shared-secret fallback is allowed for unknown/disabled nodes. Atomic file replacement changes the credential snapshot. Preserve actual existing node IDs; never assign identities from display names.

Shape (shown with placeholders, never copy placeholders as credentials):

```json
{"version":1,"peers":{"existing-node-id":{"enabled":true,"secret":"GENERATED_PRIVATE_BASE64URL_CREDENTIAL"}}}
```

Operator must prepare a source-only package and private registry outside Git. Installer kits resolve the selected node's key when this registry is enabled; global-secret reveal refuses the per-node mode. A valid existing key is sufficient to retrieve its own same-key update kit, never a recovery trust channel for replacing a compromised key. Existing admin JWT signing uses only the independent ANIMUS_ADMIN_SECRET; no fallback to peer/server HMAC remains. Do not rotate or overwrite that separate administrative credential while rotating peers.

## Recovery channels for the three currently observed peers

Inventory reported three online peers before this work. This work has not accessed external Windows or independently validated possession of any external credential. Root-managed native VPS/service configuration can be updated directly via existing root-authorized local/SSH administration, retaining its node ID, registry and independent admin secret. Root must map each of the three actual node IDs to the respective runtime and record evidence privately.

An external Windows peer using only the compromised old shared HMAC has **no independently authenticated recovery channel demonstrated yet**. Product-license entitlement by node ID is not proof that a caller possesses an independent secret/private key. Cloudflare service-token headers are not trustworthy unless the edge application policy validates the token and ingress prevents bypass; the new optional client headers alone do not prove that policy. A downloaded update kit authorized with the old HMAC cannot be used to deliver a new secret. Never use these as recovery shortcuts.

Acceptable channels after independent verification: existing authorized SSH/public-key management, independently verified per-device administrative/license credential, or an existing correctly configured Cloudflare Access device identity/token with enforced origin policy. If none exists, the owner must verify the recipient key through an independent administrative session. That is an indispensable identity/channel decision; technical packaging and reconciliation remain owner=agent.

## Bounded encrypted delivery preparation

`scripts/security/prepare-peer-rotation.py` accepts an operator-approved mapping of existing node IDs to independently verified X25519 recipient public keys, SHA256 fingerprints and channel references. It creates a new 0700 directory, a 0600 registry and 0600 encrypted recovery envelopes. It does not update any active file, contact peers or activate credentials. Keys are generated independently per node; no raw key is printed. Envelopes bind node ID, rotation ID, recipient fingerprint and a one-hour expiry using X25519/HKDF/AES-GCM.

The receiver must use `credential_rotation.unseal` with its private key and the expected node, rotation and **package digest received independently from the operator**. Encryption alone does not authenticate the sender: anyone with a recipient public key can encrypt a different secret. The digest is mandatory, not inferred from an old-HMAC message or the package being decrypted. Root has to preserve the approval/receipt and verify external actual decryption through the independent session; isolated fixture decryption does not prove Windows installation.

Example preparation (all files private; no secrets in command arguments):

```bash
python scripts/security/prepare-peer-rotation.py \
  --approved-recipients PRIVATE_APPROVAL_FILE \
  --private-output NEW_PRIVATE_DIRECTORY \
  --rotation-id APPROVED_ROTATION_ID
```

Private approval records contain `public_key` (base64 raw 32-byte X25519), `verified_sha256` and `independent_channel` with an explicit supported method and privately retained evidence_id; a label is not proof of actual verification. The output receipt contains only node-envelope hashes, rotation ID, expiry, count and activated=false. Do not send plaintext registry by mail/issues/chat. Checkpoint private current config/data and generated artifacts through canonical SharePoint upload/listing/size/full streamed download/SHA256/0600 receipt before deleting local payloads.

## Serialized application and rollback

1. Root acquires the common capacity lease/reserve 5 GiB, records actual base image/codename, source SHA, package/DB/checkpoint hashes and unrelated container IDs. Preserve configured independent admin secret and all peer identities. Classify offline peers too.
2. Independently verify each recipient/recovery channel. Prepare encrypted per-node delivery and manifests. Deliver code and recipient key through that channel; old HMAC never grants provisioning/recovery. Confirm every external peer's installation privately.
3. Quiesce old trust paths during cutover. Atomically install the private registry and per-peer configs, enable strict nonce, remove revoked shared key from active configs and installer material, and restart/recreate only the affected Animus runtime/native peer services. There is no grace period accepting the compromised old key. A temporary peer disconnect during verified cutover is safer than maintaining compromised trust.
4. Prove that old key, anonymous/unknown nodes, bad signature, reused nonce and cross-node credentials are rejected; newly provisioned identities reconnect/sync; administrative authentication remains configured with the separate original credential. Probe readiness/stats latency without copying memory content/logs into Git.
5. Failures keep revoked trust blocked; restore code/image only if it enforces revocation too, using fresh credentials and preserved identities. Never restore an old env/kit containing the revoked key as an operational rollback. Keep secure recovery pending for an unverified external peer.
6. Record exact artifact digest, before/after measurements, auth rejection/convergence evidence and SharePoint receipt. Close issue #5 only after actual rotation/revocation is proved. Source tests and the earlier PR #6 alone are insufficient.

## Dependencies, build provenance and VPS CI

PyJWT candidate is pinned 2.15.1; official [changelog](https://pyjwt.readthedocs.io/en/stable/changelog.html) documents the compatible security/parsing fixes. Existing host test environment has PyJWT 2.12.1, so candidate runtime 2.15.1 still requires isolated build/tests. Read-only runtime metadata confirmed Python 3.12.14/Debian trixie. Dockerfile fixes the explicit Python 3.12 Debian trixie family and verifies BASE_CODENAME against /etc/os-release and updates packages within that family; remove the failed install step previously swallowed with `||true`. Before deployment, confirm actual current base codename; resolve Python base to its immutable vendor digest, retain final image/package inventory and rescan the artifact against official Debian/OSV feeds. Never upgrade host APT or change OS major under this patch.

Hosted Dependabot configuration was removed according to machine policy. `scripts/ci/validate.sh` is a bounded VPS-only focused offline gate, with no install/network/hosted Actions, and excludes the legacy live VPS diagnostic. The existing wider VPS scheduler/matrix must invoke this source; no new production schedule was activated here.

Validation: the final persisted focused gate passed140 tests; earlier137 tests passed in1.96s and136 tests in11.34s using the existing prepared /opt/animus-peer Python environment, source isolated, no package installation/container/new service/external peer. Coverage includes real SQLite/HMAC/thread race/cache saturation/future timestamp expiry/deletion invalidation, per-node authority/file modes/atomic replacement, encrypted-envelope integrity/binding and private preparation artifacts, auth profile regression and existing licensing/config/server/engine tests. Seven edited Python sources parsed and git diff --check passed. Two initial fixture tests failed (WAL recovery kept the intentionally damaged old fixture valid; sample count was 7 not 6); corrected to a separate genuinely corrupt DB and actual fixture cardinality, then focused 90 tests passed before the expanded 136-test run and 137-test persisted gate.

DatanO AppSec/SRE source guidance applied: independently verified trust, bounded resources, gradual release, recoverable evidence and no simulated native gate. No claim of physical rotation, deployed latency improvement, final package qualification or pentest approval is made by this source preparation.
