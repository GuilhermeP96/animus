[CmdletBinding()]
param([ValidateSet('Register','Run')][string]$Mode='Register',[string]$PlanPath)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$script:Gate='input'
$script:InstalledVerified=$false
function Sid([string]$Value) {
    if ($Value -match '^S-1-[0-9-]+$') { return ([Security.Principal.SecurityIdentifier]::new($Value)).Value }
    return ([Security.Principal.NTAccount]::new($Value)).Translate([Security.Principal.SecurityIdentifier]).Value
}
function Hash([string]$Path) { return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant() }
function Private([string]$Path,[string]$Owner,[bool]$Directory=$false) {
    $item=Get-Item -LiteralPath $Path -Force
    if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Reparse path forbidden' }
    $acl=if ($Directory) { [Security.AccessControl.DirectorySecurity]::new() } else { [Security.AccessControl.FileSecurity]::new() }
    $acl.SetAccessRuleProtection($true,$false); $acl.SetOwner([Security.Principal.SecurityIdentifier]::new($Owner))
    foreach ($identity in @($Owner,'S-1-5-18','S-1-5-32-544') | Select-Object -Unique) {
        $sid=[Security.Principal.SecurityIdentifier]::new($identity)
        $rule=if ($Directory) { [Security.AccessControl.FileSystemAccessRule]::new($sid,'FullControl','ContainerInherit,ObjectInherit','None','Allow') } else { [Security.AccessControl.FileSystemAccessRule]::new($sid,'FullControl','Allow') }
        $acl.AddAccessRule($rule)
    }
    Set-Acl -LiteralPath $Path -AclObject $acl
    $observed=Get-Acl -LiteralPath $Path
    if (-not $observed.AreAccessRulesProtected -or (Sid $observed.Owner) -ne $Owner) { throw 'Private ACL mismatch' }
    foreach ($rule in $observed.Access) {
        if ((Sid $rule.IdentityReference.Value) -notin @($Owner,'S-1-5-18','S-1-5-32-544') -or $rule.IsInherited -or $rule.AccessControlType -ne 'Allow') { throw 'Unexpected private ACL' }
    }
}
function Parent([string]$Path,[string]$Owner) {
    $item=Get-Item -LiteralPath $Path -Force
    if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Parent reparse forbidden' }
    $danger=[Security.AccessControl.FileSystemRights]::Write -bor [Security.AccessControl.FileSystemRights]::Delete -bor [Security.AccessControl.FileSystemRights]::DeleteSubdirectoriesAndFiles -bor [Security.AccessControl.FileSystemRights]::ChangePermissions -bor [Security.AccessControl.FileSystemRights]::TakeOwnership
    foreach ($rule in (Get-Acl -LiteralPath $Path).Access) {
        if ($rule.AccessControlType -eq 'Allow' -and (Sid $rule.IdentityReference.Value) -notin @($Owner,'S-1-5-18','S-1-5-32-544') -and ($rule.FileSystemRights -band $danger)) { throw 'Untrusted parent mutation permission' }
    }
}
function Write-PrivateJson([string]$Path,$Value,[string]$Owner) {
    $temp=$Path+'.'+[Guid]::NewGuid().ToString('N')+'.tmp'
    $stream=[IO.File]::Open($temp,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
    $stream.Dispose(); Private $temp $Owner
    [IO.File]::WriteAllText($temp,($Value | ConvertTo-Json -Depth 12),[Text.UTF8Encoding]::new($false))
    if (Test-Path -LiteralPath $Path) { [IO.File]::Replace($temp,$Path,$null) } else { [IO.File]::Move($temp,$Path) }
}
function Task-Binding($Task) {
    $xml=Export-ScheduledTask -TaskName $Task.TaskName -TaskPath $Task.TaskPath
    # Ignore only Enabled while the qualified own job temporarily disables it.
    $document=[xml]$xml
    $enabled=$document.SelectSingleNode('/*[local-name()="Task"]/*[local-name()="Settings"]/*[local-name()="Enabled"]')
    if ($null -eq $enabled) { throw 'Native enabled setting must be explicit' }
    $enabled.InnerText='BOUND-TEMPORARY'
    $xml=$document.OuterXml
    $sha=[Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($xml)))).Replace('-','').ToLowerInvariant() } finally { $sha.Dispose() }
}
function Validate-Task($Plan) {
    $task=Get-ScheduledTask -TaskName $Plan.task_name -TaskPath $Plan.task_path
    if ($task.Actions.Count -ne 1 -or (Sid $task.Principal.UserId) -ne $Plan.owner_sid) { throw 'Native task principal/action mismatch' }
    $action=$task.Actions[0]
    if ($action.Execute -ne $Plan.python -or $action.Arguments -notmatch '^\s*-m\s+animus\.cli\s+daemon(?:\s|$)') { throw 'Native task interpreter/action mismatch' }
    if ((Task-Binding $task) -ne $Plan.task_sha256) { throw 'Native task configuration drift' }
    return $task
}
function Validate-Plan($Plan) {
    $script:Gate='plan_identity'
    if ($Plan.owner_sid -ne [Security.Principal.WindowsIdentity]::GetCurrent().User.Value -or [DateTime]::UtcNow.Ticks -gt [long]$Plan.deadline_ticks) { throw 'Plan owner/expiry mismatch' }
    foreach ($path in @($Plan.python,$Plan.config_path,$Plan.wheel,$Plan.runner)) {
        $item=Get-Item -LiteralPath $path -Force
        if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Plan reparse forbidden' }
    }
    if ($Plan.python -match '(?i)(codex|vscode|claude|antigravity)' -or (Hash $Plan.wheel) -ne $Plan.wheel_sha256 -or (Hash $Plan.runner) -ne $Plan.runner_sha256) { throw 'Plan interpreter/payload integrity mismatch' }
    Parent (Split-Path $Plan.config_path -Parent) $Plan.owner_sid
    Parent (Split-Path $PlanPath -Parent) $Plan.owner_sid
    if ((Hash $Plan.config_path) -ne $Plan.config_sha256) { throw 'Config drift; never rewrite config during update' }
    $config=Get-Content -LiteralPath $Plan.config_path -Raw | ConvertFrom-Json
    if ($config.node_id -cne $Plan.node_id) { throw 'Native node mismatch' }
    if ([Environment]::GetEnvironmentVariable('ANIMUS_SECURE_AUTH','Process') -and $env:ANIMUS_SECURE_AUTH -ne '1') { throw 'Explicit insecure auth environment' }
    $null=Validate-Task $Plan
}
function Assert-VerifiedRestartEvidence([string]$ExpectedVersion,[string]$InstalledVersion,[long]$PidValue,[long]$ExpectedCreation,[long]$ObservedCreation,[bool]$TaskRunning,[bool]$ProcessAlive) {
    if ($ExpectedVersion -cne $InstalledVersion -or $PidValue -le 0 -or $ExpectedCreation -le 0 -or $ExpectedCreation -ne $ObservedCreation -or -not $TaskRunning -or -not $ProcessAlive) { throw 'Actual package/task/process evidence is incomplete' }
}
function Source-Alive($Plan) {
    $process=Get-CimInstance Win32_Process -Filter ('ProcessId='+[int]$Plan.source_pid) -ErrorAction SilentlyContinue
    if ($null -eq $process) { return $false }
    return $process.ExecutablePath -eq $Plan.python -and $process.CreationDate.ToUniversalTime().Ticks -eq [long]$Plan.source_creation_ticks
}
try {
    if ($Mode -eq 'Register') {
        $spec=[Console]::In.ReadToEnd() | ConvertFrom-Json
        $owner=[Security.Principal.WindowsIdentity]::GetCurrent().User.Value
        $script:Gate='registration_binding'
        $task=Get-ScheduledTask -TaskName $spec.task_name -TaskPath $spec.task_path
        if ($task.Actions.Count -ne 1 -or (Sid $task.Principal.UserId) -ne $owner -or $task.Actions[0].Execute -ne $spec.python -or $task.Actions[0].Arguments -notmatch '^\s*-m\s+animus\.cli\s+daemon(?:\s|$)') { throw 'Current-user direct native task required' }
        $source=Get-CimInstance Win32_Process -Filter ('ProcessId='+[int]$spec.source_pid)
        if ($source.ExecutablePath -ne $spec.python -or -not $source.CommandLine.Trim().EndsWith($task.Actions[0].Arguments.Trim(),[StringComparison]::Ordinal)) { throw 'Daemon task/process attribution mismatch' }
        Parent $spec.data_dir $owner
        Parent (Split-Path $spec.config_path -Parent) $owner
        if (-not $task.Settings.Enabled) { throw 'Native task must be enabled before staging update' }
        if ((Hash $spec.config_path) -ne $spec.config_sha256) { throw 'Active config changed' }
        $updates=Join-Path $spec.data_dir 'updates'
        if (-not (Test-Path -LiteralPath $updates)) { [IO.Directory]::CreateDirectory($updates) | Out-Null }
        Parent $updates $owner
        $jobDir=Join-Path $spec.data_dir ('updates\job-'+[Guid]::NewGuid().ToString('N'))
        [IO.Directory]::CreateDirectory($jobDir) | Out-Null; Private $jobDir $owner $true
        $runner=Join-Path $jobDir 'windows-update-task.ps1'
        [IO.File]::WriteAllBytes($runner,[IO.File]::ReadAllBytes($PSCommandPath)); Private $runner $owner
        $jobName='AnimusPeerUpdate-'+[Guid]::NewGuid().ToString('N')
        $PlanPath=Join-Path $jobDir 'plan.json'
        $plan=@{version=1;task_name=$spec.task_name;task_path=$spec.task_path;task_sha256=(Task-Binding $task);owner_sid=$owner;python=$spec.python;config_path=$spec.config_path;config_sha256=$spec.config_sha256;node_id=$spec.node_id;wheel=$spec.wheel;wheel_sha256=$spec.wheel_sha256;expected_version=$spec.expected_version;source_pid=$spec.source_pid;source_creation_ticks=$source.CreationDate.ToUniversalTime().Ticks;deadline_ticks=[DateTime]::UtcNow.AddMinutes(15).Ticks;job_name=$jobName;runner=$runner;runner_sha256=(Hash $runner)}
        Write-PrivateJson $PlanPath $plan $owner
        $script:Gate='register_independent_update_task'
        $ps=Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
        $command="& '"+$runner.Replace("'","''")+"' -Mode Run -PlanPath '"+$PlanPath.Replace("'","''")+"'"
        $encoded=[Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($command))
        $action=New-ScheduledTaskAction -Execute $ps -Argument ('-NoProfile -NonInteractive -EncodedCommand '+$encoded)
        $trigger=New-ScheduledTaskTrigger -Once -At ([DateTime]::Now.AddSeconds(10))
        $settings=New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 15) -StartWhenAvailable
        $principal=New-ScheduledTaskPrincipal -UserId $task.Principal.UserId -LogonType S4U -RunLevel $task.Principal.RunLevel
        Register-ScheduledTask -TaskName $jobName -TaskPath '\' -Action $action -Trigger $trigger -Settings $settings -Principal $principal | Out-Null
        $registered=Get-ScheduledTask -TaskName $jobName -TaskPath '\'
        if ((Sid $registered.Principal.UserId) -ne $owner -or $registered.Actions.Count -ne 1 -or $registered.Actions[0].Execute -ne $ps -or $registered.Actions[0].Arguments -ne $action.Arguments) { throw 'Registered helper binding mismatch' }
        Write-PrivateJson (Join-Path $jobDir 'receipt.json') @{status='registered';installed=$false;restart_verified=$false;owner='agent';job_name=$jobName} $owner
        Start-ScheduledTask -TaskName $jobName -TaskPath '\'
        $script:Gate='verify_independent_job_started'
        $deadline=[DateTime]::UtcNow.AddSeconds(45); $jobStarted=$false
        do {
            $job=Get-ScheduledTask -TaskName $jobName -TaskPath '\'
            $current=Get-Content -LiteralPath (Join-Path $jobDir 'receipt.json') -Raw | ConvertFrom-Json
            if ($job.State -eq 'Running' -and $current.status -eq 'waiting_bound_source_exit') { $jobStarted=$true; break }
            if ($current.status -eq 'blocked') { throw 'Independent job preflight failed' }
            Start-Sleep -Milliseconds 200
        } while ([DateTime]::UtcNow -lt $deadline)
        if (-not $jobStarted) { throw 'Independent job did not actually start; daemon remains running' }
        Write-Output (@{status='registered';job_started=$true;installed=$false;restart_verified=$false;job_name=$jobName} | ConvertTo-Json -Compress)
        exit 0
    }
    $plan=Get-Content -LiteralPath $PlanPath -Raw | ConvertFrom-Json
    $receipt=Join-Path (Split-Path $PlanPath -Parent) 'receipt.json'
    Validate-Plan $plan
    $script:Gate='wait_bound_source_exit'
    Write-PrivateJson $receipt @{status='waiting_bound_source_exit';installed=$false;restart_verified=$false;owner='agent'} $plan.owner_sid
    $deadline=[DateTime]::UtcNow.AddSeconds(60)
    while (Source-Alive $plan) { if ([DateTime]::UtcNow -gt $deadline) { throw 'Bound source process did not exit' }; Start-Sleep -Milliseconds 200 }
    # Stop ONLY the unchanged original task; helper is a separate scheduler job.
    $script:Gate='stop_exact_native_task'
    $task=Validate-Task $plan
    Disable-ScheduledTask -TaskName $plan.task_name -TaskPath $plan.task_path | Out-Null
    if ($task.State -eq 'Running') { Stop-ScheduledTask -TaskName $plan.task_name -TaskPath $plan.task_path }
    $deadline=[DateTime]::UtcNow.AddSeconds(30)
    do { $task=Validate-Task $plan; if ($task.State -ne 'Running') { break }; Start-Sleep -Milliseconds 200 } while ([DateTime]::UtcNow -lt $deadline)
    if ($task.State -eq 'Running' -or (Source-Alive $plan)) { throw 'Exact native task did not stop' }
    Validate-Plan $plan
    $task=Validate-Task $plan
    $remaining=@(Get-CimInstance Win32_Process | Where-Object {$_.ExecutablePath -eq $plan.python -and $_.CommandLine -and $_.CommandLine.Trim().EndsWith($task.Actions[0].Arguments.Trim(),[StringComparison]::Ordinal)})
    if ($remaining.Count) { throw 'Native daemon still alive; no broad process kill permitted' }
    Write-PrivateJson $receipt @{status='installing';installed=$false;restart_verified=$false;owner='agent'} $plan.owner_sid
    $script:Gate='bounded_local_wheel_install'
    $stdout=Join-Path (Split-Path $PlanPath -Parent) 'pip.stdout'; $stderr=Join-Path (Split-Path $PlanPath -Parent) 'pip.stderr'
    foreach ($file in @($stdout,$stderr)) { [IO.File]::WriteAllBytes($file,[byte[]]@()); Private $file $plan.owner_sid }
    $arguments='-m pip install --upgrade --quiet --disable-pip-version-check --no-index --no-deps "'+$plan.wheel+'"'
    $pip=Start-Process -FilePath $plan.python -ArgumentList $arguments -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru -WindowStyle Hidden
    if (-not $pip.WaitForExit(600000)) { $pip.Kill(); throw 'Exact pip child timed out' }
    if ($pip.ExitCode -ne 0) { throw 'Native wheel install failed; no other process was killed' }
    $script:Gate='installed_version_and_config'
    $version=@(& $plan.python -c 'import animus;print(animus.__version__)' 2>&1)
    if ($LASTEXITCODE -ne 0 -or ($version -join '').Trim() -cne $plan.expected_version) { throw 'Installed version mismatch' }
    $script:InstalledVerified=$true
    $script:Gate='native_dependency_integrity'
    $check=Start-Process -FilePath $plan.python -ArgumentList '-m pip check' -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru -WindowStyle Hidden
    if (-not $check.WaitForExit(30000)) { $check.Kill(); throw 'Exact dependency-check child timed out' }
    if ($check.ExitCode -ne 0) { throw 'Native package dependency constraints are not satisfied' }
    Validate-Plan $plan
    $script:Gate='verify_actual_native_restart'
    $started=[DateTime]::UtcNow
    Enable-ScheduledTask -TaskName $plan.task_name -TaskPath $plan.task_path | Out-Null
    Start-ScheduledTask -TaskName $plan.task_name -TaskPath $plan.task_path
    $deadline=[DateTime]::UtcNow.AddSeconds(60); $verified=$false; $pidValue=$null; $creation=$null
    do {
        $task=Validate-Task $plan
        $processes=@(Get-CimInstance Win32_Process | Where-Object {$_.ExecutablePath -eq $plan.python -and $_.CreationDate.ToUniversalTime() -ge $started -and $_.CommandLine -and $_.CommandLine.Trim().EndsWith($task.Actions[0].Arguments.Trim(),[StringComparison]::Ordinal)})
        if ($task.State -eq 'Running' -and $processes.Count -eq 1) { $verified=$true; $pidValue=$processes[0].ProcessId; $creation=$processes[0].CreationDate.ToUniversalTime().Ticks; break }
        Start-Sleep -Milliseconds 250
    } while ([DateTime]::UtcNow -lt $deadline)
    if (-not $verified) { throw 'Task start requested but native process not verified' }
    Start-Sleep -Seconds 3
    $process=Get-CimInstance Win32_Process -Filter ('ProcessId='+[int]$pidValue) -ErrorAction SilentlyContinue
    if ($null -eq $process -or $process.CreationDate.ToUniversalTime().Ticks -ne $creation -or $process.ExecutablePath -ne $plan.python) { throw 'Native restarted process did not remain alive' }
    $task=Validate-Task $plan
    Assert-VerifiedRestartEvidence $plan.expected_version (($version -join '').Trim()) $pidValue $creation ($process.CreationDate.ToUniversalTime().Ticks) ($task.State -eq 'Running') ($null -ne $process)
    Write-PrivateJson $receipt @{status='completed';installed=$true;restart_verified=$true;version=$plan.expected_version;node_id=$plan.node_id;pid=$pidValue;creation_ticks=$creation;server_reconnection_verified=$false} $plan.owner_sid
    # Keep private receipt/runner/logs for verified corporate offsite retention.
    Unregister-ScheduledTask -TaskName $plan.job_name -TaskPath '\' -Confirm:$false
    exit 0
} catch {
    if ($Mode -eq 'Run' -and (Get-Variable plan -ErrorAction SilentlyContinue) -and $plan) {
        try { Write-PrivateJson (Join-Path (Split-Path $PlanPath -Parent) 'receipt.json') @{status='blocked';gate=$script:Gate;owner='agent';installed=$script:InstalledVerified;restart_verified=$false;secret_disclosed=$false} $plan.owner_sid } catch {}
    }
    Write-Output (@{status='blocked';gate=$script:Gate;restart_verified=$false;secret_disclosed=$false} | ConvertTo-Json -Compress)
    exit 1
}
