# Reassemble the original Docker archive and verify all bytes before publishing it.
$ErrorActionPreference = 'Stop'
$Root = $PSScriptRoot
$Manifest = Get-Content -LiteralPath (Join-Path $Root 'manifest.json') -Raw | ConvertFrom-Json
$Output = Join-Path $Root $Manifest.archive
$Partial = "$Output.partial"

if (Test-Path -LiteralPath $Output) {
    $ExistingHash = (Get-FileHash -LiteralPath $Output -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($ExistingHash -ne $Manifest.sha256) {
        throw "An existing archive has the wrong checksum. Move or remove it before retrying: $Output"
    }
    Write-Host "Archive already verified: $Output"
    return
}

$Destination = [System.IO.File]::Open($Partial, [System.IO.FileMode]::CreateNew, [System.IO.FileAccess]::Write)
try {
    try {
        foreach ($Part in $Manifest.parts) {
            $Path = Join-Path $Root $Part.file
            if ((Get-Item -LiteralPath $Path).Length -ne $Part.bytes) {
                throw "Wrong size: $($Part.file)"
            }
            $Hash = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
            if ($Hash -ne $Part.sha256) {
                throw "Checksum mismatch: $($Part.file)"
            }
            Write-Host "Joining $($Part.file)"
            $InputStream = [System.IO.File]::OpenRead($Path)
            try { $InputStream.CopyTo($Destination) }
            finally { $InputStream.Dispose() }
        }
    }
    finally { $Destination.Dispose() }

    if ((Get-Item -LiteralPath $Partial).Length -ne $Manifest.bytes) {
        throw 'The assembled archive has the wrong size.'
    }
    $Hash = (Get-FileHash -LiteralPath $Partial -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($Hash -ne $Manifest.sha256) {
        throw 'The assembled archive failed SHA-256 verification.'
    }
    Move-Item -LiteralPath $Partial -Destination $Output
}
catch {
    Remove-Item -LiteralPath $Partial -ErrorAction SilentlyContinue
    throw
}
Write-Host "Verified archive: $Output"
Write-Host "Load it with: podman load -i `"$Output`""
