$ErrorActionPreference = 'Stop'
$name = [string]::Concat([char[]](0x5f00,0x5fc3,0x52a8,0x529b,0x8d85,0x7ea7,0x5b66,0x9738))
$drives = @([IO.DriveInfo]::GetDrives() | Where-Object { $_.IsReady -and $_.DriveType -eq 'Fixed' -and $_.DriveFormat -eq 'NTFS' } | Sort-Object AvailableFreeSpace)
if ($drives.Count -lt 2) { throw 'Two fixed Windows partitions are needed for this verification' }
$alternateDrive = @($drives | Where-Object AvailableFreeSpace -GE 20GB)[-1]
$sourceDrive = @($drives | Where-Object Name -NE $alternateDrive.Name)[0]
$env:LOCALAPPDATA = Join-Path $sourceDrive.RootDirectory.FullName ('KaixinRelocationQA-' + [Guid]::NewGuid().ToString('N'))
$env:OPEN_DEEPTUTOR_TEST_HOME = Join-Path $env:LOCALAPPDATA 'unused-electron-test-home'
$appDir = Join-Path $env:LOCALAPPDATA 'App'
$src = New-Item -Type Directory -Force (Join-Path $appDir 'resources/app/src')
Copy-Item 'startup-qa/original-bundles.mjs' (Join-Path $src.FullName 'bundles.mjs')
Copy-Item 'startup-qa/original-main.mjs' (Join-Path $src.FullName 'main.mjs')
Copy-Item (Join-Path $env:SystemRoot 'System32/where.exe') (Join-Path $appDir ($name+'.exe'))
[IO.File]::WriteAllText((Join-Path $appDir 'resources/app/package.json'), '{"kaixinLauncherBuild":"20261121-updater-8"}')
$profile = Join-Path $env:LOCALAPPDATA $name
$workspace = New-Item -Type Directory -Force (Join-Path $profile 'workspace')
$history = Join-Path $workspace.FullName 'learning.txt'
[IO.File]::WriteAllText($history, 'untouched learning record')
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File "startup-qa/repair/repair.ps1" -AppDirectory $appDir -UseAnotherDrive
if ($LASTEXITCODE -eq 0 -or [IO.File]::ReadAllText($history) -ne 'untouched learning record') { throw 'Existing data safety check failed' }
Remove-Item -LiteralPath $workspace.FullName -Recurse
$target = $null
try {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File "startup-qa/repair/repair.ps1" -AppDirectory $appDir -UseAnotherDrive
    if ($LASTEXITCODE -ne 0) { throw 'Fresh installation relocation failed' }
    $link = Get-Item -LiteralPath $profile -Force
    $target = [string]$link.Target[0]
    if ($link.LinkType -ne 'Junction' -or [IO.Path]::GetPathRoot($target) -eq $sourceDrive.Name) { throw 'Storage was not redirected' }
    $acl = Get-Acl -LiteralPath $target
    if (-not $acl.AreAccessRulesProtected -or $acl.Access.Count -ne 2) { throw 'Data folder ACL is not private' }
    [IO.File]::WriteAllText((Join-Path $profile 'checked.txt'), 'test data')
    if ([IO.File]::ReadAllText((Join-Path $target 'checked.txt')) -ne 'test data') { throw 'Data does not land on the other drive' }
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File "startup-qa/repair/repair.ps1" -AppDirectory $appDir -UseAnotherDrive
    if ($LASTEXITCODE -ne 0 -or (Get-Item -LiteralPath $profile).Target[0] -ne $target) { throw 'Second launch did not preserve data location' }
    Write-Host ('Fresh install data verified across ' + $sourceDrive.Name + ' -> ' + $alternateDrive.Name)
} finally {
    if ((Get-Item -LiteralPath $profile -Force).LinkType -eq 'Junction') { [IO.Directory]::Delete($profile) }
    if ($target -and (Test-Path -LiteralPath $target)) { Remove-Item -LiteralPath $target -Recurse }
    Remove-Item -LiteralPath $env:LOCALAPPDATA -Recurse
}
