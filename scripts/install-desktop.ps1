param(
    [Parameter(Mandatory=$true)][string]$PackageDirectory,
    [Parameter(Mandatory=$true)][ValidatePattern('^[a-fA-F0-9]{64}$')][string]$ExpectedSha256,
    [string]$DataDirectory=(Join-Path $env:USERPROFILE '.animus'),
    [switch]$DesktopOnly
)
$ErrorActionPreference='Stop'
# ASCII script, binary copies and explicit UTF-8 IPC. No credential changes.
$data=[IO.Path]::GetFullPath($DataDirectory)
if($data.StartsWith('\\')){throw 'Local peer data required'}
$source=Join-Path $PackageDirectory 'Animus.exe'
if((Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash -ne $ExpectedSha256){throw 'Desktop checksum mismatch'}
$python=Join-Path $data 'runtime\Scripts\pythonw.exe'
foreach($path in @($data,$python,(Join-Path $data 'config.json'))){
    $item=Get-Item -LiteralPath $path
    if($item.Attributes -band [IO.FileAttributes]::ReparsePoint){throw 'Native peer reparse refused'}
}
$sid=[Security.Principal.WindowsIdentity]::GetCurrent().User
$task=Get-ScheduledTask -TaskName AnimusPeerDaemon
if($task.Principal.UserId -match '^S-1-'){$taskOwner=New-Object Security.Principal.SecurityIdentifier($task.Principal.UserId)}
else{$taskOwner=(New-Object Security.Principal.NTAccount($task.Principal.UserId)).Translate([Security.Principal.SecurityIdentifier])}
if($taskOwner -ne $sid -or $task.Actions.Count -ne 1){throw 'Only the current-user native peer task can be migrated'}
$oldPython=[IO.Path]::GetFullPath($task.Actions[0].Execute)
if($oldPython -notin @((Join-Path $data 'runtime\Scripts\python.exe'),$python) -or $task.Actions[0].Arguments -notmatch '^\s*-m\s+animus\.cli\s+daemon(?:\s|$)'){throw 'Unexpected native daemon action'}
$config=Join-Path $data 'config.json';$configHash=(Get-FileHash -LiteralPath $config).Hash
$checkpoints=Join-Path $data ('desktop\checkpoints\'+[DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ')+'-'+[Guid]::NewGuid().ToString('N'))
[IO.Directory]::CreateDirectory($checkpoints) | Out-Null
[IO.File]::WriteAllText((Join-Path $checkpoints 'daemon-task.xml'),(Export-ScheduledTask -TaskName AnimusPeerDaemon),[Text.Encoding]::Unicode)
$desktop=Join-Path $data 'desktop\0.9.3'
[IO.Directory]::CreateDirectory($desktop) | Out-Null
if((Get-Item -LiteralPath $desktop).Attributes -band [IO.FileAttributes]::ReparsePoint){throw 'Desktop reparse refused'}
$acl=Get-Acl -LiteralPath $desktop
$acl.SetAccessRuleProtection($true,$false)
$acl.SetOwner($sid)
$acl.AddAccessRule((New-Object Security.AccessControl.FileSystemAccessRule($sid,'FullControl','ContainerInherit,ObjectInherit','None','Allow')))
$acl.AddAccessRule((New-Object Security.AccessControl.FileSystemAccessRule('SYSTEM','FullControl','ContainerInherit,ObjectInherit','None','Allow')))
Set-Acl -LiteralPath $desktop -AclObject $acl
$exe=Join-Path $desktop 'Animus.exe'
$existing=Get-ScheduledTask -TaskName AnimusPeerTray -ErrorAction SilentlyContinue
if($existing){
    [IO.File]::WriteAllText((Join-Path $checkpoints 'tray-task.xml'),(Export-ScheduledTask -TaskName AnimusPeerTray),[Text.Encoding]::Unicode)
    $existingExe=$existing.Actions[0].Execute
    if(-not ([IO.Path]::GetFullPath($existingExe)).StartsWith((Join-Path $data 'desktop\'),[StringComparison]::OrdinalIgnoreCase)){throw 'Unexpected existing tray task'}
    $quit=Start-Process -FilePath $existingExe -ArgumentList @('--data-dir',('"'+$data+'"'),'--quit') -WindowStyle Hidden -PassThru -Wait
    Start-Sleep -Seconds 2
}
if(Test-Path -LiteralPath $exe){
    if((Get-FileHash -LiteralPath $exe).Hash -ne $ExpectedSha256){throw 'Immutable desktop version already contains different bytes'}
}else{Copy-Item -LiteralPath $source -Destination $exe}
Copy-Item -LiteralPath (Join-Path $PackageDirectory 'LICENSE'),(Join-Path $PackageDirectory 'NOTICE') -Destination $desktop
# Preserve task settings/triggers/principal; change only the native interpreter.
if(-not $DesktopOnly){
    Stop-ScheduledTask -TaskName AnimusPeerDaemon
    $action=New-ScheduledTaskAction -Execute $python -Argument $task.Actions[0].Arguments -WorkingDirectory $data
    Set-ScheduledTask -TaskName AnimusPeerDaemon -Action $action | Out-Null
    Start-ScheduledTask -TaskName AnimusPeerDaemon
}
$trayAction=New-ScheduledTaskAction -Execute $exe -Argument ('--background --data-dir "'+$data+'"') -WorkingDirectory $data
$trigger=New-ScheduledTaskTrigger -AtLogOn -User $sid.Value
$principal=New-ScheduledTaskPrincipal -UserId $sid.Value -LogonType Interactive -RunLevel Limited
$settings=New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Days 0) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName AnimusPeerTray -Action $trayAction -Trigger $trigger -Principal $principal -Settings $settings -Description 'Animus desktop tray and local peer dashboard' -Force | Out-Null
$shell=New-Object -ComObject WScript.Shell
foreach($base in @([Environment]::GetFolderPath('Desktop'),[Environment]::GetFolderPath('Programs'))){
    $shortcut=$shell.CreateShortcut((Join-Path $base 'Animus.lnk'))
    $shortcut.TargetPath=$exe;$shortcut.Arguments='--data-dir "'+$data+'"';$shortcut.WorkingDirectory=$data;$shortcut.IconLocation=$exe+',0';$shortcut.Save()
}
Start-ScheduledTask -TaskName AnimusPeerTray
if((Get-FileHash -LiteralPath $config).Hash -ne $configHash){throw 'Configuration changed during install'}
[pscustomobject]@{version='0.9.3';config_preserved=$true;desktop_only=[bool]$DesktopOnly;daemon_interpreter=[IO.Path]::GetFileName((Get-ScheduledTask -TaskName AnimusPeerDaemon).Actions[0].Execute);tray_task='AnimusPeerTray';exe_sha256=(Get-FileHash -LiteralPath $exe).Hash} | ConvertTo-Json -Compress
