param([string]$AppDirectory)
$ErrorActionPreference = 'Stop'
try {
    $name = '开心动力超级学霸'
    $binary = $name + '.exe'
    $running = @(Get-Process -Name $name -ErrorAction SilentlyContinue)
    if ($AppDirectory) { $candidates = @($AppDirectory) }
    else {
        $candidates = @($running | Where-Object { $_.MainWindowHandle -and $_.Path } | Sort-Object StartTime -Descending | ForEach-Object { Split-Path -Parent $_.Path })
        $registered = Get-ItemProperty -LiteralPath (Join-Path 'HKCU:\Software' $name) -Name InstallDir -ErrorAction SilentlyContinue
        $candidates += $registered.InstallDir
        $candidates += (Join-Path (Join-Path $env:LOCALAPPDATA 'Programs') $name)
        $candidates += @([IO.DriveInfo]::GetDrives() | Where-Object { $_.IsReady -and $_.DriveType -in @('Fixed','Removable') } | ForEach-Object { Join-Path $_.RootDirectory.FullName $name })
        $candidates += (Join-Path ([Environment]::GetFolderPath('DesktopDirectory')) $name)
    }
    $edits = @(
        @{Name='bundles.mjs'; Old='aaff9df354910a87efb44705ab7398466a4498720bdee756e4fb134f7cf0dea5'; Fixed='2e7d7991ab2f590d79fda28fee3a5c9587edc20024834fa5a3ace4419b509015'},
        @{Name='main.mjs'; Old='73482a9a12c3ede23844ca898b8e514834700ed45c6e7568c68976e42fe4d1e2'; Fixed='56083aea41456c8982b168c663e48b432711bfa7d3ca1eb2826f33cd1ed6a3ec'}
    )
    function Get-Hash([string]$file) { (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash }
    foreach ($row in $edits) {
        if ((Get-Hash (Join-Path $PSScriptRoot $row.Name)) -ne $row.Fixed) { throw '修复文件校验未通过。' }
    }
    $app = $null
    foreach ($dir in @($candidates | Where-Object { $_ } | Select-Object -Unique)) {
        if (-not (Test-Path -LiteralPath (Join-Path $dir $binary) -PathType Leaf)) { continue }
        $res = Join-Path $dir 'resources\app'
        $meta = Join-Path $res 'package.json'
        if (-not (Test-Path -LiteralPath $meta -PathType Leaf)) { continue }
        $package = Get-Content -LiteralPath $meta -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($package.kaixinLauncherBuild -ne '20261121-updater-8') { continue }
        $misses = @($edits | Where-Object {
            $target = Join-Path (Join-Path $res 'src') $_.Name
            -not (Test-Path -LiteralPath $target -PathType Leaf) -or (Get-Hash $target) -notin @($_.Old,$_.Fixed)
        })
        if (-not $misses.Count) { $app = $dir; break }
    }
    if (-not $app) { throw '没有找到校验一致的 k12-18 程序。请打开正在使用的那份程序所在文件夹后重试。' }
    foreach ($child in $running) { if ($child.MainWindowHandle) { [void]$child.CloseMainWindow() } }
    $deadline = [DateTime]::UtcNow.AddSeconds(12)
    do {
        $running = @(Get-Process -Name $name -ErrorAction SilentlyContinue)
        if ($running.Count) { Start-Sleep -Milliseconds 250 }
    } while ($running.Count -and [DateTime]::UtcNow -lt $deadline)
    if ($running.Count) { throw '程序仍在运行。请重启 Windows 后再运行修复，只打开一份软件。' }
    $src = Join-Path $app 'resources\app\src'
    foreach ($row in $edits) {
        $file = Join-Path $src $row.Name
        if ((Get-Hash $file) -eq $row.Fixed) { continue }
        $backup = $file + '.before-k12-18-recovery'
        if (Test-Path -LiteralPath $backup) { throw '该启动文件已有备份，暂未覆盖。' }
        $temp = $file + '.' + [Guid]::NewGuid().ToString('N') + '.tmp'
        try {
            Copy-Item -LiteralPath (Join-Path $PSScriptRoot $row.Name) -Destination $temp
            if ((Get-Hash $temp) -ne $row.Fixed -or (Get-Hash $file) -ne $row.Old) { throw '写入前校验未通过。' }
            [IO.File]::Replace($temp, $file, $backup, $true)
            if ((Get-Hash $file) -ne $row.Fixed) { throw '写入后校验未通过。' }
        } finally {
            if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp }
        }
    }
    Write-Host ('已修复启动程序，正在打开 ' + $app) -ForegroundColor Green
    Start-Process -FilePath (Join-Path $app $binary) -WorkingDirectory $app
    exit 0
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}
