[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$LiteralPath,
      [Parameter(Mandatory=$true)][string]$OwnerSid,
      [switch]$Directory, [switch]$VerifyParent)
$ErrorActionPreference = 'Stop'
if ($OwnerSid -notmatch '^S-1-[0-9-]+$') { throw 'Invalid owner identity' }
$item = Get-Item -LiteralPath $LiteralPath -Force
if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'Reparse points forbidden' }
$allowed = @($OwnerSid, 'S-1-5-18', 'S-1-5-32-544') | Select-Object -Unique
if ($VerifyParent) {
    $observed = Get-Acl -LiteralPath $LiteralPath
    $dangerous = [Security.AccessControl.FileSystemRights]::Write -bor [Security.AccessControl.FileSystemRights]::Delete -bor [Security.AccessControl.FileSystemRights]::DeleteSubdirectoriesAndFiles -bor [Security.AccessControl.FileSystemRights]::ChangePermissions -bor [Security.AccessControl.FileSystemRights]::TakeOwnership
    foreach ($rule in $observed.Access) {
        $sid = $rule.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value
        if ($rule.AccessControlType -eq 'Allow' -and $sid -notin $allowed -and ($rule.FileSystemRights -band $dangerous)) { throw 'Untrusted principal can mutate recovery parent directory' }
    }
    return
}
if ($Directory) { $acl = New-Object Security.AccessControl.DirectorySecurity }
else { $acl = New-Object Security.AccessControl.FileSecurity }
$before = Get-Acl -LiteralPath $LiteralPath
if ($before.GetOwner([Security.Principal.SecurityIdentifier]).Value -ne $OwnerSid) {
    throw 'Selected private path must already belong to the verified owner'
}
$acl.SetAccessRuleProtection($true, $false)
foreach ($sid in $allowed) {
    $identity = New-Object Security.Principal.SecurityIdentifier($sid)
    if ($Directory) {
        $rule = New-Object Security.AccessControl.FileSystemAccessRule($identity, 'FullControl',
            'ContainerInherit,ObjectInherit', 'None', 'Allow')
    } else { $rule = New-Object Security.AccessControl.FileSystemAccessRule($identity, 'FullControl', 'Allow') }
    $acl.AddAccessRule($rule)
}
# Modify only the DACL. Rewriting even an unchanged owner requests WRITE_OWNER,
# which an ordinary owning account need not have. Ownership is verified above
# and again below; this helper never takes ownership or changes audit policy.
if ($Directory) { [IO.Directory]::SetAccessControl($LiteralPath,$acl) }
else { [IO.File]::SetAccessControl($LiteralPath,$acl) }
$observed = Get-Acl -LiteralPath $LiteralPath
if (-not $observed.AreAccessRulesProtected) { throw 'Private ACL inheritance was not disabled' }
foreach ($rule in $observed.Access) {
    $sid = $rule.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value
    if ($rule.IsInherited -or $sid -notin $allowed -or $rule.AccessControlType -ne 'Allow') {
        throw 'Private ACL verification failed'
    }
}
foreach ($sid in $allowed) {
    $matching = @($observed.Access | Where-Object { $_.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value -eq $sid -and $_.FileSystemRights -eq [Security.AccessControl.FileSystemRights]::FullControl })
    if ($matching.Count -ne 1) { throw 'Required private ACL grant missing' }
}
if ($observed.GetOwner([Security.Principal.SecurityIdentifier]).Value -ne $OwnerSid) { throw 'Private ACL owner verification failed' }
