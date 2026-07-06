# Machine A one-click start (Windows PowerShell)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$ComposeFile = "docker-compose.app.yml"

if ($PSScriptRoot -match '[^\u0000-\u007F]') {
    Write-Host "ERROR: Docker cannot build in a folder with non-ASCII characters in the path."
    Write-Host "Use an ASCII-only path, e.g. E:\image_db"
    exit 1
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Host "Please install Docker Desktop: https://www.docker.com/products/docker-desktop/"
    exit 1
}

if (-not (Test-Path .env)) {
    Copy-Item .env.app.example .env
    Write-Host "Created .env from .env.app.example"
    Write-Host "Edit MYSQL_* passwords, PUBLIC_URL, MACHINE_B_NFS_*, then run again."
    exit 0
}

if (-not (Test-Path upload)) {
    New-Item -ItemType Directory -Path upload | Out-Null
    Write-Host "Created upload/. Mount machine B NFS here in production."
}

python docker/set-env.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

docker compose -f $ComposeFile up -d --build
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$public = "http://localhost"
$match = Select-String -Path .env -Pattern '^PUBLIC_URL=' | Select-Object -First 1
if ($match) { $public = $match.Line.Split('=', 2)[1].Trim() }

Write-Host ""
Write-Host "=========================================="
Write-Host " Machine A started (MySQL + app layer)"
Write-Host " Browser: $public"
Write-Host " upload/ should be NFS from machine B in production"
Write-Host " Stop: docker compose -f $ComposeFile down"
Write-Host " Docs: README-MACHINE-A.md"
Write-Host "=========================================="
