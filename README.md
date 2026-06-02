# ⟁ Animus

> *"We work in the dark to serve the light."*

**Animus** é uma rede de sincronização de memórias do GitHub Copilot e do Claude Code — inspirada no Animus de Assassin's Creed. Coleta, indexa e sincroniza o contexto das suas interações com IA entre todas as suas máquinas.

## Conceito

| AC Lore | Animus System |
|---------|---------------|
| Animus | O sistema completo |
| Memórias Genéticas | Interações do Copilot, chat logs, contextos |
| Subject (Desmond) | Sua máquina — um nó peer |
| Abstergo | Hub central na VPS |
| Bleeding Effect | Cross-context: memórias de outros nós disponíveis localmente |
| Eagle Vision | Busca full-text + semântica em todas as memórias |
| Brotherhood | Rede peer-to-peer de sincronização |
| Synchronization | Processo de sync com o hub |
| Leap of Faith | CLI para entrar no Animus |

## Arquitetura

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  Machine A  │     │  Machine B  │     │  Machine C  │
│  (Subject)  │     │  (Subject)  │     │  (Subject)  │
│             │     │             │     │             │
│ ┌─────────┐ │     │ ┌─────────┐ │     │ ┌─────────┐ │
│ │Collector│ │     │ │Collector│ │     │ │Collector│ │
│ │ Indexer │ │     │ │ Indexer │ │     │ │ Indexer │ │
│ │  Peer   │ │     │ │  Peer   │ │     │ │  Peer   │ │
│ └────┬────┘ │     │ └────┬────┘ │     │ └────┬────┘ │
└──────┼──────┘     └──────┼──────┘     └──────┼──────┘
       │   HTTPS/WSS       │                   │
       └───────────┐       │       ┌───────────┘
                   ▼       ▼       ▼
            ┌──────────────────────────┐
            │      VPS Hub (Abstergo)  │
            │                          │
            │  ┌────────┐ ┌─────────┐  │
            │  │FastAPI │ │ SQLite  │  │
            │  │ Server │ │  FTS5   │  │
            │  └────────┘ └─────────┘  │
            │                          │
            │  Docker + Nginx + SSL    │
            └──────────────────────────┘
