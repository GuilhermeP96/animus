# =============================================================================
# Animus Peer Installer Kit - self-bootstrapping wrapper (Windows)
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
    Write-Host "X  peer.env nao encontrado em $envFile" -ForegroundColor Red
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
# check is enough - peer.env from the hub always carries a real value.
if (-not $env:ANIMUS_SERVER_SECRET) {
    Write-Host "X  peer.env nao tem ANIMUS_SERVER_SECRET - gere o ZIP novamente no hub." -ForegroundColor Red
    exit 1
}

$installDir = if ($env:ANIMUS_INSTALL_DIR) {
    $env:ANIMUS_INSTALL_DIR
} else {
    Join-Path $env:LOCALAPPDATA 'animus'
}
$task = Get-ScheduledTask -TaskName 'AnimusPeerDaemon' -ErrorAction SilentlyContinue
$taskWasRunning = $null -ne $task -and $task.State -eq 'Running'
if ($taskWasRunning) {
    Write-Host 'Stopping the Animus task for maintenance...' -ForegroundColor Cyan
    Stop-ScheduledTask -TaskName 'AnimusPeerDaemon' -ErrorAction Stop
}

# Release only launchers inside this peer venv. The wrapper itself runs in a
# separate PowerShell process and remains alive to perform/verify the update.
$scriptsDir = [IO.Path]::GetFullPath((Join-Path $installDir '.venv\Scripts')).TrimEnd('\') + '\'
Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
    $_.ExecutablePath -and
    $_.ExecutablePath.StartsWith($scriptsDir, [StringComparison]::OrdinalIgnoreCase) -and
    $_.Name -like 'animus*.exe'
} | ForEach-Object {
    & taskkill.exe /PID $_.ProcessId /T /F 2>$null | Out-Null
}

$repo   = if ($env:ANIMUS_REPO_URL) { $env:ANIMUS_REPO_URL } else { 'https://github.com/GuilhermeP96/animus.git' }
$branch = if ($env:ANIMUS_BRANCH)   { $env:ANIMUS_BRANCH }   else { 'master' }
$rawBase = ($repo -replace '\.git$', '') -replace 'github\.com', 'raw.githubusercontent.com'
$url    = "$rawBase/$branch/scripts/install-peer.ps1"
$installedSource = Join-Path $installDir 'scripts\install-peer.ps1'

Write-Host ''
Write-Host 'Animus Peer - self-install (Windows)' -ForegroundColor Magenta
Write-Host "    hub:     $env:ANIMUS_HUB_URL"
Write-Host "    node_id: $env:ANIMUS_NODE_ID"
Write-Host "    name:    $env:ANIMUS_NODE_NAME"
Write-Host "    source:  local checkout (fallback: $url)"
Write-Host ''

# Download and run the canonical installer with env vars already set. Preserve
# its exit code so install.bat cannot report success after a failed update.
$tmp = Join-Path $env:TEMP "install-peer-$([guid]::NewGuid().Guid).ps1"
$installExitCode = 1
try {
    if ((Test-Path (Join-Path $installDir '.git')) -and (Test-Path $installedSource)) {
        # Existing peers already have an authenticated clone. Prefer it because
        # private GitHub repositories return 404 from raw.githubusercontent.com.
        & git -C $installDir fetch --quiet origin $branch
        if ($LASTEXITCODE -ne 0) { throw "git fetch failed (code $LASTEXITCODE)" }
        & git -C $installDir checkout --quiet $branch
        if ($LASTEXITCODE -ne 0) { throw "git checkout failed (code $LASTEXITCODE)" }
        & git -C $installDir pull --quiet --ff-only origin $branch
        if ($LASTEXITCODE -ne 0) { throw "git pull failed (code $LASTEXITCODE)" }
        $source = $installedSource
    } else {
        Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $tmp
        $source = $tmp
    }
    # GitHub raw serves UTF-8 without BOM. Normalize it for Windows PowerShell
    # 5, which otherwise decodes non-ASCII script text using the ANSI codepage.
    $body = [IO.File]::ReadAllText($source, [Text.Encoding]::UTF8)
    [IO.File]::WriteAllText($tmp, $body, (New-Object Text.UTF8Encoding($true)))
    & powershell -NoProfile -ExecutionPolicy Bypass -File $tmp
    $installExitCode = $LASTEXITCODE
} finally {
    if (Test-Path $tmp) { Remove-Item -Force $tmp }
    if ($installExitCode -ne 0 -and $taskWasRunning) {
        Write-Host 'Restoring the previous Animus task after failure...' -ForegroundColor Yellow
        Start-ScheduledTask -TaskName 'AnimusPeerDaemon' -ErrorAction SilentlyContinue
    }
}

if ($installExitCode -ne 0) {
    Write-Host "X  Instalador principal falhou (codigo $installExitCode)." -ForegroundColor Red
}
exit $installExitCode
