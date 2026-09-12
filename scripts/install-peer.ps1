# =============================================================================
# Animus — Kit de Instalação de Peer (Windows)
# =============================================================================
# Instala dependências (Python via winget se faltar), clona o Animus,
# configura conexão com o hub e (opcionalmente) registra uma Scheduled Task
# para rodar `animus daemon` no logon.
#
# Uso (PowerShell — abrir como administrador é opcional):
#   irm https://raw.githubusercontent.com/GuilhermeP96/animus/master/scripts/install-peer.ps1 | iex
#
# Ou interativo:
#   irm https://raw.githubusercontent.com/GuilhermeP96/animus/master/scripts/install-peer.ps1 -OutFile install-peer.ps1
#   .\install-peer.ps1
#
# Variáveis (opcionais — pulam o prompt):
#   $env:ANIMUS_HUB_URL          Default: https://animus.datano.com.br
#   $env:ANIMUS_SERVER_SECRET    Secret compartilhado com o hub (sem default)
#   $env:ANIMUS_NODE_NAME        Default: $env:COMPUTERNAME
#   $env:ANIMUS_NODE_ID          Default: uuid4[:12]
#   $env:ANIMUS_INSTALL_DIR      Default: $env:LOCALAPPDATA\animus
#   $env:ANIMUS_REPO_URL         Default: https://github.com/GuilhermeP96/animus.git
#   $env:ANIMUS_BRANCH           Default: master
#   $env:ANIMUS_INSTALL_TASK     yes|no  (default: yes)
#   $env:ANIMUS_INSTALL_CLAUDE_MCP yes|no (default: yes se houver %USERPROFILE%\.claude.json)
#     Quando 'yes', acrescenta o servidor MCP 'animus' ao .claude.json para
#     que o Claude Code consuma as memórias como ferramentas.
# =============================================================================

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$HubDefault            = 'https://animus.datano.com.br'
$RepoDefault           = 'https://github.com/GuilhermeP96/animus.git'

function Write-Step ($m) { Write-Host "⟁  $m" -ForegroundColor Cyan }
function Write-Ok   ($m) { Write-Host "✓  $m" -ForegroundColor Green }
function Write-Warn ($m) { Write-Host "!  $m" -ForegroundColor Yellow }
function Write-Err  ($m) { Write-Host "✗  $m" -ForegroundColor Red; throw $m }

function Test-Cmd($c) { [bool](Get-Command $c -ErrorAction SilentlyContinue) }

# ── 1. Dependências (Python 3.11+, git) ────────────────────────────────
function Install-Deps {
    Write-Step 'Verificando dependências...'

    $pythonOk = $false
    if (Test-Cmd python) {
        $verOut = (& python --version 2>&1) -join ' '
        if ($verOut -match '(\d+)\.(\d+)') {
            $major = [int]$Matches[1]; $minor = [int]$Matches[2]
            if ($major -gt 3 -or ($major -eq 3 -and $minor -ge 11)) { $pythonOk = $true }
        }
    }

    if (-not $pythonOk) {
        if (Test-Cmd winget) {
            Write-Step 'Instalando Python 3.13 via winget...'
            winget install --id Python.Python.3.13 --silent --accept-source-agreements --accept-package-agreements | Out-Null
        } else {
            Write-Err 'Python 3.11+ ausente e winget indisponível — instale https://www.python.org/'
        }
    }

    if (-not (Test-Cmd git)) {
        if (Test-Cmd winget) {
            Write-Step 'Instalando Git via winget...'
            winget install --id Git.Git --silent --accept-source-agreements --accept-package-agreements | Out-Null
        } else {
            Write-Err 'Git ausente — instale https://git-scm.com/'
        }
    }
    Write-Ok 'Dependências OK'
}

# ── 2. Clonar / atualizar repo ─────────────────────────────────────────
function Clone-Repo($dir, $url, $branch) {
    if (Test-Path "$dir\.git") {
        Write-Step "Atualizando repo em $dir"
        git -C $dir fetch --quiet origin $branch
        git -C $dir checkout --quiet $branch
        git -C $dir pull --quiet --ff-only origin $branch
    } else {
        Write-Step "Clonando $url → $dir"
        New-Item -ItemType Directory -Force -Path (Split-Path $dir -Parent) | Out-Null
        git clone --quiet --branch $branch --depth 1 $url $dir
    }
    Write-Ok "Source pronto em $dir"
}

