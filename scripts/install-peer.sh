#!/usr/bin/env bash
# =============================================================================
# Animus — Kit de Instalação de Peer (Linux / macOS)
# =============================================================================
# Instala dependências, clona o Animus, configura conexão com o hub e
# (opcionalmente) registra um serviço systemd para coletar/sincronizar em
# background.
#
# Uso (one-liner):
#   curl -fsSL https://raw.githubusercontent.com/GuilhermeP96/animus/master/scripts/install-peer.sh | bash
#
# Ou interativo (recomendado — pergunta o secret sem ecoar):
#   curl -fsSL https://raw.githubusercontent.com/GuilhermeP96/animus/master/scripts/install-peer.sh -o install-peer.sh
#   bash install-peer.sh
#
# Variáveis de ambiente (opcionais — pulam o prompt):
#   ANIMUS_HUB_URL        Default: https://animus.datano.com.br
#   ANIMUS_SERVER_SECRET  Secret compartilhado com o hub (sem default)
#   ANIMUS_NODE_NAME      Nome humano do nó (default: hostname)
#   ANIMUS_NODE_ID        ID estável (default: uuid4[:12])
#   ANIMUS_INSTALL_DIR    Default: $HOME/.local/animus  (root → /opt/animus)
#   ANIMUS_REPO_URL       Default: https://github.com/GuilhermeP96/animus.git
#   ANIMUS_BRANCH         Default: master
#   ANIMUS_INSTALL_SERVICE  yes|no  (default: yes em Linux com systemd)
# =============================================================================

set -euo pipefail

readonly ANIMUS_HUB_URL_DEFAULT="https://animus.datano.com.br"
readonly REPO_URL_DEFAULT="https://github.com/GuilhermeP96/animus.git"

# ── Helpers ─────────────────────────────────────────────────────────────
log()  { printf '\033[1;36m⟁\033[0m  %s\n' "$*"; }
ok()   { printf '\033[1;32m✓\033[0m  %s\n' "$*"; }
warn() { printf '\033[1;33m!\033[0m  %s\n' "$*" >&2; }
err()  { printf '\033[1;31m✗\033[0m  %s\n' "$*" >&2; exit 1; }

is_root()    { [[ $EUID -eq 0 ]]; }
have_cmd()   { command -v "$1" >/dev/null 2>&1; }
detect_os()  { uname -s | tr '[:upper:]' '[:lower:]'; }

# ── 1. Detectar SO + sudo ───────────────────────────────────────────────
OS=$(detect_os)
SUDO=""
if ! is_root && have_cmd sudo; then SUDO="sudo"; fi

# ── 2. Instalar dependências (Python 3.11+, git, build essentials) ─────
install_deps() {
    log "Verificando dependências..."

    if have_cmd python3 && have_cmd git && have_cmd pip3; then
        local pyver
        pyver=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')
        if [[ $(printf '%s\n3.11\n' "$pyver" | sort -V | head -1) == "3.11" ]]; then
            ok "python3 $pyver, git, pip3 já instalados"
            return
        fi
    fi

    case "$OS" in
        linux*)
            if have_cmd apt-get; then
                $SUDO apt-get update -qq
                $SUDO apt-get install -y python3 python3-venv python3-pip git curl
            elif have_cmd dnf; then
                $SUDO dnf install -y python3 python3-pip git curl
            elif have_cmd pacman; then
                $SUDO pacman -Sy --noconfirm python python-pip git curl
            elif have_cmd apk; then
                $SUDO apk add --no-cache python3 py3-pip git curl
            else
                err "Distro Linux não suportada — instale python3.11+, git e pip manualmente"
            fi
            ;;
        darwin*)
            if ! have_cmd brew; then
                err "Homebrew necessário em macOS — https://brew.sh"
            fi
            brew list python@3.13 >/dev/null 2>&1 || brew install python@3.13
            brew list git        >/dev/null 2>&1 || brew install git
            ;;
        *)
            err "SO não suportado: $OS  (use install-peer.ps1 no Windows)"
            ;;
    esac
    ok "Dependências instaladas"
}

