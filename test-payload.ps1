$ErrorActionPreference='Stop'
$root=Join-Path $env:TEMP ('KX payload test '+[guid]::NewGuid())
New-Item -ItemType Directory $root | Out-Null
try {
    $first=Join-Path $root 'Runtime.001';$second=Join-Path $root 'Runtime.002';$joined=Join-Path $root 'expected'
    [IO.File]::WriteAllBytes($first,[byte[]](1,2,3));[IO.File]::WriteAllBytes($second,[byte[]](4,5));[IO.File]::WriteAllBytes($joined,[byte[]](1,2,3,4,5))
    $manifest=@{sha256=(Get-FileHash $joined -Algorithm SHA256).Hash;parts=@(@{file='Runtime.001';bytes=3;sha256=(Get-FileHash $first -Algorithm SHA256).Hash},@{file='Runtime.002';bytes=2;sha256=(Get-FileHash $second -Algorithm SHA256).Hash})}
    $env:KX_PARTS_MANIFEST=Join-Path $root 'parts.json';$manifest | ConvertTo-Json -Depth 5 | Set-Content $env:KX_PARTS_MANIFEST -Encoding UTF8
    $env:KX_PARTS_DIRECTORY=$root;$env:KX_PAYLOAD_OUTPUT=Join-Path $root 'output'
    $script=Join-Path $PSScriptRoot 'student-source/apps/desktop/platforms/windows-x64/join-payload.ps1'
    & powershell -NoProfile -File $script
    if($LASTEXITCODE -ne 0 -or (Get-FileHash $env:KX_PAYLOAD_OUTPUT).Hash -ne $manifest.sha256){throw 'Valid parts did not reconstruct'}
    [IO.File]::WriteAllBytes($second,[byte[]](4,6))
    & powershell -NoProfile -File $script
    if($LASTEXITCODE -eq 0 -or (Test-Path $env:KX_PAYLOAD_OUTPUT)){throw 'Corrupted part was accepted'}
    Write-Host 'PASS: valid parts join and corrupt parts remove only their incomplete output.'
}finally{Remove-Item $root -Recurse -Force}

exit 0
