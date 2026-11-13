# Inputs are set by the installer, never interpolated into PowerShell code.
$ErrorActionPreference = 'Stop'
try {
    $manifest = Get-Content -LiteralPath $env:KX_PARTS_MANIFEST -Raw -Encoding UTF8 | ConvertFrom-Json
    $archiveHash = [System.Security.Cryptography.SHA256]::Create()
    $output = [System.IO.File]::Open($env:KX_PAYLOAD_OUTPUT, 'Create', 'Write', 'None')
    try {
        $writer = [System.Security.Cryptography.CryptoStream]::new($output, $archiveHash, [System.Security.Cryptography.CryptoStreamMode]::Write)
        try {
            foreach ($part in $manifest.parts) {
                if ($part.file -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]+$') { throw 'Invalid resource name' }
                $source = Join-Path $env:KX_PARTS_DIRECTORY $part.file
                if ((Get-Item -LiteralPath $source).Length -ne $part.bytes) { throw "Incomplete resource: $($part.file)" }
                $partHash = [System.Security.Cryptography.SHA256]::Create()
                $input = [System.IO.File]::OpenRead($source)
                try {
                    $reader = [System.Security.Cryptography.CryptoStream]::new($input, $partHash, [System.Security.Cryptography.CryptoStreamMode]::Read)
                    try {
                        $reader.CopyTo($writer)
                        if ([BitConverter]::ToString($partHash.Hash).Replace('-', '') -ne $part.sha256) { throw "Incomplete resource: $($part.file)" }
                    } finally { $reader.Dispose() }
                } finally { $input.Dispose(); $partHash.Dispose() }
            }
            $writer.FlushFinalBlock()
            if ([BitConverter]::ToString($archiveHash.Hash).Replace('-', '') -ne $manifest.sha256) { throw 'Resource checksum mismatch' }
        } finally { $writer.Dispose() }
    } finally { $output.Dispose(); $archiveHash.Dispose() }
    exit 0
} catch {
    Write-Output $_.Exception.Message
    Remove-Item -LiteralPath $env:KX_PAYLOAD_OUTPUT -Force -ErrorAction SilentlyContinue
    exit 2
}
