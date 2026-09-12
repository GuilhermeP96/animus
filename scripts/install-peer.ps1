# =============================================================================
# Animus - Kit de Instalacao de Peer (Windows)
# =============================================================================
# Instala dependencias (Python via winget se faltar), clona o Animus,
# configura conexao com o hub e (opcionalmente) registra uma Scheduled Task
# para rodar `animus daemon` no logon.
#
# Uso (PowerShell - abrir como administrador e opcional):
#   irm https://raw.githubusercontent.com/GuilhermeP96/animus/master/scripts/install-peer.ps1 | iex
#
# Ou interativo:
#   irm https://raw.githubusercontent.com/GuilhermeP96/animus/master/scripts/install-peer.ps1 -OutFile install-peer.ps1
#   .\install-peer.ps1
#
# Variaveis (opcionais - pulam o prompt):
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
#     que o Claude Code consuma as memorias como ferramentas.
# =============================================================================

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$HubDefault            = 'https://animus.datano.com.br'
$RepoDefault           = 'https://github.com/GuilhermeP96/animus.git'

function Write-Step ($m) { Write-Host ">> $m" -ForegroundColor Cyan }
function Write-Ok   ($m) { Write-Host "OK $m" -ForegroundColor Green }
function Write-Warn ($m) { Write-Host "!  $m" -ForegroundColor Yellow }
function Write-Err  ($m) { Write-Host "X  $m" -ForegroundColor Red; throw $m }

function Test-Cmd($c) { [bool](Get-Command $c -ErrorAction SilentlyContinue) }

function Assert-NativeSuccess($operation) {
    if ($LASTEXITCODE -ne 0) {
        Write-Err "$operation falhou (codigo $LASTEXITCODE)"
    }
}

# -- 1. Dependencias (Python 3.11+, git) --------------------------------
function Install-Deps {
    Write-Step 'Verificando dependencias...'

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
            Write-Err 'Python 3.11+ ausente e winget indisponivel - instale https://www.python.org/'
        }
    }

    if (-not (Test-Cmd git)) {
        if (Test-Cmd winget) {
            Write-Step 'Instalando Git via winget...'
            winget install --id Git.Git --silent --accept-source-agreements --accept-package-agreements | Out-Null
        } else {
            Write-Err 'Git ausente - instale https://git-scm.com/'
        }
    }
    Write-Ok 'Dependencias OK'
}

# -- 2. Clonar / atualizar repo -----------------------------------------
function Clone-Repo($dir, $url, $branch) {
    if (Test-Path "$dir\.git") {
        Write-Step "Atualizando repo em $dir"
        git -C $dir fetch --quiet origin $branch
        Assert-NativeSuccess 'git fetch'
        git -C $dir checkout --quiet $branch
        Assert-NativeSuccess 'git checkout'
        git -C $dir pull --quiet --ff-only origin $branch
        Assert-NativeSuccess 'git pull --ff-only'
    } else {
        Write-Step "Clonando $url -> $dir"
        New-Item -ItemType Directory -Force -Path (Split-Path $dir -Parent) | Out-Null
        git clone --quiet --branch $branch --depth 1 $url $dir
        Assert-NativeSuccess 'git clone'
    }
    Write-Ok "Source pronto em $dir"
}

# -- 3. venv + pip install -e . -----------------------------------------
function New-VenvAndInstall($dir) {
    $venv = Join-Path $dir '.venv'
    if (-not (Test-Path $venv)) {
        Write-Step 'Criando virtualenv...'
        & python -m venv $venv
    }
    $py  = Join-Path $venv 'Scripts\python.exe'
    & $py -m pip install --quiet --upgrade pip
    Assert-NativeSuccess 'pip upgrade'
    Write-Step 'Instalando animus (editable)...'
    & $py -m pip install --quiet -e $dir
    Assert-NativeSuccess 'pip install'
    Write-Ok "animus instalado: $venv\Scripts\animus.exe"
}

