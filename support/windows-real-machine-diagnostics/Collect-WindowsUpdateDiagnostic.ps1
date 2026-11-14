$ErrorActionPreference = 'Stop'
$app = '开心动力超级学霸'
$output = $env:KX_DIAGNOSTIC_OUTPUT
if (-not $output) { $output = $PSScriptRoot }
$profile = Join-Path $env:LOCALAPPDATA $app
$install = Join-Path $env:LOCALAPPDATA ('Programs\' + $app)
try { $registered = (Get-ItemProperty -LiteralPath ('HKCU:\Software\' + $app) -Name InstallDir -ErrorAction Stop).InstallDir; if ($registered) { $install = $registered } } catch {}
function Inside($parent,$child) {
  $prefix = [IO.Path]::GetFullPath($parent).TrimEnd('\')+'\'
  return ([IO.Path]::GetFullPath($child).TrimEnd('\')+'\').StartsWith($prefix,[StringComparison]::OrdinalIgnoreCase)
}
$protected = @($profile,$install,(Join-Path $env:APPDATA $app))
if ($env:KX_DIAGNOSTIC_TEST_ROOT) {
  $test = [IO.Path]::GetFullPath($env:KX_DIAGNOSTIC_TEST_ROOT)
  foreach ($real in $protected) { if ((Inside $real $test) -or (Inside $test $real)) { throw 'Synthetic test root overlaps the real app or learning directory' } }
  if (-not (Test-Path -LiteralPath (Join-Path $test '.diagnostic-synthetic'))) { throw 'Synthetic test marker required' }
  foreach ($folder in @('profile','install')) { if (Inside (Join-Path $test $folder) $output) { throw 'Diagnostic output overlaps the synthetic app or profile' } }
  $profile = Join-Path $test 'profile'; $install = Join-Path $test 'install'; $output = $test
}
foreach ($directory in @($protected)+@($profile,$install)) { if (Inside $directory $output) { throw 'Please move this diagnostic tool outside the app and learning folders' } }
$parent = [IO.Path]::GetFullPath($output)
while ($parent) {
  if ((Get-Item -LiteralPath $parent -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Diagnostic output must be a normal folder, not a junction or symlink' }
  $parent = [IO.Path]::GetDirectoryName($parent)
}
$report = [ordered]@{formatVersion=1; readOnly=$true; windows=[Environment]::OSVersion.VersionString; powershell=$PSVersionTable.PSVersion.ToString(); install=$install; profile=$profile}
function Read-Manifest($file) {
  if (-not (Test-Path -LiteralPath $file -PathType Leaf)) { return @{state='missing'} }
  if ((Get-Item -LiteralPath $file).Length -gt 65536) { return @{state='too-large'} }
  try {
    $data = Get-Content -LiteralPath $file -Raw -Encoding UTF8 | ConvertFrom-Json
    $result = [ordered]@{state='read'}
    foreach ($field in @('formatVersion','protocolVersion','platform','arch','runtimeId','baseRuntimeId','coreVersion','commit','builtAt','archive','sha256','signature')) {
      if ($null -ne $data.$field) { $result[$field] = $data.$field }
    }
    return $result
  } catch { return @{state='unreadable'; errorType=$_.Exception.GetType().Name} }
}
$report.active = Read-Manifest (Join-Path $profile 'active.json')
$report.runtimeFiles = [ordered]@{}
foreach ($id in @($report.active.runtimeId, $report.active.baseRuntimeId) | Select-Object -Unique) {
  if ($id -and $id -cmatch '^[a-zA-Z0-9][a-zA-Z0-9.+_-]{0,100}$') {
    $runtime = Join-Path (Join-Path $profile 'runtimes') $id
    $files = [ordered]@{}
    foreach ($relative in @('python\python.exe','node\node.exe','core\deeptutor_cli\main.py','web\server.js')) { $files[$relative] = Test-Path -LiteralPath (Join-Path $runtime $relative) -PathType Leaf }
    $report.runtimeFiles[$id] = @{installed=(Read-Manifest (Join-Path $runtime 'installed.json')); files=$files}
  }
}
$keyFile = Join-Path $install 'resources\app\assets\runtime-public.pem'
if ((Test-Path -LiteralPath $keyFile -PathType Leaf) -and (Get-Item -LiteralPath $keyFile).Length -lt 4096) {
  $key = [IO.File]::ReadAllText($keyFile)
  if ($key -match '(?s)^-----BEGIN PUBLIC KEY-----\s*[a-zA-Z0-9+/=\s]+-----END PUBLIC KEY-----\s*$') { $report.oldPublicKeyPem=$key; $report.oldPublicKeySha256=(Get-FileHash -LiteralPath $keyFile -Algorithm SHA256).Hash.ToLowerInvariant() }
}
try { $upgrade = Get-Content -LiteralPath (Join-Path $profile 'upgrade.json') -Raw -Encoding UTF8 | ConvertFrom-Json; $report.upgradePhase=$upgrade.phase } catch { $report.upgradePhase='missing-or-unreadable' }
$report.pathLinks = @()
foreach ($root in @($profile,$install)) {
  $item = $root
  while ($item) {
    if (Test-Path -LiteralPath $item) { if ((Get-Item -LiteralPath $item -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { $report.pathLinks += $item } }
    $item = [IO.Path]::GetDirectoryName($item)
  }
}
try {
  $processes = @(Get-CimInstance Win32_Process -OperationTimeoutSec 20 -ErrorAction Stop)
  $report.processInspection = 'available'
  $report.runningAppProcesses = @($processes | Where-Object { $_.Name -eq ($app+'.exe') -or ($_.ExecutablePath -and ($_.ExecutablePath.StartsWith($install+'\',[StringComparison]::OrdinalIgnoreCase) -or $_.ExecutablePath.StartsWith((Join-Path $profile 'runtimes')+'\',[StringComparison]::OrdinalIgnoreCase) -or $_.ExecutablePath.StartsWith((Join-Path $profile 'cache')+'\',[StringComparison]::OrdinalIgnoreCase))) } | Select-Object ProcessId,Name,ExecutablePath)
} catch { $report.processInspection='unavailable'; $report.processInspectionErrorType=$_.Exception.GetType().Name }
$logs = @()
foreach ($directory in @(Get-ChildItem -LiteralPath $env:TEMP -Directory -Filter 'ns*.tmp' -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 20)) {
  foreach ($name in @('migration-check-payload.json','migration-check-staged.json')) {
    $file = Join-Path $directory.FullName $name
    if ((Test-Path -LiteralPath $file -PathType Leaf) -and (Get-Item -LiteralPath $file).Length -lt 65536) {
      try { $data = Get-Content -LiteralPath $file -Raw -Encoding UTF8 | ConvertFrom-Json; $logs += @{file=$file; passed=$data.passed; error=([string]$data.error).Substring(0,[Math]::Min(4000,([string]$data.error).Length))} } catch {}
    }
  }
}
$report.existingInstallerReports = $logs
$reportFile = Join-Path $output ('Windows-update-diagnostic-'+(Get-Date -Format 'yyyyMMdd-HHmmss-fff')+'.json')
$report | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $reportFile -Encoding UTF8
Write-Host ('诊断已保存：'+$reportFile)
Write-Host '请把这个 JSON 文件发给维护人员。未修改程序、聊天、设置或密钥。'
