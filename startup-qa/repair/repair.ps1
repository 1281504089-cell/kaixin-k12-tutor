$ErrorActionPreference = 'Stop'
try {
    $name = '开心动力超级学霸'
    $reg = Get-ItemProperty -LiteralPath (Join-Path 'HKCU:\Software' $name) -Name InstallDir -ErrorAction SilentlyContinue
    $default = Join-Path (Join-Path $env:LOCALAPPDATA 'Programs') $name
    $app = @($reg.InstallDir, $default) | Where-Object { $_ -and (Test-Path -LiteralPath (Join-Path $_ ($name + '.exe')) -PathType Leaf) } | Select-Object -First 1
    if (-not $app) { throw '找不到已安装的程序。请先解压完整安装 ZIP，运行 Setup.exe。' }
    $exe = Join-Path $app ($name + '.exe')
    $res = Join-Path $app 'resources\app'
    $package = Get-Content -LiteralPath (Join-Path $res 'package.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($package.kaixinLauncherBuild -ne '20261121-updater-8') { throw '当前安装不是 k12-18 本批启动器，暂未改动。' }
    $file = Join-Path $res 'src\bundles.mjs'
    $payload = Join-Path $PSScriptRoot 'bundles.mjs'
    $old = 'aaff9df354910a87efb44705ab7398466a4498720bdee756e4fb134f7cf0dea5'
    $fix = '2e7d7991ab2f590d79fda28fee3a5c9587edc20024834fa5a3ace4419b509015'
    function Get-Hash([string]$path) { (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash }
    $current = Get-Hash $file
    if ($current -ne $old -and $current -ne $fix) { throw '当前启动文件与发行版校验值不一致，暂未改动。' }
    if ((Get-Hash $payload) -ne $fix) { throw 'U 盘修复文件校验失败。' }
    $running = @(Get-Process -Name $name -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $exe })
    foreach ($child in $running) { if ($child.MainWindowHandle) { [void]$child.CloseMainWindow() } }
    $deadline = [DateTime]::UtcNow.AddSeconds(12)
    do {
        $running = @(Get-Process -Name $name -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $exe })
        if ($running.Count) { Start-Sleep -Milliseconds 250 }
    } while ($running.Count -and [DateTime]::UtcNow -lt $deadline)
    if ($running.Count) { throw '请关闭超级学霸窗口，再双击一次修复。' }
    if ($current -ne $fix) {
        $backup = $file + '.before-k12-18-repair'
        if (Test-Path -LiteralPath $backup) { throw '启动文件已有备份，暂未覆盖。' }
        $temp = $file + '.' + [Guid]::NewGuid().ToString('N') + '.tmp'
        try {
            Copy-Item -LiteralPath $payload -Destination $temp
            if ((Get-Hash $temp) -ne $fix -or (Get-Hash $file) -ne $old) { throw '写入前校验失败。' }
            [IO.File]::Replace($temp, $file, $backup, $true)
            if ((Get-Hash $file) -ne $fix) { throw '写入后校验失败。' }
        } finally {
            if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp }
        }
    }
    Start-Process -FilePath $exe -WorkingDirectory $app
    Write-Host '启动修复已写入，程序会重新打开。第一次打开可能需要几分钟解包。' -ForegroundColor Green
    exit 0
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}