# Stop the existing task and processes launched from this peer's venv before
# pip replaces console launchers. Windows locks animus.exe/animus-mcp.exe while
# they are running, which used to leave updates half-installed.
function Enter-PeerMaintenance($dir) {
    $name = 'AnimusPeerDaemon'
    $task = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
    $wasInstalled = $null -ne $task
    $wasRunning = $wasInstalled -and $task.State -eq 'Running'

    if ($wasRunning) {
        Write-Step "Parando Scheduled Task '$name' para atualizar..."
        Stop-ScheduledTask -TaskName $name -ErrorAction Stop
    }

    $venv = [IO.Path]::GetFullPath((Join-Path $dir '.venv')).TrimEnd('\') + '\'
    $processes = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        $_.ExecutablePath -and $_.ExecutablePath.StartsWith(
            $venv, [StringComparison]::OrdinalIgnoreCase
        )
    })
    $processIds = @($processes | ForEach-Object { [int]$_.ProcessId })
    $roots = @($processes | Where-Object { $processIds -notcontains [int]$_.ParentProcessId })
    foreach ($process in $roots) {
        Write-Step "Encerrando $($process.Name) (PID $($process.ProcessId)) para liberar o venv..."
        & taskkill.exe /PID $process.ProcessId /T /F 2>$null | Out-Null
    }

    $deadline = [DateTime]::UtcNow.AddSeconds(10)
    do {
        $remaining = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
            $_.ExecutablePath -and $_.ExecutablePath.StartsWith(
                $venv, [StringComparison]::OrdinalIgnoreCase
            )
        })
        if ($remaining.Count -eq 0) { break }
        Start-Sleep -Milliseconds 200
    } while ([DateTime]::UtcNow -lt $deadline)

    if ($remaining.Count -gt 0) {
        # Continue into the guarded install block. If pip still cannot replace
        # a locked file it will fail loudly and the finally block restores the
        # previous Scheduled Task.
        Write-Warn "Ainda ha processos no ambiente virtual em $venv"
    }
    [pscustomobject]@{ TaskInstalled = $wasInstalled; TaskWasRunning = $wasRunning }
}

function Restore-PeerTask($maintenance) {
    if ($maintenance.TaskInstalled -and $maintenance.TaskWasRunning) {
        Write-Warn 'Restaurando o daemon anterior apos falha na atualizacao...'
        Start-ScheduledTask -TaskName 'AnimusPeerDaemon' -ErrorAction SilentlyContinue
    }
}

# -- 4. Configurar peer -------------------------------------------------
function Configure-Peer($dir, $hub, $secret, $id, $name) {
    $animus = Join-Path $dir '.venv\Scripts\animus.exe'
    $env:ANIMUS_NODE_ID   = $id
    $env:ANIMUS_NODE_NAME = $name
    & $animus init                           | Out-Null
    Assert-NativeSuccess 'animus init'
    & $animus config-set hub_url       $hub  | Out-Null
    Assert-NativeSuccess 'config-set hub_url'
    & $animus config-set server_secret $secret | Out-Null
    Assert-NativeSuccess 'config-set server_secret'
    & $animus config-set node_id       $id   | Out-Null
    Assert-NativeSuccess 'config-set node_id'
    & $animus config-set node_name     $name | Out-Null
    Assert-NativeSuccess 'config-set node_name'
    Write-Ok "Peer configurado: node_id=$id  hub=$hub"
}

# -- 5. Collect + sync inicial ------------------------------------------
function Initial-Sync($dir) {
    $animus = Join-Path $dir '.venv\Scripts\animus.exe'
    Write-Step 'Coletando memorias locais...'
    & $animus collect
    if ($LASTEXITCODE -ne 0) { Write-Warn "collect retornou erro (codigo $LASTEXITCODE)" }
    Write-Step 'Sincronizando com o hub...'
    & $animus sync
    if ($LASTEXITCODE -eq 0) { Write-Ok 'Sync inicial concluido' }
    else { Write-Warn "Sync falhou (codigo $LASTEXITCODE) - verifique hub_url e server_secret" }
}

