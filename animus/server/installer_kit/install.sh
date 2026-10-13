#!/usr/bin/env bash
# =============================================================================
# Animus Peer Installer Kit — self-bootstrapping wrapper
# -----------------------------------------------------------------------------
# Reads peer.env (pre-baked by the hub with hub_url, secret, node_id, node_name)
# and downloads + runs the canonical install-peer.sh from the configured repo.
#
# Usage:
#   ./install.sh                # interactive (won't ask anything — env is set)
#   bash install.sh
# =============================================================================
set -euo pipefail

here() { cd "$(dirname "${BASH_SOURCE[0]}")" && pwd; }
HERE=$(here)
ENV_FILE="$HERE/peer.env"

if [[ ! -f "$ENV_FILE" ]]; then
    echo "✗  peer.env not found next to install.sh — did you extract the ZIP fully?" >&2
    exit 1
fi

# Load peer.env into the environment.
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

if [[ -z "${ANIMUS_SERVER_SECRET:-}" || "${ANIMUS_SERVER_SECRET}" == "{{SECRET}}" ]]; then
    echo "✗  peer.env has no ANIMUS_SERVER_SECRET — regenerate the installer ZIP from the hub." >&2
    exit 1
fi

REPO=${ANIMUS_REPO_URL:-https://github.com/GuilhermeP96/animus.git}
BRANCH=${ANIMUS_BRANCH:-licensing-managment}
RAW_BASE=${ANIMUS_RAW_BASE:-${REPO%.git}}
RAW_BASE=${RAW_BASE/github.com/raw.githubusercontent.com}

URL="${RAW_BASE}/${BRANCH}/scripts/install-peer.sh"

echo "⟁  Animus Peer — self-install"
echo "    hub:     $ANIMUS_HUB_URL"
echo "    node_id: $ANIMUS_NODE_ID"
echo "    name:    $ANIMUS_NODE_NAME"
echo "    source:  $URL"
echo

if command -v curl >/dev/null 2>&1; then
    curl -fsSL "$URL" | bash
elif command -v wget >/dev/null 2>&1; then
    wget -qO- "$URL" | bash
else
    echo "✗  Neither curl nor wget available. Install one and retry, or follow COPILOT.md." >&2
    exit 1
fi
