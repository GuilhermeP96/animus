[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$NativePython,[Parameter(Mandatory=$true)][string]$Workspace)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
$source=Join-Path $PSScriptRoot '../../animus/network/windows-update-task.ps1'
$tokens=$null;$errors=$null;$ast=[Management.Automation.Language.Parser]::ParseFile($source,[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'Runner syntax failed'}
foreach($name in @('Sid','Private','Parent','Local-Absolute','Guard-Ancestry','Invoke-PrivateChild')){
 $d=$ast.Find({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name},$true)
 if($null -eq $d){throw 'Missing child gate function'};Invoke-Expression $d.Extent.Text
}
$owner=[Security.Principal.WindowsIdentity]::GetCurrent().User.Value;Guard-Ancestry $Workspace $owner
$root=Join-Path $Workspace ('child-test-'+[Guid]::NewGuid().ToString('N'));[IO.Directory]::CreateDirectory($root)|Out-Null;Private $root $owner $true
$checks=0
function Run-Python([string]$Code,[int]$Timeout=10000,[long]$Limit=1048576){
 $script=Join-Path $root ([Guid]::NewGuid().ToString('N')+'.py');[IO.File]::WriteAllText($script,$Code,[Text.UTF8Encoding]::new($false));Private $script $owner
 $script:LastOut=$script+'.stdout';$script:LastErr=$script+'.stderr'
 return Invoke-PrivateChild $NativePython ('"'+$script+'"') $script:LastOut $script:LastErr $owner $Timeout $Limit
}
foreach($expected in @(0,7)){
 $code=Run-Python ('import sys;print("stdout");sys.stderr.write("stderr");sys.exit('+$expected+')')
 if($code -ne $expected -or (Get-Item $script:LastOut).Length -eq 0 -or (Get-Item $script:LastErr).Length -eq 0){throw 'Actual redirected exit status mismatch'};$checks++
}
$code=Run-Python 'import sys,threading;f=lambda s:s.write("x"*131072);t=threading.Thread(target=f,args=(sys.stderr,));t.start();f(sys.stdout);t.join()'
if($code -ne 0 -or (Get-Item $script:LastOut).Length -ne 131072 -or (Get-Item $script:LastErr).Length -ne 131072){throw 'Concurrent pipes were not drained'};$checks++
$refused=$false;$timer=[Diagnostics.Stopwatch]::StartNew();try{$null=Run-Python 'import time;time.sleep(30)' 200}catch{if($_.Exception.Message -eq 'Owned native child deadline exceeded'){$refused=$true}else{throw}}
if(-not $refused -or $timer.ElapsedMilliseconds -gt 10000){throw 'Native child deadline not bounded'};$checks++
$refused=$false;try{$null=Run-Python 'import sys;sys.stdout.write("x"*65536);sys.stderr.write("y"*65536)' 10000 1024}catch{if($_.Exception.Message -eq 'Owned native child output limit exceeded'){$refused=$true}else{throw}}
if(-not $refused -or ((Get-Item $script:LastOut).Length+(Get-Item $script:LastErr).Length) -gt 1024){throw 'Strict combined log cap not enforced'};$checks++
# Missing executable fails before launch; no process/task/production mutation.
$refused=$false;try{$null=Invoke-PrivateChild (Join-Path $root 'absent.exe') '' (Join-Path $root 'absent.out') (Join-Path $root 'absent.err') $owner 1000}catch{$refused=$true}
if(-not $refused){throw 'Absent child executable accepted'};$checks++
# Exercise Process.Start failure after guards, and prove exclusive logs close.
$bad=Join-Path $root 'not-executable.txt';[IO.File]::WriteAllText($bad,'not a PE executable');Private $bad $owner
$badOut=Join-Path $root 'start-failure.out';$badErr=Join-Path $root 'start-failure.err';$refused=$false
try{$null=Invoke-PrivateChild $bad '' $badOut $badErr $owner 1000}catch{if(Test-Path -LiteralPath $badOut){$refused=$true}else{throw}}
if(-not $refused){throw 'Real Process.Start failure not exercised'}
foreach($path in @($badOut,$badErr)){$handle=[IO.File]::Open($path,[IO.FileMode]::Open,[IO.FileAccess]::Write,[IO.FileShare]::None);$handle.Dispose()};$checks++
# This one owned descendant exits by itself after7s; never enumerate/kill others.
$refused=$false;$timer=[Diagnostics.Stopwatch]::StartNew()
try{$null=Run-Python 'import sys,subprocess;subprocess.Popen([sys.executable,"-c","import time;time.sleep(7)"])' 15000}catch{if($_.Exception.Message -eq 'Owned native child stream deadline exceeded'){$refused=$true}else{throw}}
if(-not $refused -or $timer.ElapsedMilliseconds -gt 12000){throw 'Inherited pipe drain was not bounded'}
Start-Sleep -Seconds 3;$checks++
Write-Output (@{status='passed';private_child_checks_passed=$checks;native_scheduler_tested=$false;production_changed=$false}|ConvertTo-Json -Compress)