# ── 3. Clonar repositório ──────────────────────────────────────────────
clone_repo() {
    local install_dir=$1 repo_url=$2 branch=$3

    if [[ -d "$install_dir/.git" ]]; then
        log "Repo já existe em $install_dir — atualizando..."
        git -C "$install_dir" fetch --quiet origin "$branch"
        git -C "$install_dir" checkout --quiet "$branch"
        git -C "$install_dir" pull --quiet --ff-only origin "$branch"
    else
        log "Clonando $repo_url ($branch) → $install_dir"
        mkdir -p "$(dirname "$install_dir")"
        git clone --quiet --branch "$branch" --depth 1 "$repo_url" "$install_dir"
    fi
    ok "Source pronto em $install_dir"
}

# ── 4. Criar venv + instalar pacote ────────────────────────────────────
create_venv() {
    local install_dir=$1
    local venv="$install_dir/.venv"

    if [[ ! -d "$venv" ]]; then
        log "Criando virtualenv..."
        python3 -m venv "$venv"
    fi
    # shellcheck disable=SC1091
    source "$venv/bin/activate"
    pip install --quiet --upgrade pip
    log "Instalando animus (editable)..."
    pip install --quiet -e "$install_dir"
    ok "animus CLI disponível em $venv/bin/animus"
}

# ── 5. Configurar peer ─────────────────────────────────────────────────
configure_peer() {
    local install_dir=$1
    local hub_url=$2 secret=$3 node_id=$4 node_name=$5

    # shellcheck disable=SC1091
    source "$install_dir/.venv/bin/activate"

    log "Inicializando configuração local..."
    ANIMUS_NODE_ID="$node_id" ANIMUS_NODE_NAME="$node_name" animus init >/dev/null

    animus config-set hub_url       "$hub_url"  >/dev/null
    animus config-set server_secret "$secret"   >/dev/null
    animus config-set node_id       "$node_id"  >/dev/null
    animus config-set node_name     "$node_name" >/dev/null

    ok "Peer configurado: node_id=$node_id  hub=$hub_url"
}

# ── 6. Primeiro collect + sync (validação) ─────────────────────────────
initial_sync() {
    local install_dir=$1
    # shellcheck disable=SC1091
    source "$install_dir/.venv/bin/activate"

    log "Coletando memórias locais..."
    animus collect 2>&1 | tail -8 || warn "collect retornou erro — siga investigando manualmente"

    log "Sincronizando com o hub..."
    if animus sync 2>&1 | tail -8; then
        ok "Sync inicial concluído"
    else
        warn "Sync falhou — verifique hub_url e server_secret"
    fi
}

# ── 7. Instalar serviço systemd (opcional) ─────────────────────────────
install_service() {
    local install_dir=$1 do_install=$2
    [[ "$do_install" == "yes" ]] || return 0
    have_cmd systemctl || { warn "systemd ausente — pulando serviço"; return 0; }

    local service_path
    if is_root; then
        service_path="/etc/systemd/system/animus-peer.service"
    else
        mkdir -p "$HOME/.config/systemd/user"
        service_path="$HOME/.config/systemd/user/animus-peer.service"
    fi

    log "Gerando $service_path"
    cat > /tmp/animus-peer.service <<EOF
[Unit]
Description=Animus Peer — Collector + Sync Daemon
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=$install_dir/.venv/bin/animus daemon
Restart=on-failure
RestartSec=10
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=default.target
EOF

    if is_root; then
        $SUDO mv /tmp/animus-peer.service "$service_path"
        $SUDO systemctl daemon-reload
        $SUDO systemctl enable --now animus-peer.service
        ok "Serviço ativado: systemctl status animus-peer"
    else
        mv /tmp/animus-peer.service "$service_path"
        systemctl --user daemon-reload
        systemctl --user enable --now animus-peer.service
        ok "Serviço (user) ativado: systemctl --user status animus-peer"
    fi
}

