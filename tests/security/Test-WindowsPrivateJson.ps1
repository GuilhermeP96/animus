[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$Workspace)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
$source=Join-Path $PSScriptRoot '../../animus/network/windows-update-task.ps1'
$tokens=$null;$errors=$null;$ast=[Management.Automation.Language.Parser]::ParseFile($source,[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'Runner syntax failed'}
foreach($name in @('Sid','Private','Parent','Local-Absolute','Guard-Ancestry','Write-PrivateJson')){
 $d=$ast.Find({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name},$true)
 if($null -eq $d){throw 'Missing private JSON gate'};Invoke-Expression $d.Extent.Text
}
$owner=[Security.Principal.WindowsIdentity]::GetCurrent().User.Value;Guard-Ancestry $Workspace $owner
$root=Join-Path $Workspace ('json-test-'+[Guid]::NewGuid().ToString('N'));[IO.Directory]::CreateDirectory($root)|Out-Null;Private $root $owner $true
$path=Join-Path $root 'fixture.json';$checks=0
foreach($sequence in @(1,2,3,4)){
 Write-PrivateJson $path @{fixture_sequence=$sequence;production_changed=$false} $owner
 $value=[IO.File]::ReadAllText($path)|ConvertFrom-Json
 if($value.fixture_sequence -ne $sequence -or $value.production_changed -ne $false){throw 'Atomic private JSON readback failed'}
 $acl=Get-Acl -LiteralPath $path
 if(-not $acl.AreAccessRulesProtected -or $acl.GetOwner([Security.Principal.SecurityIdentifier]).Value -ne $owner){throw 'Atomic private JSON owner/ACL changed'}
 if(@(Get-ChildItem -LiteralPath $root -Filter '*.tmp').Count){throw 'Successful atomic write left a temporary file'};$checks++
}
Write-Output (@{status='passed';private_json_checks_passed=$checks;production_changed=$false}|ConvertTo-Json -Compress)
