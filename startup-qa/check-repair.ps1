$ErrorActionPreference = 'Stop'
$brand = [string]::Concat([char[]](0x5f00,0x5fc3,0x52a8,0x529b,0x8d85,0x7ea7,0x5b66,0x9738))
$env:LOCALAPPDATA = Join-Path $env:RUNNER_TEMP 'isolated desktop repair test'
$env:OPEN_DEEPTUTOR_TEST_HOME = Join-Path $env:LOCALAPPDATA 'synthetic learning home'
$installed = Join-Path (Join-Path $env:LOCALAPPDATA 'Programs') $brand
$app = Join-Path $installed 'resources/app'
$src = New-Item -Type Directory -Force (Join-Path $app 'src')
$target = Join-Path $src.FullName 'bundles.mjs'
$sentinel = New-Item -Type Directory -Force $env:OPEN_DEEPTUTOR_TEST_HOME
$sentinelPath = Join-Path $sentinel.FullName 'learning.txt'
[IO.File]::WriteAllText($sentinelPath, 'synthetic learning data')
Copy-Item 'startup-qa/original-bundles.mjs' $target
Copy-Item 'startup-qa/original-main.mjs' (Join-Path $src.FullName 'main.mjs')
Copy-Item (Join-Path $env:SystemRoot 'System32/where.exe') (Join-Path $installed ($brand+'.exe'))
[IO.File]::WriteAllText((Join-Path $app 'package.json'), '{"kaixinLauncherBuild":"20261121-updater-8"}')
$before = (Get-FileHash -LiteralPath $target).Hash
$after = (Get-FileHash -LiteralPath 'startup-qa/repair/bundles.mjs').Hash
for ($i = 0; $i -lt 2; $i++) {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File "startup-qa/repair/repair.ps1" -AppDirectory $installed
    if ($LASTEXITCODE -ne 0) { throw 'The Windows repair returned a failure' }
    if ((Get-FileHash -LiteralPath $target).Hash -ne $after) { throw 'Installed bytes mismatch' }
    if ((Get-FileHash -LiteralPath (Join-Path $src.FullName 'main.mjs')).Hash -ne (Get-FileHash 'startup-qa/repair/main.mjs').Hash) { throw 'Recovery code mismatch' }
    if ((Get-FileHash -LiteralPath ($target+'.before-k12-18-recovery')).Hash -ne $before) { throw 'Backup bytes mismatch' }
}
if ([IO.File]::ReadAllText($sentinelPath) -ne 'synthetic learning data') { throw 'Learning data changed' }
