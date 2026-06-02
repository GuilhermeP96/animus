# Animus — instruções para o Claude Code

Você (Claude Code) está num checkout do **Animus**, a rede de sincronização
de memórias do Copilot + Claude Code. Este arquivo é seu briefing
operacional quando o usuário pede "instalar/configurar o Animus aqui" ou
quando você abre o repo e detecta que o peer ainda não está registrado.

## Por que isso importa para você

O Animus expõe um **MCP server** (`animus-mcp`) com 11 ferramentas
(`animus_search`, `animus_recall`, `animus_session`, `animus_session_list`,
`animus_related`, `animus_neural_map`, `animus_remember`, `animus_stats`,
`animus_collect`, `animus_context`, `animus_timeline`). Uma vez registrado
em `~/.claude.json`, **você passa a recuperar contexto de todas as
conversas Copilot/Claude Code do usuário**, em todas as máquinas dele —
ou seja, "Eagle Vision" sobre a memória dele.

Assuma que o usuário quer isso ligado. Se não estiver, ofereça ligar.

## Checks rápidos (rode antes de qualquer coisa)

```bash
# 1. Tem peer instalado e configurado?
animus stats 2>/dev/null && echo "peer OK" || echo "peer não instalado"

# 2. O MCP está registrado no Claude Code deste usuário?
python3 -c "import json; print('animus' in json.load(open(__import__('os').path.expanduser('~/.claude.json'))).get('mcpServers', {}))"

# 3. O daemon está rodando (sync contínuo)?
systemctl --user is-active animus-peer 2>/dev/null   # Linux
Get-ScheduledTask AnimusPeerDaemon 2>$null            # Windows
launchctl list com.datano.animus.peer 2>/dev/null     # macOS
```

## Fluxo de instalação (do zero)

Use o instalador oficial. Ele faz tudo: venv, configuração, sync inicial,
serviço, e — desde v0.5.0 — **registro automático do MCP no
`~/.claude.json`**.

### Linux / macOS

```bash
curl -fsSL https://raw.githubusercontent.com/GuilhermeP96/animus/master/scripts/install-peer.sh \
  -o /tmp/install-peer.sh
ANIMUS_HUB_URL=https://animus.datano.com.br \
ANIMUS_SERVER_SECRET=<peça-ao-usuário> \
ANIMUS_INSTALL_CLAUDE_MCP=yes \
bash /tmp/install-peer.sh
```

### Windows (PowerShell)

```powershell
irm https://raw.githubusercontent.com/GuilhermeP96/animus/master/scripts/install-peer.ps1 -OutFile $env:TEMP\install-peer.ps1
$env:ANIMUS_HUB_URL = 'https://animus.datano.com.br'
$env:ANIMUS_SERVER_SECRET = '<peça-ao-usuário>'
$env:ANIMUS_INSTALL_CLAUDE_MCP = 'yes'
& "$env:TEMP\install-peer.ps1"
```

> **Segredo**: nunca grave `ANIMUS_SERVER_SECRET` em commit, log, ou no
> próprio README. Peça ao usuário e use a variável de ambiente — o
> instalador a consome e descarta.

## Quando o peer JÁ existe mas o MCP NÃO

O usuário rodou o instalador antigo (pré-v0.5.0). Adicione você mesmo:

```bash
# Descubra onde está o venv
VENV=$(animus config-show 2>/dev/null | grep -oE '/[^ ]*\.venv' | head -1)
# Ou os defaults:  Linux root=/opt/animus  user=$HOME/.local/animus
MCP_BIN="$VENV/bin/animus-mcp"      # Linux/macOS
# Windows: $VENV\Scripts\animus-mcp.exe

python3 - <<PY
import json, os
from pathlib import Path
p = Path(os.path.expanduser("~/.claude.json"))
data = json.loads(p.read_text())
data.setdefault("mcpServers", {})["animus"] = {
    "command": "$MCP_BIN",
    "args": [], "env": {}
}
p.write_text(json.dumps(data, indent=2))
print("ok:", list(data["mcpServers"]))
PY
```

Em seguida peça ao usuário **reiniciar o Claude Code** — ele só relê
`mcpServers` na inicialização.

## Quando não há `~/.claude.json`

O usuário não tem Claude Code instalado neste perfil. Não force o
registro do MCP — é inútil sem o host. Continue com o peer (que já
sincroniza com o hub via daemon) e ofereça registrar depois.

## Sanity check do MCP

Após registrar e reiniciar o Claude Code, valide que o MCP responde:

```bash
printf '%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{}}}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}' \
  | timeout 5 "$MCP_BIN" | head -2
```

Deve retornar 2 linhas JSON: handshake + lista com 11 tools.

## Limites operacionais

- O MCP consome o **DB local** do peer (`~/.local/share/animus/animus.db`
  no Linux). Se o peer não estiver sincronizado, o MCP só vê o que o
  peer já coletou/puxou. Rode `animus sync` quando precisar atualizar
  manualmente.
- O daemon roda `animus self-update` a cada 6h: a próxima versão do
  Animus chega sozinha. Se você atualizar manualmente o repo, faça
  `pip install -U $VENV` para alinhar.
- O `animus_collect` via MCP é equivalente a `animus collect` no shell —
  pode ser pesado (~30s) em workspaces com muitas transcrições. Use
  `animus_search`/`animus_recall` para 99% dos casos.