# ── 3. venv + pip install -e . ─────────────────────────────────────────
function New-VenvAndInstall($dir) {
    $venv = Join-Path $dir '.venv'
    if (-not (Test-Path $venv)) {
        Write-Step 'Criando virtualenv...'
        & python -m venv $venv
    }
    $py  = Join-Path $venv 'Scripts\python.exe'
    & $py -m pip install --quiet --upgrade pip
    Write-Step 'Instalando animus (editable)...'
    & $py -m pip install --quiet -e $dir
    Write-Ok "animus instalado: $venv\Scripts\animus.exe"
}

# ── 4. Configurar peer ─────────────────────────────────────────────────
function Configure-Peer($dir, $hub, $secret, $id, $name) {
    $animus = Join-Path $dir '.venv\Scripts\animus.exe'
    $env:ANIMUS_NODE_ID   = $id
    $env:ANIMUS_NODE_NAME = $name
    & $animus init                           | Out-Null
    & $animus config-set hub_url       $hub  | Out-Null
    & $animus config-set server_secret $secret | Out-Null
    & $animus config-set node_id       $id   | Out-Null
    & $animus config-set node_name     $name | Out-Null
    Write-Ok "Peer configurado: node_id=$id  hub=$hub"
}

# ── 5. Collect + sync inicial ──────────────────────────────────────────
function Initial-Sync($dir) {
    $animus = Join-Path $dir '.venv\Scripts\animus.exe'
    Write-Step 'Coletando memórias locais...'
    try { & $animus collect } catch { Write-Warn "collect retornou erro" }
    Write-Step 'Sincronizando com o hub...'
    try { & $animus sync; Write-Ok 'Sync inicial concluído' }
    catch { Write-Warn 'Sync falhou — verifique hub_url e server_secret' }
}

# ── 6. Scheduled Task — `animus daemon` no logon ───────────────────────
function Install-Task($dir, $enabled) {
    if ($enabled -ne 'yes') { return }
    $python = Join-Path $dir '.venv\Scripts\python.exe'
    $name   = 'AnimusPeerDaemon'

    Write-Step "Registrando Scheduled Task '$name' no logon..."
    # RestartCount alto + intervalo curto sustentam o self-update: o daemon
    # detecta uma versão nova, faz `pip install --upgrade` e cai com exit
    # code 75 (EX_TEMPFAIL); o Task Scheduler restarta dentro de 1 minuto e
    # a nova versão entra no lugar — sem janela manual.
    # Do not execute animus.exe directly: Windows may lock that console
    # launcher while pip needs to replace it during an automatic update.
    $action  = New-ScheduledTaskAction -Execute $python -Argument '-m animus.cli daemon'
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
    $set     = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries `
                  -DontStopIfGoingOnBatteries `
                  -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
                  -MultipleInstances IgnoreNew `
                  -ExecutionTimeLimit (New-TimeSpan -Days 0)
    Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Settings $set `
                           -Description 'Animus Peer collector + sync daemon (self-updating)' -Force | Out-Null
    Start-ScheduledTask -TaskName $name
    Write-Ok "Task ativa — `Get-ScheduledTask $name` para ver o status"
}

function Read-DefaultedHost($prompt, $default) {
    $r = Read-Host "?  $prompt [$default]"
    if ([string]::IsNullOrWhiteSpace($r)) { return $default } else { return $r }
}

