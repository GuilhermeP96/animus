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
    if ($Directory) { [IO.Directory]::SetAccessControl($Path,$acl) }
    else { [IO.File]::SetAccessControl($Path,$acl) }
    $observed=Get-Acl -LiteralPath $Path
    if (-not $observed.AreAccessRulesProtected -or $observed.GetOwner([Security.Principal.SecurityIdentifier]).Value -ne $Owner) { throw 'Private ACL mismatch' }
    foreach ($rule in $observed.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier])) {
        if ((Sid $rule.IdentityReference.Value) -notin @($Owner,'S-1-5-18','S-1-5-32-544') -or $rule.IsInherited -or $rule.AccessControlType -ne 'Allow') { throw 'Unexpected private ACL' }
    }
}
function Parent([string]$Path,[string]$Owner) {
    $item=Get-Item -LiteralPath $Path -Force
    if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Parent reparse forbidden' }
    $danger=[Security.AccessControl.FileSystemRights]::Write -bor [Security.AccessControl.FileSystemRights]::Delete -bor [Security.AccessControl.FileSystemRights]::DeleteSubdirectoriesAndFiles -bor [Security.AccessControl.FileSystemRights]::ChangePermissions -bor [Security.AccessControl.FileSystemRights]::TakeOwnership
    foreach ($rule in (Get-Acl -LiteralPath $Path).GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier])) {
        if ($rule.PropagationFlags -band [Security.AccessControl.PropagationFlags]::InheritOnly) { continue }
        if ($rule.AccessControlType -eq 'Allow' -and (Sid $rule.IdentityReference.Value) -notin @($Owner,'S-1-5-18','S-1-5-32-544','S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464') -and ($rule.FileSystemRights -band $danger)) { throw 'Untrusted parent mutation permission' }
    }
}
function Local-Absolute([string]$Path) {
    if ($Path -notmatch '^[A-Za-z]:[\\/]' -or $Path.StartsWith('\\')) { throw 'Absolute local native path required' }
    return [IO.Path]::GetFullPath($Path).TrimEnd('\','/')
}
function Guard-Ancestry([string]$Path,[string]$Owner) {
    $item=Get-Item -LiteralPath (Local-Absolute $Path) -Force
    if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Native ancestry reparse forbidden' }
    Parent $item.FullName $Owner
    $parent=if ($item.PSIsContainer) { $item.Parent } else { $item.Directory }
    # Rename/replacement is relevant on existing ancestors. A volume-root ACE
    # permitting creation of unrelated directories does not permit replacing an
    # existing protected child; unlike DELETE_CHILD/ownership/permission rights.
    $danger=[Security.AccessControl.FileSystemRights]::Delete -bor [Security.AccessControl.FileSystemRights]::DeleteSubdirectoriesAndFiles -bor [Security.AccessControl.FileSystemRights]::ChangePermissions -bor [Security.AccessControl.FileSystemRights]::TakeOwnership
    $trusted=@($Owner,'S-1-5-18','S-1-5-32-544','S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464')
    while ($null -ne $parent) {
        if ($parent.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Native ancestor reparse forbidden' }
        foreach ($rule in (Get-Acl -LiteralPath $parent.FullName).GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier])) {
            if ($rule.PropagationFlags -band [Security.AccessControl.PropagationFlags]::InheritOnly) { continue }
            if ($rule.AccessControlType -eq 'Allow' -and (Sid $rule.IdentityReference.Value) -notin $trusted -and ($rule.FileSystemRights -band $danger)) { throw 'Untrusted native ancestor replacement permission' }
        }
        $parent=$parent.Parent
    }
}
function Hash-Text([string]$Value) {
    $sha=[Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($Value)))).Replace('-','').ToLowerInvariant() } finally { $sha.Dispose() }
}
function Env-Literal([string]$Value) {
    $value=$Value.Trim()
    if ($value.Length -ge 2 -and (($value.StartsWith('"') -and $value.EndsWith('"')) -or ($value.StartsWith("'") -and $value.EndsWith("'")))) { $value=$value.Substring(1,$value.Length-2) }
    if (-not $value -or $value -match '[\$`#\r\n]') { throw 'Ambiguous native dotenv selection refused' }
    return $value
}
function Assert-SelectionBinding([string]$ExpectedDataDir,[string]$SelectedDataDir,[string]$ExpectedConfig,[string]$SelectedConfig,[string]$SecureAuth) {
    if ($ExpectedDataDir -ne $SelectedDataDir -or $ExpectedConfig -ne $SelectedConfig -or ($SecureAuth -and $SecureAuth -ne '1')) { throw 'Native config selection or secure-auth drift' }
}
function Environment-Binding($Plan,$Task) {
    $script:Gate='native_environment_selection'
    $owner=$Plan.owner_sid
    $data=Local-Absolute $Plan.data_dir
    $config=Local-Absolute $Plan.config_path
    Assert-SelectionBinding $data (Local-Absolute (Split-Path $config -Parent)) $config (Local-Absolute (Join-Path $data 'config.json')) ''
    foreach ($path in @($data,$Plan.python,$config,$Plan.wheel)) { Guard-Ancestry $path $owner }
    $working=$Task.Actions[0].WorkingDirectory
    if (-not $working) { $working=Join-Path $env:SystemRoot 'System32' }
    $working=Local-Absolute $working;Guard-Ancestry $working $owner
    $values=[ordered]@{working_directory=$working;data_dir=$data;config_path=$config}
    $explicit=$false
    foreach ($scope in @('Process','User','Machine')) {
        $envData=[Environment]::GetEnvironmentVariable('ANIMUS_DATA_DIR',$scope)
        $secure=[Environment]::GetEnvironmentVariable('ANIMUS_SECURE_AUTH',$scope)
        if ($envData) { $envData=Local-Absolute $envData;Assert-SelectionBinding $data $envData $config (Local-Absolute (Join-Path $envData 'config.json')) $secure;$explicit=$true }
        elseif ($secure -and $secure -ne '1') { throw 'Explicit insecure native environment' }
        $values[$scope+'_data_dir']=$envData;$values[$scope+'_secure_auth']=$secure
    }
    $envPath=Join-Path $working '.env'
    $values['dotenv_path']=$envPath;$values['dotenv_sha256']='absent'
    if (Test-Path -LiteralPath $envPath) {
        Guard-Ancestry $envPath $owner
        if ((Get-Item -LiteralPath $envPath).Length -gt 1048576) { throw 'Native dotenv bound exceeded' }
        $seen=@{}
        foreach ($line in [IO.File]::ReadAllLines($envPath)) {
            if ($line -match '^\s*(?:export\s+)?(ANIMUS_DATA_DIR|ANIMUS_SECURE_AUTH)\s*=\s*(.*?)\s*$') {
                $key=$Matches[1];$value=Env-Literal $Matches[2]
                if ($seen.ContainsKey($key)) { throw 'Ambiguous duplicate native dotenv selector' }
                $seen[$key]=$value
                if ($key -eq 'ANIMUS_DATA_DIR') { $value=Local-Absolute $value;Assert-SelectionBinding $data $value $config (Local-Absolute (Join-Path $value 'config.json')) '';$explicit=$true }
                elseif ($value -ne '1') { throw 'Native dotenv disables strict auth' }
            }
        }
        $values['dotenv_sha256']=Hash $envPath
    }
    if (-not $explicit) {
        $default=Local-Absolute (Join-Path ([Environment]::GetFolderPath('UserProfile')) '.animus')
        Assert-SelectionBinding $data $default $config (Local-Absolute (Join-Path $default 'config.json')) ''
    }
    $saved=Get-Content -LiteralPath $config -Raw | ConvertFrom-Json
    if ($saved.node_id -cne $Plan.node_id -or -not $saved.data_dir -or (Local-Absolute $saved.data_dir) -ne $data) { throw 'Persistent native identity/data selection differs' }
    return Hash-Text ($values | ConvertTo-Json -Compress)
}
function Write-PrivateJson([string]$Path,$Value,[string]$Owner) {
    $temp=$Path+'.'+[Guid]::NewGuid().ToString('N')+'.tmp'
    $stream=[IO.File]::Open($temp,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
    $stream.Dispose(); Private $temp $Owner
    [IO.File]::WriteAllText($temp,($Value | ConvertTo-Json -Depth 12),[Text.UTF8Encoding]::new($false))
    if (Test-Path -LiteralPath $Path) { [IO.File]::Replace($temp,$Path,[System.Management.Automation.Language.NullString]::Value) } else { [IO.File]::Move($temp,$Path) }
}
function Invoke-PrivateChild([string]$Executable,[string]$Arguments,[string]$Stdout,[string]$Stderr,[string]$Owner,[int]$TimeoutMs,[long]$MaxOutputBytes=1048576) {
    # Own the Process handle from creation. Start-Process redirected streams can
    # lose ExitCode on Windows PowerShell5.1 (PowerShell issue5421).
    if ($TimeoutMs -lt 100 -or $TimeoutMs -gt 600000 -or $MaxOutputBytes -lt 1 -or $MaxOutputBytes -gt 10485760 -or $Stdout -eq $Stderr) { throw 'Invalid bounded child parameters' }
    foreach ($path in @($Executable,(Split-Path $Stdout -Parent),(Split-Path $Stderr -Parent))) { Guard-Ancestry $path $Owner }
    $outputStream=$null;$errorStream=$null;$child=$null;$launched=$false
    try {
        foreach ($path in @($Stdout,$Stderr)) {
            $new=[IO.File]::Open($path,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None);$new.Dispose();Private $path $Owner
        }
        $outputStream=[IO.File]::Open($Stdout,[IO.FileMode]::Open,[IO.FileAccess]::Write,[IO.FileShare]::None)
        $errorStream=[IO.File]::Open($Stderr,[IO.FileMode]::Open,[IO.FileAccess]::Write,[IO.FileShare]::None)
        $start=[Diagnostics.ProcessStartInfo]::new();$start.FileName=$Executable;$start.Arguments=$Arguments;$start.UseShellExecute=$false;$start.CreateNoWindow=$true;$start.RedirectStandardOutput=$true;$start.RedirectStandardError=$true;$start.RedirectStandardInput=$true
        $child=[Diagnostics.Process]::new();$child.StartInfo=$start
        $launched=$child.Start();if(-not $launched){throw 'Owned native child did not start'};$child.StandardInput.Close()
        $outBuffer=New-Object byte[] 8192;$errBuffer=New-Object byte[] 8192
        $readOut=$child.StandardOutput.BaseStream.ReadAsync($outBuffer,0,$outBuffer.Length)
        $readErr=$child.StandardError.BaseStream.ReadAsync($errBuffer,0,$errBuffer.Length)
        $outDone=$false;$errDone=$false;$total=0L;$drain=$null;$clock=[Diagnostics.Stopwatch]::StartNew()
        while ($true) {
            if (-not $outDone -and $readOut.IsCompleted) {
                $count=$readOut.GetAwaiter().GetResult()
                if($count -eq 0){$outDone=$true}else{if($total+$count -gt $MaxOutputBytes){throw 'Owned native child output limit exceeded'};$outputStream.Write($outBuffer,0,$count);$total+=$count;$readOut=$child.StandardOutput.BaseStream.ReadAsync($outBuffer,0,$outBuffer.Length)}
            }
            if (-not $errDone -and $readErr.IsCompleted) {
                $count=$readErr.GetAwaiter().GetResult()
                if($count -eq 0){$errDone=$true}else{if($total+$count -gt $MaxOutputBytes){throw 'Owned native child output limit exceeded'};$errorStream.Write($errBuffer,0,$count);$total+=$count;$readErr=$child.StandardError.BaseStream.ReadAsync($errBuffer,0,$errBuffer.Length)}
            }
            if($child.HasExited){if($outDone -and $errDone){break};if($null -eq $drain){$drain=[Diagnostics.Stopwatch]::StartNew()};if($drain.ElapsedMilliseconds -ge 5000){throw 'Owned native child stream deadline exceeded'}}
            elseif($clock.ElapsedMilliseconds -ge $TimeoutMs){throw 'Owned native child deadline exceeded'}
            $pending=@();if(-not $outDone){$pending+=,$readOut};if(-not $errDone){$pending+=,$readErr}
            if($pending.Count){$null=[Threading.Tasks.Task]::WaitAny([Threading.Tasks.Task[]]$pending,50)}else{$null=$child.WaitForExit(50)}
        }
        $outputStream.Flush($true);$errorStream.Flush($true)
        $code=$child.ExitCode;if($null -eq $code){throw 'Owned native child exit status unavailable'}
        return [int]$code
    } finally {
        if($launched -and $null -ne $child){try{if(-not $child.HasExited){$child.Kill();$null=$child.WaitForExit(5000)}}catch{}}
        if($null -ne $outputStream){$outputStream.Dispose()};if($null -ne $errorStream){$errorStream.Dispose()};if($null -ne $child){$child.Dispose()}
    }
}
function Task-Binding($Task) {
    $xml=Export-ScheduledTask -TaskName $Task.TaskName -TaskPath $Task.TaskPath
    # Ignore only Settings/Enabled while the qualified own job temporarily
    # disables it. Windows exports may omit this schema-default-true element.
    # Removing the one permitted flag also normalizes its insertion position;
    # every other task field remains bound to the exported XML hash.
    $document=[xml]$xml
    $settings=$document.SelectNodes('/*[local-name()="Task"]/*[local-name()="Settings"]')
    if ($settings.Count -ne 1) { throw 'Exactly one native task Settings element required' }
    $enabled=$settings[0].SelectNodes('./*[local-name()="Enabled"]')
    if ($enabled.Count -gt 1) { throw 'Duplicate native enabled settings refused' }
    if ($enabled.Count -eq 1) {
        if ($enabled[0].InnerText -cnotin @('true','false','1','0')) { throw 'Native enabled setting is not a schema boolean' }
        $null=$settings[0].RemoveChild($enabled[0])
    }
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
    foreach ($path in @($Plan.python,$Plan.process_python,$Plan.config_path,$Plan.wheel,$Plan.runner)) {
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
    $selected=Validate-Task $Plan
    Guard-Ancestry $Plan.runner $Plan.owner_sid
    if ((Environment-Binding $Plan $selected) -ne $Plan.environment_fingerprint) { throw 'Native environment/config selection drift; no stop/install/restart' }
}
function Assert-VerifiedRestartEvidence([string]$ExpectedVersion,[string]$InstalledVersion,[long]$PidValue,[long]$ExpectedCreation,[long]$ObservedCreation,[bool]$TaskRunning,[bool]$ProcessAlive) {
    if ($ExpectedVersion -cne $InstalledVersion -or $PidValue -le 0 -or $ExpectedCreation -le 0 -or $ExpectedCreation -ne $ObservedCreation -or -not $TaskRunning -or -not $ProcessAlive) { throw 'Actual package/task/process evidence is incomplete' }
}
function Source-Alive($Plan) {
    $process=Get-CimInstance Win32_Process -Filter ('ProcessId='+[int]$Plan.source_pid) -ErrorAction SilentlyContinue
    if ($null -eq $process) { return $false }
    return $process.ExecutablePath -eq $Plan.process_python -and $process.CreationDate.ToUniversalTime().Ticks -eq [long]$Plan.source_creation_ticks
}
function Native-ProcessMatches($Process,$Plan,$Task) {
    if ($null -eq $Process -or $Process.ExecutablePath -ne $Plan.process_python -or -not $Process.CommandLine -or -not $Process.CommandLine.Trim().EndsWith($Task.Actions[0].Arguments.Trim(),[StringComparison]::Ordinal)) { return $false }
    if ($Plan.process_python -eq $Plan.python) { return $true }
    # Windows venv/Store launchers spawn the real image. Bind its immediate
    # parent to this exact task interpreter and action, never another Python.
    $launcher=Get-CimInstance Win32_Process -Filter ('ProcessId='+[int]$Process.ParentProcessId) -ErrorAction SilentlyContinue
    if ($null -eq $launcher -or $launcher.ExecutablePath -ne $Plan.python -or -not $launcher.CommandLine -or -not $launcher.CommandLine.Trim().EndsWith($Task.Actions[0].Arguments.Trim(),[StringComparison]::Ordinal) -or $launcher.CreationDate -gt $Process.CreationDate) { return $false }
    $identity=Invoke-CimMethod -InputObject $launcher -MethodName GetOwnerSid
    return $identity.ReturnValue -eq 0 -and $identity.Sid -eq $Plan.owner_sid
}
try {
    if ($Mode -eq 'Register') {
        $spec=[Console]::In.ReadToEnd() | ConvertFrom-Json
        $owner=[Security.Principal.WindowsIdentity]::GetCurrent().User.Value
        $script:Gate='registration_binding'
        $task=Get-ScheduledTask -TaskName $spec.task_name -TaskPath $spec.task_path
        if ($task.Actions.Count -ne 1 -or (Sid $task.Principal.UserId) -ne $owner -or $task.Actions[0].Execute -ne $spec.python -or $task.Actions[0].Arguments -notmatch '^\s*-m\s+animus\.cli\s+daemon(?:\s|$)') { throw 'Current-user direct native task required' }
        $source=Get-CimInstance Win32_Process -Filter ('ProcessId='+[int]$spec.source_pid)
        $sourceOwner=Invoke-CimMethod -InputObject $source -MethodName GetOwnerSid
        if ($sourceOwner.ReturnValue -ne 0 -or $sourceOwner.Sid -ne $owner) { throw 'Source process belongs to another principal' }
        $spec | Add-Member -NotePropertyName owner_sid -NotePropertyValue $owner
        if (-not (Native-ProcessMatches $source $spec $task)) { throw 'Daemon task/process attribution mismatch' }
        if ($spec.process_python -ne $spec.python -and $source.ParentProcessId -ne $spec.source_launcher_pid) { throw 'Native launcher identity drift' }
        $environmentFingerprint=Environment-Binding $spec $task
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
        $plan=@{version=1;data_dir=$spec.data_dir;environment_fingerprint=$environmentFingerprint;task_name=$spec.task_name;task_path=$spec.task_path;task_sha256=(Task-Binding $task);owner_sid=$owner;python=$spec.python;process_python=$spec.process_python;config_path=$spec.config_path;config_sha256=$spec.config_sha256;node_id=$spec.node_id;wheel=$spec.wheel;wheel_sha256=$spec.wheel_sha256;expected_version=$spec.expected_version;source_pid=$spec.source_pid;source_creation_ticks=$source.CreationDate.ToUniversalTime().Ticks;deadline_ticks=[DateTime]::UtcNow.AddMinutes(15).Ticks;job_name=$jobName;runner=$runner;runner_sha256=(Hash $runner)}
        Write-PrivateJson $PlanPath $plan $owner
        Validate-Plan $plan
        $script:Gate='register_independent_update_task'
        $ps=Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
        $consoleOut=Join-Path $jobDir 'runner.stdout';$consoleErr=Join-Path $jobDir 'runner.stderr'
        foreach($file in @($consoleOut,$consoleErr)){$new=[IO.File]::Open($file,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None);$new.Dispose();Private $file $owner}
        # Preserve even parser/loader failures from the independent scheduler
        # process. Private console files are diagnostic, never completion proof.
        $command="& '"+$runner.Replace("'","''")+"' -Mode Run -PlanPath '"+$PlanPath.Replace("'","''")+"' 1> '"+$consoleOut.Replace("'","''")+"' 2> '"+$consoleErr.Replace("'","''")+"'"
        $encoded=[Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($command))
        $action=New-ScheduledTaskAction -Execute $ps -Argument ('-NoProfile -NonInteractive -ExecutionPolicy RemoteSigned -EncodedCommand '+$encoded)
        $trigger=New-ScheduledTaskTrigger -Once -At ([DateTime]::Now.AddSeconds(10))
        $settings=New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 15) -StartWhenAvailable
        if ($task.Principal.LogonType -notin @('Interactive','S4U')) { throw 'Unsupported native task logon type; do not change credentials' }
        $principal=New-ScheduledTaskPrincipal -UserId $task.Principal.UserId -LogonType $task.Principal.LogonType -RunLevel $task.Principal.RunLevel
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
        Validate-Plan $plan
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
    $remaining=@(Get-CimInstance Win32_Process | Where-Object {($_.ExecutablePath -eq $plan.python -or $_.ExecutablePath -eq $plan.process_python) -and $_.CommandLine -and $_.CommandLine.Trim().EndsWith($task.Actions[0].Arguments.Trim(),[StringComparison]::Ordinal)})
    if ($remaining.Count) { throw 'Native daemon still alive; no broad process kill permitted' }
    Write-PrivateJson $receipt @{status='installing';installed=$false;restart_verified=$false;owner='agent'} $plan.owner_sid
    $script:Gate='bounded_local_wheel_install'
    $stdout=Join-Path (Split-Path $PlanPath -Parent) 'pip.stdout'; $stderr=Join-Path (Split-Path $PlanPath -Parent) 'pip.stderr'
    $arguments='-m pip install --upgrade --quiet --disable-pip-version-check --no-index --no-deps "'+$plan.wheel+'"'
    $pipCode=Invoke-PrivateChild $plan.python $arguments $stdout $stderr $plan.owner_sid 600000
    if ($pipCode -ne 0) { throw 'Native wheel install failed; no other process was killed' }
    $script:Gate='installed_version_and_config'
    $version=@(& $plan.python -c 'import animus;print(animus.__version__)' 2>&1)
    if ($LASTEXITCODE -ne 0 -or ($version -join '').Trim() -cne $plan.expected_version) { throw 'Installed version mismatch' }
    $script:InstalledVerified=$true
    $script:Gate='native_dependency_integrity'
    $checkOut=Join-Path (Split-Path $PlanPath -Parent) 'dependency.stdout'; $checkErr=Join-Path (Split-Path $PlanPath -Parent) 'dependency.stderr'
    $checkCode=Invoke-PrivateChild $plan.python '-m pip check' $checkOut $checkErr $plan.owner_sid 30000
    if ($checkCode -ne 0) { throw 'Native package dependency constraints are not satisfied' }
    Validate-Plan $plan
    $script:Gate='verify_actual_native_restart'
    $started=[DateTime]::UtcNow
    Enable-ScheduledTask -TaskName $plan.task_name -TaskPath $plan.task_path | Out-Null
    Start-ScheduledTask -TaskName $plan.task_name -TaskPath $plan.task_path
    $deadline=[DateTime]::UtcNow.AddSeconds(60); $verified=$false; $pidValue=$null; $creation=$null
    do {
        $task=Validate-Task $plan
        $processes=@(Get-CimInstance Win32_Process | Where-Object {$_.ExecutablePath -eq $plan.process_python -and $_.CreationDate -and $_.CreationDate.ToUniversalTime() -ge $started -and (Native-ProcessMatches $_ $plan $task)})
        if ($task.State -eq 'Running' -and $processes.Count -eq 1) { $verified=$true; $pidValue=$processes[0].ProcessId; $creation=$processes[0].CreationDate.ToUniversalTime().Ticks; break }
        Start-Sleep -Milliseconds 250
    } while ([DateTime]::UtcNow -lt $deadline)
    if (-not $verified) { throw 'Task start requested but native process not verified' }
    Start-Sleep -Seconds 3
    $process=Get-CimInstance Win32_Process -Filter ('ProcessId='+[int]$pidValue) -ErrorAction SilentlyContinue
    if ($null -eq $process -or $process.CreationDate.ToUniversalTime().Ticks -ne $creation -or -not (Native-ProcessMatches $process $plan $task)) { throw 'Native restarted process did not remain alive' }
    $task=Validate-Task $plan
    $processOwner=Invoke-CimMethod -InputObject $process -MethodName GetOwnerSid
    if ($processOwner.ReturnValue -ne 0 -or $processOwner.Sid -ne $plan.owner_sid) { throw 'Restart process principal mismatch' }
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
