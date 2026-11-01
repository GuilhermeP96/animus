# Animus — instruções para o Claude Code

Você (Claude Code) está num checkout do **Animus**, a rede de sincronização
de memórias do Copilot + Claude Code. Este arquivo é seu briefing
operacional quando o usuário pede "instalar/configurar o Animus aqui" ou
quando você abre o repo e detecta que o peer ainda não está registrado.

## Por que isso importa para você

O Animus expõe um **MCP server** (`animus-mcp`) com 16 ferramentas
(`animus_search`, `animus_recall`, `animus_session`, `animus_session_list`,
`animus_related`, `animus_neural_map`, `animus_remember`, `animus_stats`,
`animus_collect`, `animus_context`, `animus_timeline`,
`animus_obsidian_guide`, `animus_obsidian_search`, `animus_obsidian_export`, `animus_obsidian_organize`,
`animus_obsidian_dataset`). Antes de organizar ou promover conhecimento do
Obsidian, consulte obrigatoriamente `animus_obsidian_guide`. Uma vez registrado
em `~/.claude.json`, **você passa a recuperar contexto de todas as
conversas Copilot/Copilot CLI/Claude Code/Antigravity do usuário**, em todas as
máquinas dele — ou seja, "Eagle Vision" sobre a memória dele.

A partir de v0.5.1 o `animus collect` também indexa memórias do Google
Antigravity / Antigravity IDE (`~/.gemini/antigravity/conversations/*.db`,
`brain/`, `GEMINI.md`, `config/projects/*.json` e `.antigravity/mcp.json`
nos workspaces). Colete somente fontes autorizadas pelo usuário; não habilite fontes por suposição.

A partir de v0.6.0 o `animus collect` também indexa sessões do **GitHub
Copilot CLI** (`~/.copilot/session-store.db` — turns e checkpoints, tipo
`copilot_cli_chat`). Peers pré-v0.6.0 rejeitam essas memórias no pull
(`'copilot_cli_chat' is not a valid MemoryType`) até se auto-atualizar —
mesmo caminho de migração do `claude_chat` na v0.5.0.

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

# 4. O peer está atualizado? (assinatura de versão antiga no log)
#    Se aparecer "claude_chat is not a valid MemoryType" ou "Pulled N, 0 new"
#    com o hub tendo memórias do Claude → peer pré-v0.5.0, ver "Diagnóstico" abaixo.
grep -cE "is not a valid MemoryType" ~/.animus/daemon.log 2>/dev/null   # >0 = peer desatualizado
```

## Fluxo de instalação (do zero)

Use o instalador oficial. Ele faz tudo: venv, configuração, sync inicial,
serviço, e — desde v0.5.0 — **registro automático do MCP no
`~/.claude.json`**.

### Linux / macOS

```bash
curl -fsSL https://raw.githubusercontent.com/GuilhermeP96/animus/master/scripts/install-peer.sh \
  -o /tmp/install-peer.sh
ANIMUS_HUB_URL=https://animus.example.com \
ANIMUS_SERVER_SECRET=<configure-localmente> \
ANIMUS_INSTALL_CLAUDE_MCP=yes \
bash /tmp/install-peer.sh
```

### Windows (PowerShell)

```powershell
irm https://raw.githubusercontent.com/GuilhermeP96/animus/master/scripts/install-peer.ps1 -OutFile $env:TEMP\install-peer.ps1
$env:ANIMUS_HUB_URL = 'https://animus.example.com'
$env:ANIMUS_SERVER_SECRET = '<configure-localmente>'
$env:ANIMUS_INSTALL_CLAUDE_MCP = 'yes'
& "$env:TEMP\install-peer.ps1"
```

> **Segredo**: nunca peça credenciais no chat nem as grave em commit, log ou README.
> O operador deve fornecê-las por um canal local seguro, fora da conversa.

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

## Diagnóstico: peer desatualizado (memórias do Claude não sincronizam)

Assinatura no `~/.animus/daemon.log` de um peer **pré-v0.5.0**:

```
[animus.sync] WARNING: Skipping malformed memory: 'claude_chat' is not a valid MemoryType   ← repetido milhares de vezes
[animus.peer]  INFO:    Pulled 1 memories, 0 new                                             ← descarta tudo que vem do hub
```

A v0.5.0 introduziu o tipo `claude_chat` e o `ClaudeCollector`. Um peer
anterior **rejeita toda memória do Claude** que o hub envia (transporte
funciona, mas o schema não conhece o tipo). O MCP antigo também expõe só
7 tools em vez de 11. Correção:

```bash
# Descubra o diretório do install editable (git checkout) e o venv:
#   Windows: %LOCALAPPDATA%\animus     Linux root: /opt/animus     user: ~/.local/animus
git -C "$dir" pull origin master
"$venv/bin/python" -m pip install -e "$dir"   # só necessário se pyproject mudou deps
```

Depois **reinicie o daemon** — o processo em memória NÃO recarrega o código sozinho:

```bash
systemctl --user restart animus-peer                              # Linux
Stop-ScheduledTask AnimusPeerDaemon; Start-ScheduledTask AnimusPeerDaemon   # Windows
launchctl kickstart -k gui/$UID/com.datano.animus.peer            # macOS
```

No próximo ciclo o log deve mostrar `vX.Y.Z starting` (≥0.5.0), zero avisos
`MemoryType`, e `Collected ... N new` / `Pulled ... N new` com N>0 — sinal de
que as memórias do Claude finalmente entram.

> **Credenciais Git**: use o gerenciador de credenciais configurado. Nunca inclua tokens na URL, em argumentos ou logs.

## Sanity check do MCP

Após registrar e reiniciar o Claude Code, valide que o MCP responde:

```bash
printf '%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{}}}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}' \
  | timeout 5 "$MCP_BIN" | head -2
```

Deve retornar 2 linhas JSON: handshake + lista com 16 tools.

## Limites operacionais

- O MCP consome o **DB local** do peer (`~/.local/share/animus/animus.db`
  no Linux). Se o peer não estiver sincronizado, o MCP só vê o que o
  peer já coletou/puxou. Rode `animus sync` quando precisar atualizar
  manualmente.
- O daemon roda `animus self-update` a cada 6h: a próxima versão do
  Animus chega sozinha (peers ≥v0.5.0; `auto-update=True` no log de
  startup confirma). Se atualizar manualmente o repo, é `git pull` +
  reiniciar o daemon — **não** basta o `git pull`, o processo em memória
  só recarrega o código no restart. Veja "Diagnóstico: peer desatualizado".
- O `animus_collect` via MCP é equivalente a `animus collect` no shell —
  pode ser pesado (~30s) em workspaces com muitas transcrições. Use
  `animus_search`/`animus_recall` para 99% dos casos.