# ── 7b. Registrar MCP no Claude Code ───────────────────────────────────
# Idempotente: substitui qualquer entrada anterior em mcpServers.animus
# em vez de duplicar. Quando $env:USERPROFILE\.claude.json não existe,
# o Claude Code não está instalado para este usuário — pulamos sem erro.
function Install-ClaudeMcp($dir, $enabled) {
    if ($enabled -ne 'yes') { return }
    $cfg = Join-Path $env:USERPROFILE '.claude.json'
    if (-not (Test-Path $cfg)) {
        Write-Warn '.claude.json não encontrado — Claude Code não instalado neste usuário. Pulando MCP.'
        return
    }
    $mcp = Join-Path $dir '.venv\Scripts\animus-mcp.exe'
    if (-not (Test-Path $mcp)) { Write-Warn "$mcp ausente — pulando MCP"; return }

    Write-Step "Registrando MCP 'animus' em $cfg..."
    $py = Join-Path $dir '.venv\Scripts\python.exe'
    $script = @"
import json, sys
from pathlib import Path
p = Path(sys.argv[1])
data = json.loads(p.read_text())
data.setdefault('mcpServers', {})
data['mcpServers']['animus'] = {'command': sys.argv[2], 'args': [], 'env': {}}
p.write_text(json.dumps(data, indent=2))
print('  ok — mcpServers agora tem:', list(data['mcpServers']))
"@
    & $py -c $script $cfg $mcp
    Write-Ok 'Animus MCP registrado para Claude Code'
}

# ── Main ───────────────────────────────────────────────────────────────
Write-Host ''
Write-Host '  ⟁  ANIMUS — Peer Installation Kit (Windows)' -ForegroundColor Magenta
Write-Host '  ────────────────────────────────────────────' -ForegroundColor Magenta
Write-Host ''

$hub     = $env:ANIMUS_HUB_URL
$secret  = $env:ANIMUS_SERVER_SECRET
$nodeId  = $env:ANIMUS_NODE_ID
$nodeNm  = $env:ANIMUS_NODE_NAME
$repo    = if ($env:ANIMUS_REPO_URL)    { $env:ANIMUS_REPO_URL }    else { $RepoDefault }
$branch  = if ($env:ANIMUS_BRANCH)      { $env:ANIMUS_BRANCH }      else { 'master' }
$dir     = if ($env:ANIMUS_INSTALL_DIR) { $env:ANIMUS_INSTALL_DIR } else { Join-Path $env:LOCALAPPDATA 'animus' }
$task    = if ($env:ANIMUS_INSTALL_TASK){ $env:ANIMUS_INSTALL_TASK }else { 'yes' }
$mcp     = if ($env:ANIMUS_INSTALL_CLAUDE_MCP) { $env:ANIMUS_INSTALL_CLAUDE_MCP } `
           elseif (Test-Path (Join-Path $env:USERPROFILE '.claude.json')) { 'yes' } else { 'no' }

if ([string]::IsNullOrWhiteSpace($hub))    { $hub    = Read-DefaultedHost 'Hub URL' $HubDefault }
if ([string]::IsNullOrWhiteSpace($secret)) {
    $sec = Read-Host '?  Server secret (HMAC)' -AsSecureString
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec)
    $secret = [Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr)
}
if ([string]::IsNullOrWhiteSpace($secret)) { Write-Err 'server_secret é obrigatório' }
if ([string]::IsNullOrWhiteSpace($nodeNm)) { $nodeNm = Read-DefaultedHost 'Node name' $env:COMPUTERNAME }
if ([string]::IsNullOrWhiteSpace($nodeId)) {
    $nodeId = (& python -c 'import uuid; print(str(uuid.uuid4())[:12])').Trim()
}

Write-Step "Plano:  install_dir=$dir  hub=$hub  node_id=$nodeId  service=$task  claude-mcp=$mcp"
Write-Host ''

Install-Deps
Clone-Repo         $dir   $repo   $branch
New-VenvAndInstall $dir
Configure-Peer     $dir   $hub    $secret $nodeId $nodeNm
Initial-Sync       $dir
Install-Task       $dir   $task
Install-ClaudeMcp  $dir   $mcp

Write-Host ''
Write-Host '  ─────────────────────────────────────' -ForegroundColor Magenta
Write-Host '  ⟁  Peer registrado com sucesso'        -ForegroundColor Magenta
Write-Host '  ─────────────────────────────────────' -ForegroundColor Magenta
Write-Host ''
Write-Host "  Ativar venv:   & '$dir\.venv\Scripts\Activate.ps1'"
Write-Host '  Comandos:      animus stats  /  animus search "..." '
Write-Host "  Daemon status: Get-ScheduledTask AnimusPeerDaemon"
Write-Host ''
