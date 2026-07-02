# One-click start (Windows PowerShell, requires Docker Desktop)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

# Docker BuildKit on Windows fails when the project path contains non-ASCII chars (e.g. Chinese).
if ($PSScriptRoot -match '[^\u0000-\u007F]') {
    Write-Host ""
    Write-Host "ERROR: Docker cannot build in a folder with Chinese/non-ASCII characters in the path."
    Write-Host "Current path: $PSScriptRoot"
    Write-Host ""
    Write-Host "Fix: clone or copy the project to an ASCII-only path, for example:"
    Write-Host "  E:\image_db"
    Write-Host ""
    Write-Host "Example:"
    Write-Host "  cd E:\"
    Write-Host "  git clone https://github.com/luoshirui-192/image.git image_db"
    Write-Host "  cd image_db"
    Write-Host "  copy .env.docker.example .env"
    Write-Host "  # edit .env: PUBLIC_URL=http://192.168.17.162"
    Write-Host "  .\start.ps1"
    Write-Host ""
    exit 1
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Host "Please install Docker Desktop: https://www.docker.com/products/docker-desktop/"
    exit 1
}

if (-not (Test-Path .env)) {
    Copy-Item .env.docker.example .env
    Write-Host "Created .env from template. Edit PUBLIC_URL and secrets, then run this script again."
}

python docker/set-env.py
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

docker compose up -d --build
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

$public = "http://localhost"
$match = Select-String -Path .env -Pattern '^PUBLIC_URL=' | Select-Object -First 1
if ($match) {
    $public = $match.Line.Split('=', 2)[1].Trim()
}

Write-Host ""
Write-Host "=========================================="
Write-Host " Started"
Write-Host " Open in browser: $public"
Write-Host " Default login: admin / admin123"
Write-Host " Stop: docker compose down"
Write-Host "=========================================="
