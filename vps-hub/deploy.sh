#!/bin/bash
# =============================================================================
# Animus Hub — Deploy Script (VPS Hub Compatible)
# =============================================================================
# Usage from VPS Hub:
#   cd /opt/vps-hub && ./scripts/deploy.sh animus
#
# Standalone:
#   ./vps-hub/deploy.sh [--with-tunnel] [--force]
# =============================================================================

set -e

# Cores
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log() { echo -e "${BLUE}[$(date +'%H:%M:%S')]${NC} $1"; }
ok()  { echo -e "${GREEN}[✓]${NC} $1"; }
warn(){ echo -e "${YELLOW}[!]${NC} $1"; }
err() { echo -e "${RED}[✗]${NC} $1"; }

# ── Configuração ──

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Detectar se rodando via VPS Hub ou standalone
if [ -f "/opt/vps-hub/scripts/deploy.sh" ] && [ "$1" = "animus" ]; then
    PROJECT_DIR="/opt/vps-hub/animus"
else
    PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
fi

cd "$PROJECT_DIR"

WITH_TUNNEL=false
FORCE=false

for arg in "$@"; do
    case $arg in
        --with-tunnel) WITH_TUNNEL=true ;;
        --force)       FORCE=true ;;
    esac
done

# ── Pre-checks ──

log "Animus Hub deploy starting..."

if [ ! -f "docker-compose.yml" ]; then
    err "docker-compose.yml not found in $PROJECT_DIR"
    exit 1
fi

if [ ! -f ".env" ] && [ -f ".env.example" ]; then
    warn ".env not found — copying from .env.example"
    cp .env.example .env
    warn "⚠️  Edit .env and set ANIMUS_SERVER_SECRET before production use!"
fi

# ── Verificar secret ──

if [ -f ".env" ]; then
    source .env
    if [ -z "$ANIMUS_SERVER_SECRET" ]; then
        if [ "$FORCE" != "true" ]; then
            warn "ANIMUS_SERVER_SECRET is empty — generating one..."
            SECRET=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))" 2>/dev/null || openssl rand -base64 32)
            sed -i "s/^ANIMUS_SERVER_SECRET=.*/ANIMUS_SERVER_SECRET=$SECRET/" .env
            ok "Secret generated and saved to .env"
        fi
    fi
fi

# ── Build & Deploy ──

log "Pulling/building images..."
docker compose build --no-cache

log "Stopping existing containers..."
docker compose down --remove-orphans 2>/dev/null || true

if [ "$WITH_TUNNEL" = "true" ]; then
    log "Starting with chisel tunnel..."
    docker compose --profile tunnel up -d
else
    log "Starting Animus Hub..."
    docker compose up -d
fi

# ── Health Check ──

log "Waiting for health check..."
for i in $(seq 1 15); do
    STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:${ANIMUS_PORT:-8314}/health 2>/dev/null || echo "000")
    if [ "$STATUS" = "200" ]; then
        ok "Animus Hub is healthy (HTTP $STATUS)"
        break
    fi
    if [ "$i" = "15" ]; then
        err "Health check failed after 15 attempts"
        docker compose logs --tail=20
        exit 1
    fi
    sleep 2
done

# ── Status ──

echo ""
ok "════════════════════════════════════════"
ok "  Animus Hub deployed successfully!"
ok "════════════════════════════════════════"
echo ""
log "  Endpoint:  http://localhost:${ANIMUS_PORT:-8314}"
log "  Health:    http://localhost:${ANIMUS_PORT:-8314}/health"
log "  Stats:     http://localhost:${ANIMUS_PORT:-8314}/api/stats"
log "  WebSocket: ws://localhost:${ANIMUS_PORT:-8314}/ws/sync"

if [ "$WITH_TUNNEL" = "true" ]; then
    log "  Chisel:    localhost:${CHISEL_PORT:-8315}"
fi

echo ""
log "Configure peers with:"
log "  animus config set hub_url http://<VPS_IP>:${ANIMUS_PORT:-8314}"
echo ""
