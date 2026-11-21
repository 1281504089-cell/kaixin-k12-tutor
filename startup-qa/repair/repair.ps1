param([string]$AppDirectory, [switch]$UseAnotherDrive)
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
        @{Name='main.mjs'; Old='73482a9a12c3ede23844ca898b8e514834700ed45c6e7568c68976e42fe4d1e2'; Fixed='8a287764c9b29e22843fe64897d034724a85f464dc09b2bc3fe8cc34b41ee49b'}
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
    if ($UseAnotherDrive) {
        $profile = Join-Path $env:LOCALAPPDATA $name
        $item = Get-Item -LiteralPath $profile -Force -ErrorAction SilentlyContinue
        if ($item -and ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            if ($item.LinkType -ne 'Junction') { throw '检测到自定义数据目录。请使用普通启动修复。' }
            Write-Host ('已配置其他磁盘的数据目录：' + $item.Target)
        } else {
            foreach ($entry in @('workspace','workspace-location.json','active.json','upgrade.json','backups')) {
                if (Test-Path -LiteralPath (Join-Path $profile $entry)) {
                    throw '该电脑已有学习目录或升级记录。请使用普通启动修复，文件已保留。'
                }
            }
            $systemVolume = [IO.Path]::GetPathRoot($profile)
            $required = 20GB
            $drives = @([IO.DriveInfo]::GetDrives() | Where-Object {
                $_.IsReady -and $_.DriveType -eq 'Fixed' -and $_.DriveFormat -eq 'NTFS' -and
                $_.RootDirectory.FullName -ne $systemVolume -and $_.AvailableFreeSpace -ge $required
            } | Sort-Object AvailableFreeSpace -Descending)
            if (-not $drives.Count) { throw '没有找到其他可用的 NTFS 硬盘分区（需至少 20 GB 可用）。请在系统盘腾出足够空间后点重试。' }
            $identity = [Security.Principal.WindowsIdentity]::GetCurrent().User
            $acl = New-Object Security.AccessControl.DirectorySecurity
            $acl.SetAccessRuleProtection($true, $false)
            foreach ($sid in @($identity, [Security.Principal.SecurityIdentifier]::new('S-1-5-18'))) {
                $rule = [Security.AccessControl.FileSystemAccessRule]::new($sid, 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow')
                $acl.AddAccessRule($rule)
            }
            $alternate = $null
            foreach ($drive in $drives) {
                $target = Join-Path $drive.RootDirectory.FullName ('Kaixin-' + [Guid]::NewGuid().ToString('N').Substring(0,12))
                try {
                    [void][IO.Directory]::CreateDirectory($target, $acl)
                    $alternate = $target
                    break
                } catch { Write-Host ('无法在 ' + $drive.Name + ' 创建目录：' + $_.Exception.Message) }
            }
            if (-not $alternate) { throw '其他硬盘分区无法写入。请检查可用空间和写入权限。' }
            $original = $profile + '.before-fresh-storage-' + [Guid]::NewGuid().ToString('N').Substring(0,8)
            $moved = $false
            $junctionCreated = $false
            try {
                if ($item) {
                    [IO.Directory]::Move($profile, $original)
                    $moved = $true
                }
                [void](New-Item -Path $profile -ItemType Junction -Target $alternate)
                $junctionCreated = $true
                $link = Get-Item -LiteralPath $profile -Force
                if ($link.LinkType -ne 'Junction' -or $link.Target -notcontains $alternate) { throw '数据目录核对失败。' }
            } catch {
                if ($junctionCreated) { [IO.Directory]::Delete($profile) }
                if ($moved -and -not (Test-Path -LiteralPath $profile)) { [IO.Directory]::Move($original, $profile) }
                [IO.Directory]::Delete($alternate)
                throw
            }
            Write-Host ('学习数据和运行资源将写入 ' + $alternate) -ForegroundColor Green
        }
    }
    Write-Host ('已修复启动程序，正在打开 ' + $app) -ForegroundColor Green
    Start-Process -FilePath (Join-Path $app $binary) -WorkingDirectory $app
    exit 0
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}
