# Pure selection/identity gates: independently testable without Windows runtime.
function Assert-ExplicitRecoverySelection {
    param([bool]$NonInteractive,[string]$TaskName,[string]$TaskPath,[string]$ConfigPath,[string]$ExpectedNodeId)
    if (-not $NonInteractive) { return }
    if (-not $TaskName -or -not $TaskPath -or -not $ConfigPath -or -not $ExpectedNodeId) {
        throw 'NonInteractive requires explicit TaskName, TaskPath, ConfigPath and ExpectedNodeId'
    }
    if ($ExpectedNodeId -notmatch '^[A-Za-z0-9_.-]{1,128}$' -or $TaskPath -notmatch '^\\.*\\$|^\\$' -or $ConfigPath -notmatch '^[A-Za-z]:[\\/].+') {
        throw 'NonInteractive requires a bounded identity, exact task path and absolute local config'
    }
}
function Assert-RecoveryNodeIdentity {
    param([string]$ExpectedNodeId,[string]$ActualNodeId)
    if (-not $ActualNodeId -or ($ExpectedNodeId -and $ActualNodeId -cne $ExpectedNodeId)) {
        throw 'Expected native identity does not match inspected/enrolled peer'
    }
}
function Assert-RecoveryTargetBinding {
    param([bool]$NonInteractive,[string]$TaskName,[string]$TaskPath,[string]$ConfigPath,[string]$ExpectedNodeId,$Runtime,[string]$ActualNodeId)
    Assert-RecoveryNodeIdentity $Runtime.node_id $ActualNodeId
    if (-not $Runtime.node_id) { throw 'Enrollment must bind its inspected native identity' }
    if ($ExpectedNodeId) { Assert-RecoveryNodeIdentity $ExpectedNodeId $Runtime.node_id }
    if ($NonInteractive -and ($TaskName -cne $Runtime.task_name -or $TaskPath -cne $Runtime.task_path -or $ConfigPath -ne $Runtime.config_path)) {
        throw 'Explicit target must exactly match private enrollment task/config'
    }
}
