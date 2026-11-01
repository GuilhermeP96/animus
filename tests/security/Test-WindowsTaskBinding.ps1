$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
$source=Join-Path $PSScriptRoot '../../animus/network/windows-update-task.ps1'
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($source,[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'Runner syntax failed'}
$definition=$ast.Find({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Task-Binding'},$true)
if($null -eq $definition){throw 'Missing task binding function'}
Invoke-Expression $definition.Extent.Text
# Stub only the Windows export boundary. Execute the actual XML/hash function.
function Export-ScheduledTask { param($TaskName,$TaskPath) return $script:TaskXml }
$task=[pscustomobject]@{TaskName='fixture';TaskPath='\'}
$base='<Task xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task"><Settings><Hidden>false</Hidden></Settings><Actions><Exec><Command>python.exe</Command><Arguments>-m animus.cli daemon</Arguments></Exec></Actions></Task>'
$script:TaskXml=$base;$expected=Task-Binding $task;$checks=1
foreach($flag in @('true','false','1','0')){
 $script:TaskXml=$base.Replace('<Hidden>',('<Enabled>'+$flag+'</Enabled><Hidden>'))
 if((Task-Binding $task) -cne $expected){throw 'Implicit/explicit temporary flag binding differs'};$checks++
}
foreach($change in @($base.Replace('python.exe','other.exe'),$base.Replace('daemon','server'),$base.Replace('<Hidden>false','<Hidden>true'))){
 $script:TaskXml=$change;if((Task-Binding $task) -ceq $expected){throw 'Unrelated task drift was accepted'};$checks++
}
foreach($bad in @($base.Replace('<Hidden>','<Enabled>true</Enabled><Enabled>false</Enabled><Hidden>'),$base.Replace('<Hidden>','<Enabled>unknown</Enabled><Hidden>'),$base.Replace('<Settings><Hidden>false</Hidden></Settings>',''))){
 $script:TaskXml=$bad;$refused=$false;try{$null=Task-Binding $task}catch{$refused=$true}
 if(-not $refused){throw 'Invalid task XML was accepted'};$checks++
}
Write-Output ('task_binding_checks_passed='+$checks)
