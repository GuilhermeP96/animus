[CmdletBinding()]
param([ValidateSet('Prepare','Apply')][string]$Mode='Prepare',
      [string]$ConfigPath, [string]$PythonExe, [string]$TaskName, [string]$TaskPath,
      [string]$RecoveryDir, [string]$EnvelopePath, [string]$ExpectedDigest,
      [switch]$NonInteractive, [string]$ExpectedNodeId,
      [ValidateRange(60,3600)][int]$TTLSeconds=3600)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$helper=Join-Path $PSScriptRoot 'recover_peer.py'
. (Join-Path $PSScriptRoot 'Recovery-Selection.ps1')
function Full-Path([string]$Path) {
    $item=Get-Item -LiteralPath $Path -Force
    if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Reparse path forbidden' }
    return $item.FullName
}
function Resolve-Sid([string]$Identity) {
    if ($Identity -match '^S-1-[0-9-]+$') { return ([Security.Principal.SecurityIdentifier]::new($Identity)).Value }
    return ([Security.Principal.NTAccount]::new($Identity)).Translate([Security.Principal.SecurityIdentifier]).Value
}
function Hash-Text([string]$Value) {
    $sha=[Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($Value)))).Replace('-','').ToLowerInvariant() }
    finally { $sha.Dispose() }
}
function Invoke-Helper([string[]]$Arguments) {
    $captured=@(& $script:PythonExe $helper @Arguments 2>&1)
    if ($LASTEXITCODE -ne 0) { throw 'Recovery preflight or operation refused; credentials were not printed' }
    return ($captured -join "`n") | ConvertFrom-Json
}
function Verify-Native {
    if (($script:PythonExe.Replace('\','/')) -match '(?i)(/\.codex/|/codex/|vscode|claude|antigravity|/agy/)') { throw 'Use only the existing native Animus interpreter' }
    $probe=@(& $script:PythonExe -c 'import sys,cryptography; from animus.config import AnimusConfig; from animus.network.crypto import create_auth_header; assert sys.version_info >= (3,10); assert create_auth_header("recovery-preflight","temporary-probe-credential-never-used") .get("X-Animus-Nonce"); print("native-ok")' 2>&1)
    if ($LASTEXITCODE -ne 0 -or ($probe -join '') -ne 'native-ok') { throw 'Existing native Python/Animus/cryptography or strict nonce support unavailable' }
    foreach ($scope in @('Process','User','Machine')) {
        $value=[Environment]::GetEnvironmentVariable('ANIMUS_SECURE_AUTH',$scope)
        if ($value -and $value -ne '1') { throw 'Explicit insecure authentication environment requires administrator correction first' }
    }
}
function Verify-TaskEnvironment($Selected) {
    $working=$Selected.Action.WorkingDirectory
    if ($working -and (Test-Path -LiteralPath (Join-Path $working '.env'))) {
        $envPath=Full-Path (Join-Path $working '.env')
        foreach ($line in [IO.File]::ReadAllLines($envPath)) {
            if ($line -match '^\s*ANIMUS_SECURE_AUTH\s*=\s*["'']?([^"''\s]+)' -and $Matches[1] -ne '1') { throw 'Task .env explicitly disables secure authentication' }
        }
        return Hash-Text ([IO.File]::ReadAllText($envPath))
    }
    return 'no-task-env'
}
function Get-SelectedTask([string]$Name,[string]$Path) {
    $task=Get-ScheduledTask -TaskName $Name -TaskPath $Path
    if ($task.Actions.Count -ne 1) { throw 'Only one direct native Animus task action is supported' }
    $action=$task.Actions[0]
    if ($action.Arguments -notmatch '(?i)(-m\s+animus|animus[^\r\n]*daemon)' -or $action.Arguments -match '(?i)ANIMUS_SECURE_AUTH\s*=\s*[^1\s]') {
        throw 'Selected task is not a verified direct Animus action or has insecure authentication'
    }
    $exe=Full-Path $action.Execute
    if ([IO.Path]::GetFileName($exe) -notmatch '^python(w)?\.exe$') { throw 'Wrapper/service tasks need separate administrator qualification; no guessed restarts' }
    $runtimeSid=Resolve-Sid $task.Principal.UserId
    return @{Task=$task; Action=$action; Python=$exe; Sid=$runtimeSid;
             Fingerprint=(Hash-Text ($exe+"`n"+$action.Arguments+"`n"+$action.WorkingDirectory+"`n"+$runtimeSid))}
}
try {
    if ($env:OS -ne 'Windows_NT') { throw 'Run this native recovery launcher on Windows only' }
    Assert-ExplicitRecoverySelection ([bool]$NonInteractive) $TaskName $TaskPath $ConfigPath $ExpectedNodeId
    $owner=[Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    if ($Mode -eq 'Prepare') {
        $tasks=@(Get-ScheduledTask | Where-Object {$_.TaskName -match 'Animus' -or $_.TaskPath -match 'Animus'})
        $services=@(Get-CimInstance Win32_Service | Where-Object {$_.Name -match 'Animus' -or $_.DisplayName -match 'Animus'})
        $processes=@(Get-CimInstance Win32_Process | Where-Object {$_.Name -match '^python(w)?\.exe$' -and $_.CommandLine -match '(?i)(-m\s+animus|animus.*daemon)'})
        Write-Host ('Discovery: {0} task(s), {1} service(s), {2} native process(es). Task Ready is not proof of a running peer.' -f $tasks.Count,$services.Count,$processes.Count)
        if (-not $TaskName) {
            if (-not $tasks.Count) { throw 'No native task found; service/wrapper installations require administrator qualification' }
            for ($i=0; $i -lt $tasks.Count; $i++) { Write-Host ('[{0}] {1}{2} ({3})' -f $i,$tasks[$i].TaskPath,$tasks[$i].TaskName,$tasks[$i].State) }
            $index=0
            if (-not [int]::TryParse((Read-Host 'Select the exact native task index'),[ref]$index) -or $index -lt 0 -or $index -ge $tasks.Count) { throw 'Invalid task selection' }
            $TaskName=$tasks[$index].TaskName; $TaskPath=$tasks[$index].TaskPath
        }
        if (-not $TaskPath) { $TaskPath='\' }
        $selected=Get-SelectedTask $TaskName $TaskPath
        if ($PythonExe -and (Full-Path $PythonExe) -ne $selected.Python) { throw 'Interpreter must equal the selected native task executable' }
        $PythonExe=$selected.Python
        Verify-Native
        $environmentFingerprint=Verify-TaskEnvironment $selected
        $candidates=@()
        if ($ConfigPath) { $candidates+=Full-Path $ConfigPath }
        else {
            if ($env:ANIMUS_DATA_DIR) { $candidates+=Join-Path $env:ANIMUS_DATA_DIR 'config.json' }
            $working=$selected.Action.WorkingDirectory
            if ($working -and (Test-Path -LiteralPath (Join-Path $working '.env'))) {
                foreach ($line in [IO.File]::ReadAllLines((Join-Path $working '.env'))) {
                    if ($line -match '^\s*ANIMUS_SECURE_AUTH\s*=\s*["'']?([^"''\s]+)' -and $Matches[1] -ne '1') { throw 'Task .env explicitly disables secure authentication' }
                    if ($line -match '^\s*ANIMUS_DATA_DIR\s*=\s*["'']?([^"''\r\n]+)') { $candidates+=Join-Path ($Matches[1].Trim()) 'config.json' }
                }
            }
            if ($selected.Sid -eq $owner) { $candidates+=Join-Path $env:USERPROFILE '.animus\config.json' }
            $candidates=@($candidates | Where-Object {Test-Path -LiteralPath $_ -PathType Leaf} | ForEach-Object {Full-Path $_} | Select-Object -Unique)
        }
        if (-not $candidates.Count) { throw 'Supply -ConfigPath for the exact existing runtime config; no migration or guessed creation' }
        if ($candidates.Count -gt 1) {
            for ($i=0; $i -lt $candidates.Count; $i++) { Write-Host ('[{0}] {1}' -f $i,$candidates[$i]) }
            $index=0
            if (-not [int]::TryParse((Read-Host 'Select the exact active config index'),[ref]$index) -or $index -lt 0 -or $index -ge $candidates.Count) { throw 'Invalid config selection' }
            $ConfigPath=$candidates[$index]
        } else { $ConfigPath=$candidates[0] }
        $acl=Get-Acl -LiteralPath $ConfigPath
        $configOwner=Resolve-Sid $acl.Owner
        if ($selected.Sid -notin @($configOwner,'S-1-5-18')) { throw 'Runtime principal cannot read the protected replacement; administrator must qualify ownership' }
        $identity=Invoke-Helper @('inspect','--config',$ConfigPath)
        Assert-RecoveryNodeIdentity $ExpectedNodeId $identity.node_id
        Write-Host ('Selected node {0}; task {1}{2}; config {3}' -f $identity.node_id,$TaskPath,$TaskName,$ConfigPath)
        if (-not $NonInteractive -and (Read-Host 'Type CONFIRM to attest this exact config belongs to this native task') -cne 'CONFIRM') { throw 'Owner selection not confirmed' }
        if (-not $RecoveryDir) { $RecoveryDir=Join-Path $env:USERPROFILE ('.animus-recovery-'+[Guid]::NewGuid().ToString('N')) }
        $RecoveryDir=[IO.Path]::GetFullPath($RecoveryDir)
        $public=Invoke-Helper @('prepare','--config',$ConfigPath,'--work-dir',$RecoveryDir,'--owner-sid',$owner,'--config-owner-sid',$configOwner,'--ttl-seconds',"$TTLSeconds")
        Assert-RecoveryNodeIdentity $identity.node_id $public.node_id
        Assert-RecoveryNodeIdentity $ExpectedNodeId $public.node_id
        $runtime=@{node_id=$identity.node_id; task_name=$TaskName; task_path=$TaskPath; python=$PythonExe; runtime_fingerprint=$selected.Fingerprint; environment_fingerprint=$environmentFingerprint; config_path=$ConfigPath; owner_sid=$owner; config_owner_sid=$configOwner}
        $runtimePath=Join-Path $RecoveryDir 'runtime.json'
        [IO.File]::WriteAllText($runtimePath,($runtime | ConvertTo-Json),[Text.UTF8Encoding]::new($false))
        & (Join-Path $PSScriptRoot 'Protect-PrivateState.ps1') -LiteralPath $runtimePath -OwnerSid $owner
        Write-Host "Keep the private recovery directory: $RecoveryDir. Paste ONLY the following public JSON into the authenticated owner chat. Validity begins now."
        $public | ConvertTo-Json -Compress
    } else {
        if (-not $RecoveryDir -or -not $EnvelopePath -or $ExpectedDigest -notmatch '^[0-9a-f]{64}$') { throw 'Apply requires private recovery directory, envelope and independently received canonical SHA256' }
        $runtime=Get-Content -LiteralPath (Join-Path $RecoveryDir 'runtime.json') -Raw | ConvertFrom-Json
        if ($runtime.owner_sid -ne $owner) { throw 'Use the same independently verified local owner account' }
        $PythonExe=$runtime.python
        $actual=Invoke-Helper @('inspect','--config',$runtime.config_path)
        $explicitConfig=$ConfigPath
        if ($NonInteractive) { $explicitConfig=Full-Path $ConfigPath }
        Assert-RecoveryTargetBinding ([bool]$NonInteractive) $TaskName $TaskPath $explicitConfig $ExpectedNodeId $runtime $actual.node_id
        $selected=Get-SelectedTask $runtime.task_name $runtime.task_path
        if ($selected.Fingerprint -ne $runtime.runtime_fingerprint) { throw 'Native runtime changed; do not stop or activate' }
        $PythonExe=$selected.Python; Verify-Native
        if ((Verify-TaskEnvironment $selected) -ne $runtime.environment_fingerprint) { throw 'Task .env/DataDir changed; prepare a fresh owner-confirmed enrollment' }
        $configOwner=Resolve-Sid ((Get-Acl -LiteralPath $runtime.config_path).Owner)
        if ($configOwner -ne $runtime.config_owner_sid) { throw 'Config ownership changed' }
        if (-not $NonInteractive -and (Read-Host ('Type APPLY to replace only server_secret and restart task '+$runtime.task_name)) -cne 'APPLY') { throw 'Owner application not confirmed' }
        $running=@(Get-CimInstance Win32_Process | Where-Object {$_.ExecutablePath -eq $PythonExe -and $_.CommandLine -and $_.CommandLine.Trim().EndsWith($selected.Action.Arguments.Trim(),[StringComparison]::Ordinal)})
        if ($running.Count -gt 1 -or ($selected.Task.State -eq 'Running' -and $running.Count -ne 1) -or ($selected.Task.State -ne 'Running' -and $running.Count -gt 0)) { throw 'Task/process attribution ambiguous; no stop or activation' }
        $null=Invoke-Helper @('stage','--work-dir',$RecoveryDir,'--envelope',(Full-Path $EnvelopePath),'--expected-digest',$ExpectedDigest)
        $trackedPids=@($running | ForEach-Object {$_.ProcessId})
        $trackedDates=@($running | ForEach-Object {$_.CreationDate})
        Stop-ScheduledTask -TaskName $runtime.task_name -TaskPath $runtime.task_path
        $deadline=[DateTime]::UtcNow.AddSeconds(30)
        do {
            $task=Get-ScheduledTask -TaskName $runtime.task_name -TaskPath $runtime.task_path
            $remaining=@(Get-CimInstance Win32_Process | Where-Object {$trackedPids -contains $_.ProcessId -and $trackedDates -contains $_.CreationDate})
            if ($task.State -ne 'Running' -and $remaining.Count -eq 0) { break }
            Start-Sleep -Milliseconds 250
        } while ([DateTime]::UtcNow -lt $deadline)
        if ($task.State -eq 'Running' -or $remaining.Count -gt 0) { throw 'Native task did not stop; no activation' }
        $null=Invoke-Helper @('commit','--work-dir',$RecoveryDir)
        Verify-Native
        if ((Verify-TaskEnvironment $selected) -ne $runtime.environment_fingerprint) { throw 'Task environment changed after replacement; keep fresh credential and reconcile stopped runtime' }
        Start-ScheduledTask -TaskName $runtime.task_name -TaskPath $runtime.task_path
        Write-Host 'Credential replaced privately and exact task start requested. Old-secret rollback is forbidden. The operator must verify native process and the server must verify actual authenticated reconnection.'
    }
} catch {
    Write-Error 'Local recovery blocked. No credential values are emitted. Keep private backups and reconcile with the administrator; do not restore the revoked credential.'
    exit 1
}
