# Machine B: start MySQL data container only
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$ComposeFile = "docker-compose.data.yml"

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Host "Please install Docker Desktop"
    exit 1
}

if (-not (Test-Path .env)) {
    Copy-Item .env.data.example .env
    Write-Host "Created .env from .env.data.example — edit and run again."
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

docker compose -f $ComposeFile up -d --build
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host ""
Write-Host "Machine B MySQL started. See README-MACHINE-B.md for grant-machine-a and NFS steps."
