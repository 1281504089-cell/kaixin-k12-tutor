# Inputs are set by the installer, never interpolated into PowerShell code.
$ErrorActionPreference = 'Stop'
try {
    $manifest = Get-Content -LiteralPath $env:KX_PARTS_MANIFEST -Raw -Encoding UTF8 | ConvertFrom-Json
    $output = [System.IO.File]::Open($env:KX_PAYLOAD_OUTPUT, 'Create', 'Write', 'None')
    try {
        foreach ($part in $manifest.parts) {
            if ($part.file -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]+$') { throw 'Invalid resource name' }
            $source = Join-Path $env:KX_PARTS_DIRECTORY $part.file
            $info = Get-Item -LiteralPath $source
            if ($info.Length -ne $part.bytes -or (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash -ne $part.sha256) { throw "Incomplete resource: $($part.file)" }
            $input = [System.IO.File]::OpenRead($source)
            try { $input.CopyTo($output) } finally { $input.Dispose() }
        }
    } finally { $output.Dispose() }
    if ((Get-FileHash -LiteralPath $env:KX_PAYLOAD_OUTPUT -Algorithm SHA256).Hash -ne $manifest.sha256) { throw 'Resource checksum mismatch' }
    exit 0
} catch {
    Write-Output $_.Exception.Message
    Remove-Item -LiteralPath $env:KX_PAYLOAD_OUTPUT -Force -ErrorAction SilentlyContinue
    exit 2
}
