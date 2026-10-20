$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
$path=Join-Path $PSScriptRoot '../../animus/network/windows-update-task.ps1'
$tokens=$null;$errors=$null;$ast=[Management.Automation.Language.Parser]::ParseFile($path,[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'Runner syntax failed'}
$fn=$ast.Find({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Native-ProcessMatches'},$true)
Invoke-Expression $fn.Extent.Text
$now=[DateTime]::UtcNow
$plan=[pscustomobject]@{python='C:\Owned\python.exe';process_python='C:\Store\python3.13.exe';owner_sid='S-1-5-21-1'}
$task=[pscustomobject]@{Actions=@([pscustomobject]@{Arguments='-m animus.cli daemon'})}
$script:parent=[pscustomobject]@{ExecutablePath=$plan.python;CommandLine='python.exe -m animus.cli daemon';CreationDate=$now;ProcessId=12}
$script:owner='S-1-5-21-1'
function Get-CimInstance { param($ClassName,$Filter,$ErrorAction) return $script:parent }
function Invoke-CimMethod { param($InputObject,$MethodName) return @{ReturnValue=0;Sid=$script:owner} }
$child=[pscustomobject]@{ExecutablePath=$plan.process_python;CommandLine='python3.13.exe -m animus.cli daemon';CreationDate=$now.AddSeconds(1);ParentProcessId=12}
if(-not (Native-ProcessMatches $child $plan $task)){throw 'Bound launcher child refused'}
$script:owner='S-1-5-21-2';if(Native-ProcessMatches $child $plan $task){throw 'Foreign launcher accepted'};$script:owner=$plan.owner_sid
$script:parent.ExecutablePath='C:\Other\python.exe';if(Native-ProcessMatches $child $plan $task){throw 'Different interpreter adopted'};$script:parent.ExecutablePath=$plan.python
$script:parent.CommandLine='python.exe other.py';if(Native-ProcessMatches $child $plan $task){throw 'Different task action adopted'};$script:parent.CommandLine=$child.CommandLine
$script:parent.CreationDate=$now.AddSeconds(2);if(Native-ProcessMatches $child $plan $task){throw 'Reused parent PID accepted'};$script:parent.CreationDate=$now
$child.ExecutablePath='C:\Other\python.exe';if(Native-ProcessMatches $child $plan $task){throw 'Different child image accepted'}
$plan.process_python=$plan.python;$child.ExecutablePath=$plan.python
if(-not (Native-ProcessMatches $child $plan $task)){throw 'Direct native process refused'}
Write-Output 'native_launcher_binding_checks_passed=7'
