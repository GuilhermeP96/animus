$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$source=Join-Path $PSScriptRoot '../../animus/network/windows-update-task.ps1'
$tokens=$null; $errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($source,[ref]$tokens,[ref]$errors)
if ($errors.Count) { throw 'Update task PowerShell syntax failed' }
$definition=$ast.Find({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Assert-VerifiedRestartEvidence'},$true)
if ($null -eq $definition) { throw 'Missing pure restart evidence gate' }
Invoke-Expression $definition.Extent.Text
Assert-VerifiedRestartEvidence '99.0.0' '99.0.0' 123 1000 1000 $true $true
$count=1
foreach ($case in @(
    @('99.0.0','98.0.0',123,1000,1000,$true,$true),
    @('99.0.0','99.0.0',0,1000,1000,$true,$true),
    @('99.0.0','99.0.0',123,0,0,$true,$true),
    @('99.0.0','99.0.0',123,1000,1001,$true,$true),
    @('99.0.0','99.0.0',123,1000,1000,$false,$true),
    @('99.0.0','99.0.0',123,1000,1000,$true,$false)
)) {
    $refused=$false
    try { Assert-VerifiedRestartEvidence @case } catch { $refused=$true }
    if (-not $refused) { throw 'Incomplete restart evidence was accepted' }
    $count++
}
Write-Output ('restart_evidence_checks_passed='+$count)

$selection=$ast.Find({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Assert-SelectionBinding'},$true)
if ($null -eq $selection) { throw 'Missing native selector binding gate' }
Invoke-Expression $selection.Extent.Text
Assert-SelectionBinding 'C:\Fixture\Data' 'C:\Fixture\Data' 'C:\Fixture\Data\config.json' 'C:\Fixture\Data\config.json' ''
$selectionChecks=1
Assert-SelectionBinding 'C:\Fixture\Data' 'c:\fixture\data' 'C:\Fixture\Data\config.json' 'c:\fixture\data\config.json' '1'
$selectionChecks++
foreach ($case in @(
 @('C:\Fixture\Data','C:\Other','C:\Fixture\Data\config.json','C:\Other\config.json','1'),
 @('C:\Fixture\Data','C:\Fixture\Data','C:\Fixture\Data\config.json','C:\Other\config.json','1'),
 @('C:\Fixture\Data','C:\Fixture\Data','C:\Fixture\Data\config.json','C:\Fixture\Data\config.json','0')
)) {
 $refused=$false
 try { Assert-SelectionBinding @case } catch { $refused=$true }
 if (-not $refused) { throw 'Config/secure-auth drift was accepted' }
 $selectionChecks++
}
Write-Output ('selection_evidence_checks_passed='+$selectionChecks)
