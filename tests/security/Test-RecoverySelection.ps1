$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
. (Join-Path $PSScriptRoot '../../scripts/security/windows-local-recovery/Recovery-Selection.ps1')
$script:checks=0
function Assert-Rejected([scriptblock]$Action) {
    $rejected=$false
    try { & $Action } catch { $rejected=$true }
    if (-not $rejected) { throw 'Expected fail-closed selection rejection' }
    $script:checks++
}
Assert-ExplicitRecoverySelection $true 'AnimusFixture' '\' 'C:\Fixture\.animus\config.json' 'fixture-node'
$script:checks++
Assert-ExplicitRecoverySelection $false '' '' '' ''
$script:checks++
Assert-Rejected { Assert-ExplicitRecoverySelection $true '' '\' 'C:\Fixture\config.json' 'fixture-node' }
Assert-Rejected { Assert-ExplicitRecoverySelection $true 'AnimusFixture' '' 'C:\Fixture\config.json' 'fixture-node' }
Assert-Rejected { Assert-ExplicitRecoverySelection $true 'AnimusFixture' '\' '' 'fixture-node' }
Assert-Rejected { Assert-ExplicitRecoverySelection $true 'AnimusFixture' '\' 'C:\Fixture\config.json' '' }
Assert-Rejected { Assert-ExplicitRecoverySelection $true 'AnimusFixture' 'relative' 'C:\Fixture\config.json' 'fixture-node' }
Assert-Rejected { Assert-ExplicitRecoverySelection $true 'AnimusFixture' '\' '\\server\share\config.json' 'fixture-node' }
Assert-Rejected { Assert-ExplicitRecoverySelection $true 'AnimusFixture' '\' 'C:\Fixture\config.json' '../wrong' }
Assert-RecoveryNodeIdentity 'fixture-node' 'fixture-node'
$script:checks++
Assert-Rejected { Assert-RecoveryNodeIdentity 'fixture-node' 'Fixture-node' }
Assert-Rejected { Assert-RecoveryNodeIdentity 'fixture-node' 'other-peer' }
$runtime=[pscustomobject]@{node_id='fixture-node'; task_name='AnimusFixture'; task_path='\'; config_path='C:\Fixture\config.json'}
Assert-RecoveryTargetBinding $true 'AnimusFixture' '\' 'C:\Fixture\config.json' 'fixture-node' $runtime 'fixture-node'
$script:checks++
Assert-Rejected { Assert-RecoveryTargetBinding $true 'OtherTask' '\' 'C:\Fixture\config.json' 'fixture-node' $runtime 'fixture-node' }
Assert-Rejected { Assert-RecoveryTargetBinding $true 'AnimusFixture' '\Other\' 'C:\Fixture\config.json' 'fixture-node' $runtime 'fixture-node' }
Assert-Rejected { Assert-RecoveryTargetBinding $true 'AnimusFixture' '\' 'C:\Other\config.json' 'fixture-node' $runtime 'fixture-node' }
Assert-Rejected { Assert-RecoveryTargetBinding $true 'AnimusFixture' '\' 'C:\Fixture\config.json' 'other-peer' $runtime 'fixture-node' }
Assert-Rejected { Assert-RecoveryTargetBinding $false '' '' '' '' $runtime 'other-peer' }
Write-Output ('selection_checks_passed='+$script:checks)
