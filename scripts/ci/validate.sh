#!/usr/bin/env bash
# Offline focused security gate; run on the VPS with a prepared Python env.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."
if [[ -e .env ]]; then
    echo 'Use an isolated source-only checkout for validation' >&2
    exit 1
fi
export PYTHONDONTWRITEBYTECODE=1
exec timeout 120 "${ANIMUS_TEST_PYTHON:-python3}" -m pytest -q -p no:cacheprovider \
    tests/test_security_remediation.py tests/test_crypto.py tests/test_engine.py \
    tests/test_server.py tests/test_admin_auth.py tests/test_config.py \
    tests/test_sync.py tests/test_licensing.py
