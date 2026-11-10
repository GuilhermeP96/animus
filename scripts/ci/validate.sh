#!/usr/bin/env bash
# Offline gate; the trusted local CI registry selects a prepared interpreter.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."
if [[ -e .env ]]; then
    echo 'Use an isolated source-only checkout for validation' >&2
    exit 1
fi
exec timeout 180 "${ANIMUS_TEST_PYTHON:-python3}" scripts/ci/validate.py