# ── 8. Prompt interativo ───────────────────────────────────────────────
prompt_if_empty() {
    local var=$1 prompt=$2 default=${3:-} silent=${4:-false}
    local current=${!var:-}
    [[ -n "$current" ]] && return 0

    local input
    if [[ "$silent" == "true" ]]; then
        printf '\033[1;35m?\033[0m  %s: ' "$prompt"
        read -rs input
        printf '\n'
    elif [[ -n "$default" ]]; then
        printf '\033[1;35m?\033[0m  %s [%s]: ' "$prompt" "$default"
        read -r input
        input=${input:-$default}
    else
        printf '\033[1;35m?\033[0m  %s: ' "$prompt"
        read -r input
    fi
    printf -v "$var" '%s' "$input"
}

# ── Main ────────────────────────────────────────────────────────────────
main() {
    cat <<'EOF'

  ⟁  ANIMUS — Peer Installation Kit
  ────────────────────────────────────

EOF

    # Defaults
    : "${ANIMUS_HUB_URL:=}"
    : "${ANIMUS_SERVER_SECRET:=}"
    : "${ANIMUS_NODE_NAME:=}"
    : "${ANIMUS_NODE_ID:=}"
    : "${ANIMUS_REPO_URL:=$REPO_URL_DEFAULT}"
    : "${ANIMUS_BRANCH:=master}"
    : "${ANIMUS_INSTALL_DIR:=}"
    : "${ANIMUS_INSTALL_SERVICE:=}"

    if [[ -z "$ANIMUS_INSTALL_DIR" ]]; then
        if is_root; then ANIMUS_INSTALL_DIR=/opt/animus
        else             ANIMUS_INSTALL_DIR="$HOME/.local/animus"
        fi
    fi

    prompt_if_empty ANIMUS_HUB_URL       "Hub URL"             "$ANIMUS_HUB_URL_DEFAULT"
    prompt_if_empty ANIMUS_SERVER_SECRET "Server secret (HMAC)" ""               true
    [[ -z "$ANIMUS_SERVER_SECRET" ]] && err "server_secret é obrigatório"

    prompt_if_empty ANIMUS_NODE_NAME     "Node name"           "$(hostname -s 2>/dev/null || hostname)"

    if [[ -z "$ANIMUS_NODE_ID" ]]; then
        ANIMUS_NODE_ID=$(python3 -c 'import uuid; print(str(uuid.uuid4())[:12])')
    fi

    if [[ -z "$ANIMUS_INSTALL_SERVICE" ]]; then
        if [[ "$OS" == linux* ]] && have_cmd systemctl; then
            ANIMUS_INSTALL_SERVICE=yes
        else
            ANIMUS_INSTALL_SERVICE=no
        fi
    fi

    log "Plano:"
    log "  install_dir:  $ANIMUS_INSTALL_DIR"
    log "  hub_url:      $ANIMUS_HUB_URL"
    log "  node_id:      $ANIMUS_NODE_ID"
    log "  node_name:    $ANIMUS_NODE_NAME"
    log "  service:      $ANIMUS_INSTALL_SERVICE"
    echo

    install_deps
    clone_repo     "$ANIMUS_INSTALL_DIR" "$ANIMUS_REPO_URL" "$ANIMUS_BRANCH"
    create_venv    "$ANIMUS_INSTALL_DIR"
    configure_peer "$ANIMUS_INSTALL_DIR" "$ANIMUS_HUB_URL" "$ANIMUS_SERVER_SECRET" \
                   "$ANIMUS_NODE_ID" "$ANIMUS_NODE_NAME"
    initial_sync   "$ANIMUS_INSTALL_DIR"
    install_service "$ANIMUS_INSTALL_DIR" "$ANIMUS_INSTALL_SERVICE"

    cat <<EOF

  ${esc:-}─────────────────────────────────────
  ⟁  Peer registrado com sucesso
  ─────────────────────────────────────

  Próximos passos:
    source $ANIMUS_INSTALL_DIR/.venv/bin/activate
    animus stats
    animus search "alguma consulta"

  Status do daemon:
    systemctl${SUDO:+ }${SUDO:+}${SUDO:-} ${ANIMUS_INSTALL_SERVICE:+}status animus-peer

  Lembrete: o peer precisa de acesso de leitura aos dados do VS Code
  ($HOME/.config/Code/User no Linux, ~/Library/... no macOS) para coletar
  conversas/transcripts/memórias.

EOF
}

main "$@"
