# Machine B: configure upload directory + NFS export (no MySQL / no app)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path .env)) {
    Copy-Item .env.storage.example .env
    Write-Host "Created .env from .env.storage.example — edit DATA_UPLOAD_ROOT, MACHINE_A_HOSTS, then run again."
    exit 0
}

Get-Content .env | ForEach-Object {
    if ($_ -match '^\s*#' -or $_ -match '^\s*$') { return }
    $p = $_.Split('=', 2)
    if ($p.Count -eq 2) { Set-Item -Path "env:$($p[0].Trim())" -Value $p[1].Trim() }
}

$uploadRoot = if ($env:DATA_UPLOAD_ROOT) { $env:DATA_UPLOAD_ROOT } else { "/data/image_db/upload" }
if (-not (Test-Path $uploadRoot)) {
    New-Item -ItemType Directory -Path $uploadRoot -Force | Out-Null
}

Write-Host ""
Write-Host "Machine B storage: configure NFS on Linux with scripts/setup-nfs-export.sh"
Write-Host "See README-MACHINE-B.md (NFS server requires Linux; Windows B needs manual SMB/NFS setup)."