# -- 6. Scheduled Task - `animus daemon` no logon -----------------------
function Install-Task($dir, $enabled) {
    if ($enabled -ne 'yes') { return }
    $python = Join-Path $dir '.venv\Scripts\python.exe'
    $name   = 'AnimusPeerDaemon'

    Write-Step "Registrando Scheduled Task '$name' no logon..."
    # RestartCount alto + intervalo curto sustentam o self-update: o daemon
    # detecta uma versao nova, faz `pip install --upgrade` e cai com exit
    # code 75 (EX_TEMPFAIL); o Task Scheduler restarta dentro de 1 minuto e
    # a nova versao entra no lugar - sem janela manual.
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
    Write-Ok "Task ativa - `Get-ScheduledTask $name` para ver o status"
}

function Read-DefaultedHost($prompt, $default) {
    $r = Read-Host "?  $prompt [$default]"
    if ([string]::IsNullOrWhiteSpace($r)) { return $default } else { return $r }
}

# -- 7b. Registrar MCP no Claude Code -----------------------------------
# Idempotente: substitui qualquer entrada anterior em mcpServers.animus
# em vez de duplicar. Quando $env:USERPROFILE\.claude.json nao existe,
# o Claude Code nao esta instalado para este usuario - pulamos sem erro.
function Install-ClaudeMcp($dir, $enabled) {
    if ($enabled -ne 'yes') { return }
    $cfg = Join-Path $env:USERPROFILE '.claude.json'
    if (-not (Test-Path $cfg)) {
        Write-Warn '.claude.json nao encontrado - Claude Code nao instalado neste usuario. Pulando MCP.'
        return
    }
    $mcp = Join-Path $dir '.venv\Scripts\animus-mcp.exe'
    if (-not (Test-Path $mcp)) { Write-Warn "$mcp ausente - pulando MCP"; return }

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
print('  ok - mcpServers agora tem:', list(data['mcpServers']))
"@
    & $py -c $script $cfg $mcp
    Write-Ok 'Animus MCP registrado para Claude Code'
}

# -- Main ---------------------------------------------------------------
Write-Host ''
Write-Host '  ANIMUS - Peer Installation Kit (Windows)' -ForegroundColor Magenta
Write-Host '  ------------------------------------------' -ForegroundColor Magenta
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
if ([string]::IsNullOrWhiteSpace($secret)) { Write-Err 'server_secret e obrigatorio' }
if ([string]::IsNullOrWhiteSpace($nodeNm)) { $nodeNm = Read-DefaultedHost 'Node name' $env:COMPUTERNAME }
if ([string]::IsNullOrWhiteSpace($nodeId)) {
    $nodeId = (& python -c 'import uuid; print(str(uuid.uuid4())[:12])').Trim()
}

Write-Step "Plano:  install_dir=$dir  hub=$hub  node_id=$nodeId  service=$task  claude-mcp=$mcp"
Write-Host ''

Install-Deps
$maintenance = Enter-PeerMaintenance $dir
$installCompleted = $false
try {
    Clone-Repo         $dir   $repo   $branch
    New-VenvAndInstall $dir
    Configure-Peer     $dir   $hub    $secret $nodeId $nodeNm
    Initial-Sync       $dir
    Install-Task       $dir   $task
    if ($task -ne 'yes' -and $maintenance.TaskWasRunning) {
        Start-ScheduledTask -TaskName 'AnimusPeerDaemon' -ErrorAction Stop
    }
    Install-ClaudeMcp  $dir   $mcp
    $installCompleted = $true
} finally {
    if (-not $installCompleted) { Restore-PeerTask $maintenance }
}

Write-Host ''
Write-Host '  -------------------------------------' -ForegroundColor Magenta
Write-Host '  Peer registrado com sucesso'           -ForegroundColor Magenta
Write-Host '  -------------------------------------' -ForegroundColor Magenta
Write-Host ''
Write-Host "  Ativar venv:   & '$dir\.venv\Scripts\Activate.ps1'"
Write-Host '  Comandos:      animus stats  /  animus search "..." '
Write-Host "  Daemon status: Get-ScheduledTask AnimusPeerDaemon"
Write-Host ''