```

## O que coleta

| Fonte | Tipo | Descrição |
|-------|------|-----------|
| Copilot Chat | `copilot_chat` | Conversas de chat do Copilot |
| Debug Logs | `copilot_debug` | Logs de sessão/debug |
| `copilot-instructions.md` | `workspace_memory` | Instruções de workspace |
| `.instructions.md` | `workspace_memory` | Instruções do projeto |
| `.prompt.md` files | `prompt_file` | Prompt files customizados |
| `.agent.md` files | `agent_file` | Agentes customizados |
| `/memories/` | `user_note` | Notas persistentes do usuário |
| `/memories/session/` | `session_note` | Notas de sessão |
| `/memories/repo/` | `repo_note` | Memórias do repositório |
| MCP Memory | `mcp_knowledge` | Knowledge graph do MCP server |
| Claude Code transcripts (`~/.claude/projects/*/<sid>.jsonl`) | `claude_chat` | Turnos de sessão do Claude Code (com `session_title` derivado do primeiro prompt) |
| Claude Code auto-memory (`~/.claude/projects/*/memory/*.md`) | `claude_memory` | Memórias persistentes do Claude Code com frontmatter `name`/`description`/`metadata.type` (user/feedback/project/reference) |

## Instalação

### Peer (cada máquina)

#### Opção A — Self-install ZIP (recomendada)

No hub, abra **`/admin/peers`** → aba **📦 Self-install ZIP** → clique em
**Generate Installer ZIP**. O ZIP gerado (~8 KB) já vem com o `hub_url`,
`server_secret` e um `node_id` novo embutidos em `peer.env`.

Na máquina alvo:

```bash
# Linux / macOS
unzip animus-peer-<id>.zip && cd animus-peer-<id>
./install.sh

# Windows
# extrair o ZIP, então duplo-clique em install.bat (UAC)
```

Sem prompts — o kit já sabe tudo. Inclui `COPILOT.md`: passo-a-passo para o
GitHub Copilot fazer a instalação manual em VS Code quando o shell estiver
restrito.

#### Opção B — One-liner (irm | iex / curl | bash)

Veja a aba **🐧 Linux/macOS** ou **🪟 Windows (PowerShell)** no `/admin/peers`.

#### Opção C — Editable / dev install

```bash
cd animus
pip install -e .

# Inicializar
animus init

# Coletar memórias locais
animus collect

# Buscar (Eagle Vision)
animus search "como configurar deploy docker"

# Ver estatísticas
animus stats
```

#### Após a instalação — comandos úteis

```bash
# Status do daemon
systemctl status animus-peer            # root install
systemctl --user status animus-peer     # user install
Get-ScheduledTask AnimusPeerDaemon      # Windows

# Ver / trocar a URL do hub (use sempre a URL pública HTTPS,
# nunca um IP interno do bridge Docker — ele muda a cada restart)
animus config-show
animus config-set hub_url https://animus.datano.com.br

# Sync manual
animus sync
animus stats
```

> ⚠️ **`hub_url` precisa ser alcançável de onde o peer roda.** Se o peer
> está no host (ou em outra máquina), aponte para a URL pública (HTTPS via
> Nginx). IPs `172.x` / `10.x` do bridge Docker só funcionam para peers
> que rodam **dentro** da mesma rede do compose — e mesmo assim, prefira
> o nome do serviço (`http://animus:8314`) em vez de IP fixo.

### Hub (VPS)

```bash
# Na VPS, dentro de /opt/vps-hub/
git clone <repo> animus
cd animus

# Copiar e editar env
cp .env.example .env
# Editar .env → definir ANIMUS_SERVER_SECRET

# Deploy
./vps-hub/deploy.sh

# Ou via docker compose direto
docker compose up -d
```

### Conectar Peer ao Hub

```bash
# No peer, configurar URL do hub
animus config set hub_url https://animus.datano.com.br

# Definir o mesmo secret do hub
animus config set server_secret <MESMO_SECRET_DO_HUB>

# Sync manual
animus sync

# Ou rodar como daemon (collect + sync contínuo)
animus daemon
```

## Auto-update (peers se atualizam sozinhos)

A partir de v0.5.0 o daemon peer **checa o hub** periodicamente e instala a
versão nova sem intervenção — tanto Linux/macOS (systemd / launchd) quanto
Windows (Scheduled Task).

### Fluxo

1. Hub expõe `GET /api/version` (sem auth) com:
   ```json
   {
     "latest": "0.5.0",
     "min_compat": "",
     "channel": "stable",
     "install_url": "git+https://github.com/GuilhermeP96/animus.git",
     "git_ref": "main",
     "notes": ""
   }
   ```
2. Peer compara `latest` com `animus.__version__`. Se for mais nova, roda
   `pip install --upgrade <install_url>@<git_ref>` no mesmo venv.
3. Peer faz `os.execv` (re-exec in-place) ou sai com código `75` (EX_TEMPFAIL);
   o supervisor (systemd `Restart=always` + `SuccessExitStatus=75`, ou
   Scheduled Task com `RestartCount 999`) respawna em segundos.

### Comandos

```bash
# Ver versão local + remota
animus self-update --check

# Forçar reinstalação (mesmo já estando na versão atual — útil pós-corrupção)
animus self-update --force

# Atualizar sem reiniciar (scripts)
animus self-update --no-restart

# Desligar o auto-update no daemon
animus config-set auto_update_enabled false
animus config-set update_check_interval_seconds 21600   # 6h (default)
animus config-set update_allow_pre false                # opt-in a --pre
```

### Operacional no hub

Permite parar uma rollout / pinning sem rebuild da imagem — env vars no
container do hub (`docker compose exec` ou no `.env` do compose):

| Variável                | Efeito |
|-------------------------|--------|
| `ANIMUS_PIN_VERSION`    | Sobrescreve `latest` (ex.: `0.4.15` para travar peers) |
| `ANIMUS_GIT_REF`        | Aponta para uma tag/branch específica (`v0.5.0-rc.1`) |
| `ANIMUS_CHANNEL`        | `stable`/`beta` — informativo (clientes não bloqueiam) |
| `ANIMUS_INSTALL_URL`    | Repo alternativo (mirror, fork) |
| `ANIMUS_MIN_COMPAT`     | Versão mínima esperada (informativo) |
| `ANIMUS_RELEASE_NOTES`  | Mensagem opcional surfacede no CLI |

### Quando o peer recusa auto-update

* Install em diretório read-only / pacote do SO / `pipx` — refuses, loga e
  continua na versão atual.
* `pip` não encontrado ao lado de `sys.executable` (instalação manual fora
  de venv) — mesma resposta.
* `hub_url` vazio — pulado.

Nesses casos o operador deve reinstalar manualmente (`pip install --upgrade
git+https://github.com/GuilhermeP96/animus.git@main`) ou rodar o script
`install-peer.sh` de novo, que recria o venv writable.

## Conectividade

O Animus usa um modelo **hub-and-spoke**: peers sempre conectam **outbound** ao hub. Isso significa que **não precisa de admin, firewall rules, ou instalações complexas** nos devices.

### Opção 1: Direto (recomendado)
Se a VPS tem IP público e porta 8314 aberta:
```bash
animus config set hub_url https://animus.datano.com.br
```

### Opção 2: SSH Tunnel
Se quer rodar tudo isolado:
```bash
animus config set tunnel_mode ssh
animus config set tunnel_ssh_host SEU_VPS_IP
animus config set tunnel_ssh_user SEU_USUARIO
animus config set tunnel_ssh_key ~/.ssh/id_ed25519
animus tunnel ssh
```

### Opção 3: Chisel (single binary, sem SSH)
```bash
# No hub (VPS), ativar chisel:
docker compose --profile tunnel up -d

# No peer:
animus config set tunnel_mode chisel
animus tunnel chisel
```

### Opção 4: Cloudflare Tunnel (HTTPS grátis)
```bash
animus tunnel cloudflared
```

## Compatibilidade VPS Hub

O Animus é 100% compatível com o VPS Hub (`/opt/vps-hub/`):

```bash
# Deploy via VPS Hub
cd /opt/vps-hub
./scripts/deploy.sh animus

# Ou standalone
cd /opt/vps-hub/animus
./vps-hub/deploy.sh
```

Arquivos de integração:
- `vps-hub/deploy.sh` — Script de deploy compatível
- `vps-hub/animus.service` — Systemd service
- `vps-hub/nginx.conf` — Nginx reverse proxy (SSL/WebSocket)

## API

O hub expõe uma API REST + WebSocket:

| Endpoint | Método | Descrição |
|----------|--------|-----------|
| `/` | GET | Status do hub |
| `/health` | GET | Health check |
| `/api/stats` | GET | Estatísticas |
| `/api/sync/push` | POST | Enviar memórias |
| `/api/sync/pull` | POST | Receber memórias |
| `/api/search` | POST | Buscar (Eagle Vision) |
| `/api/memories/recent` | GET | Memórias recentes |
| `/api/peers` | GET | Peers conectados |
| `/ws/sync` | WS | Sync em tempo real |
| `/docs` | GET | Swagger UI |

## CLI Commands

```
animus init          # Inicializar no device
animus collect       # Coletar memórias
animus search QUERY  # Buscar (Eagle Vision)
animus stats         # Estatísticas
animus sync          # Sync com hub
animus daemon        # Daemon (collect + sync loop)
animus serve         # Rodar como hub
animus tunnel MODE   # Iniciar tunnel (ssh|chisel|cloudflared)
animus config-show   # Ver configuração
animus config-set K V # Alterar configuração
```

## Segurança

- HMAC-SHA256 para autenticação peer-to-peer
- Timestamp validation (replay protection, 5min window)
- Shared secret derivation per-node
- HTTPS/WSS em produção (via nginx + certbot)
- Sem dados sensíveis no conteúdo (tokens, passwords são filtrados)
- Outbound-only connections (sem necessidade de abrir portas no peer)

## Stack

- **Python 3.10+**
- **FastAPI** + **Uvicorn** — HTTP/WebSocket server
- **SQLite FTS5** — Full-text search engine
- **httpx** — Async HTTP client
- **websockets** — WebSocket client
- **watchdog** — File system monitoring
- **Typer** + **Rich** — CLI
- **Docker** — Hub deployment
- **Chisel** (opcional) — TCP tunnel

## License

MIT
