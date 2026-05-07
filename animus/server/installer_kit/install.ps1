# =============================================================================
# Animus Peer Installer Kit — self-bootstrapping wrapper (Windows)
# -----------------------------------------------------------------------------
# Reads peer.env (pre-baked by the hub) and runs the canonical
# install-peer.ps1 from the configured repo with all variables already set.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File install.ps1
#   (or double-click install.bat which calls this with the right flags)
# =============================================================================
[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'

$here    = Split-Path -Parent $MyInvocation.MyCommand.Path
$envFile = Join-Path $here 'peer.env'

if (-not (Test-Path $envFile)) {
    Write-Host "✗  peer.env nao encontrado em $envFile" -ForegroundColor Red
    exit 1
}

# Parse peer.env (KEY=VALUE, ignore #comments / blank lines)
Get-Content $envFile | ForEach-Object {
    $line = $_.Trim()
    if ($line -eq '' -or $line.StartsWith('#')) { return }
    $kv = $line -split '=', 2
    if ($kv.Length -eq 2) {
        $k = $kv[0].Trim()
        $v = $kv[1].Trim()
        Set-Item -Path "Env:$k" -Value $v
    }
}

# NOTE: the literal '{{SECRET}}' would be substituted by the hub's installer-kit
# renderer, so we cannot use it as an "unrendered" sentinel here. A simple empty
# check is enough — peer.env from the hub always carries a real value.
if (-not $env:ANIMUS_SERVER_SECRET) {
    Write-Host "X  peer.env nao tem ANIMUS_SERVER_SECRET - gere o ZIP novamente no hub." -ForegroundColor Red
    exit 1
}

$repo   = if ($env:ANIMUS_REPO_URL) { $env:ANIMUS_REPO_URL } else { 'https://github.com/GuilhermeP96/animus.git' }
$branch = if ($env:ANIMUS_BRANCH)   { $env:ANIMUS_BRANCH }   else { 'master' }
$rawBase = ($repo -replace '\.git$', '') -replace 'github\.com', 'raw.githubusercontent.com'
$url    = "$rawBase/$branch/scripts/install-peer.ps1"

Write-Host ''
Write-Host '⟁  Animus Peer — self-install (Windows)' -ForegroundColor Magenta
Write-Host "    hub:     $env:ANIMUS_HUB_URL"
Write-Host "    node_id: $env:ANIMUS_NODE_ID"
Write-Host "    name:    $env:ANIMUS_NODE_NAME"
Write-Host "    source:  $url"
Write-Host ''

# Download and dot-source the canonical installer with env vars already set.
$tmp = Join-Path $env:TEMP "install-peer-$([guid]::NewGuid().Guid).ps1"
try {
    Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $tmp
    & powershell -NoProfile -ExecutionPolicy Bypass -File $tmp
} finally {
    if (Test-Path $tmp) { Remove-Item -Force $tmp }
}
