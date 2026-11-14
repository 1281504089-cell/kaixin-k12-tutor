$ErrorActionPreference = 'Stop'
$originalTemp = $env:TEMP
$root = Join-Path $originalTemp ('学霸 诊断测试-'+[guid]::NewGuid())
$source = $PSScriptRoot
function Assert($condition,$message) { if (-not $condition) { throw $message } }
function Snapshot($directory) {
  return (@(Get-ChildItem -LiteralPath $directory -Recurse -File | Sort-Object FullName | ForEach-Object { $_.FullName+'='+(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash }) -join ';')
}
try {
  New-Item -ItemType Directory -Path $root | Out-Null
  $tools = Join-Path $root '中文 工具'
  New-Item -ItemType Directory -Path $tools | Out-Null
  $cmd = Join-Path $tools '双击检查Windows更新.cmd'
  Copy-Item -LiteralPath (Join-Path $source '双击检查Windows更新.cmd') -Destination $cmd
  New-Item -ItemType File -Path (Join-Path $root '.diagnostic-synthetic') | Out-Null
  $profile = Join-Path $root 'profile'
  $runtime = Join-Path $profile 'runtimes\fixture-native-x64'
  $install = Join-Path $root 'install'
  $keyDir = Join-Path $install 'resources\app\assets'
  New-Item -ItemType Directory -Path $runtime,$keyDir,(Join-Path $root 'temp\ns.fixture.tmp') -Force | Out-Null
  $manifest = @{formatVersion=1; protocolVersion=1; platform='win32'; arch='x64'; runtimeId='fixture-native-x64'; signature='synthetic-signature'; api_key='DO-NOT-EXPORT-THIS-KEY'} | ConvertTo-Json
  $manifest | Set-Content -LiteralPath (Join-Path $profile 'active.json') -Encoding UTF8
  $manifest | Set-Content -LiteralPath (Join-Path $runtime 'installed.json') -Encoding UTF8
  'DO-NOT-EXPORT-THIS-CHAT' | Set-Content -LiteralPath (Join-Path $profile 'private-chat.txt')
  '-----BEGIN PUBLIC KEY-----'+[Environment]::NewLine+'U1lOVEhFVElDLU9OTFk='+[Environment]::NewLine+'-----END PUBLIC KEY-----'+[Environment]::NewLine | Set-Content -LiteralPath (Join-Path $keyDir 'runtime-public.pem') -Encoding UTF8
  '{"passed":false,"error":"KNOWN_SYNTHETIC_FAILURE"}' | Set-Content -LiteralPath (Join-Path $root 'temp\ns.fixture.tmp\migration-check-payload.json') -Encoding UTF8
  $before = Snapshot $profile
  $env:KX_DIAGNOSTIC_TEST_ROOT = $root
  $env:TEMP = Join-Path $root 'temp'
  & cmd.exe /d /c $cmd
  Assert ($LASTEXITCODE -eq 0) 'CMD did not run successfully in Windows PowerShell 5.1'
  $file = @(Get-ChildItem -LiteralPath $root -Filter 'Windows-update-diagnostic-*.json')
  Assert ($file.Count -eq 1) 'Expected exactly one diagnostic report'
  $raw = Get-Content -LiteralPath $file[0].FullName -Raw -Encoding UTF8
  $report = $raw | ConvertFrom-Json
  Assert ($report.readOnly -eq $true) 'Missing read-only marker'
  Assert ($report.active.runtimeId -eq 'fixture-native-x64') 'Manifest not collected'
  Assert ($report.runtimeFiles.'fixture-native-x64'.installed.signature -eq 'synthetic-signature') 'Installed metadata missing'
  Assert ($report.oldPublicKeyPem -match 'BEGIN PUBLIC KEY') 'Public key not collected'
  Assert ($report.existingInstallerReports[0].error -eq 'KNOWN_SYNTHETIC_FAILURE') 'Open installer report not collected'
  Assert (-not $raw.Contains('DO-NOT-EXPORT-THIS-KEY')) 'Unexpected secret copied'
  Assert (-not $raw.Contains('DO-NOT-EXPORT-THIS-CHAT')) 'Unexpected chat copied'
  Assert ((Snapshot $profile) -eq $before) 'Synthetic profile was modified'
  foreach ($case in @('empty','missing-field','damaged-json')) {
    $caseRoot = Join-Path $root $case
    $caseProfile = Join-Path $caseRoot 'profile'
    New-Item -ItemType Directory -Path $caseProfile -Force | Out-Null
    New-Item -ItemType File -Path (Join-Path $caseRoot '.diagnostic-synthetic') | Out-Null
    if ($case -eq 'missing-field') { '{"api_key":"DO-NOT-EXPORT-THIS-KEY","baseRuntimeId":"../private-chat"}' | Set-Content -LiteralPath (Join-Path $caseProfile 'active.json') -Encoding UTF8 }
    if ($case -eq 'damaged-json') { '{"api_key":"DO-NOT-EXPORT-THIS-KEY"' | Set-Content -LiteralPath (Join-Path $caseProfile 'active.json') -Encoding UTF8 }
    $env:KX_DIAGNOSTIC_TEST_ROOT = $caseRoot
    $snapshot = Snapshot $caseProfile
    & cmd.exe /d /c $cmd
    Assert ($LASTEXITCODE -eq 0) ('Diagnostic failed for '+$case)
    $file = @(Get-ChildItem -LiteralPath $caseRoot -Filter 'Windows-update-diagnostic-*.json')
    Assert ($file.Count -eq 1) ('Missing report for '+$case)
    $raw = Get-Content -LiteralPath $file[0].FullName -Raw -Encoding UTF8
    $data = $raw | ConvertFrom-Json
    if ($case -eq 'empty') { Assert ($data.active.state -eq 'missing') 'Missing active not reported' }
    if ($case -eq 'missing-field') { Assert ($null -eq $data.active.runtimeId) 'Missing runtime ID fabricated' }
    if ($case -eq 'damaged-json') { Assert ($data.active.state -eq 'unreadable') 'Corrupt JSON not reported' }
    Assert (-not $raw.Contains('DO-NOT-EXPORT-THIS-KEY')) ('Secret exported for '+$case)
    Assert ((Snapshot $caseProfile) -eq $snapshot) ('Profile changed for '+$case)
  }
  $env:KX_DIAGNOSTIC_TEST_ROOT = $root
  $unsafe = Join-Path $profile 'unsafe-output.cmd'
  Copy-Item -LiteralPath $cmd -Destination $unsafe
  & cmd.exe /d /c $unsafe
  Assert ($LASTEXITCODE -ne 0) 'Output inside learning profile was permitted'
  Assert (@(Get-ChildItem -LiteralPath $profile -Filter 'Windows-update-diagnostic-*.json').Count -eq 0) 'Report written inside profile'
  $env:KX_DIAGNOSTIC_TEST_ROOT = Join-Path $env:LOCALAPPDATA '开心动力超级学霸'
  & cmd.exe /d /c $cmd
  Assert ($LASTEXITCODE -ne 0) 'Real profile accepted as synthetic root'
  Write-Host 'PASS: final CMD in Chinese/space path; normal/empty/missing-field/corrupt JSON; secret exclusion; profile preservation; unsafe output/test roots rejected'
} finally {
  $env:TEMP = $originalTemp
  Remove-Item Env:KX_DIAGNOSTIC_TEST_ROOT -ErrorAction SilentlyContinue
  if (Test-Path -LiteralPath $root) { Remove-Item -LiteralPath $root -Recurse -Force }
}
