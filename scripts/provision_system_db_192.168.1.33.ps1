# 一键：在 192.168.1.33 新建系统库 image_db，并把 ara_fp_analyst 里的系统表迁出
# 用法:
#   .\scripts\provision_system_db_192.168.1.33.ps1
#   .\scripts\provision_system_db_192.168.1.33.ps1 -Password '你的root密码'
#   .\scripts\provision_system_db_192.168.1.33.ps1 -DryRun
#   $env:MYSQL_ROOT_PASSWORD='xxx'; .\scripts\provision_system_db_192.168.1.33.ps1 -Yes

param(
    [string]$HostAddress = "192.168.1.33",
    [int]$Port = 3306,
    [string]$User = "root",
    [string]$Password = $env:MYSQL_ROOT_PASSWORD,
    [string]$WrongDb = "ara_fp_analyst",
    [string]$SystemDb = "image_db",
    [string]$AppUser = $(if ($env:MYSQL_USER) { $env:MYSQL_USER } else { "image_db" }),
    [string]$AppPassword = $env:MYSQL_PASSWORD,
    [switch]$InitOnly,
    [switch]$DryRun,
    [switch]$Yes
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if (-not $Password) {
    $secure = Read-Host "请输入 MySQL root@$HostAddress 密码" -AsSecureString
    $BSTR = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    $Password = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto($BSTR)
}

Write-Host ""
Write-Host "将在 $HostAddress 上:" -ForegroundColor Cyan
Write-Host "  1) CREATE DATABASE $SystemDb"
Write-Host "  2) 从 $WrongDb RENAME 系统表到 $SystemDb（业务表不动）"
Write-Host "  3) 补齐缺失表结构 / 授权 $AppUser"
Write-Host ""

$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) { $py = Get-Command py -ErrorAction SilentlyContinue }
if (-not $py) { throw "未找到 python，请先安装并确保 mysqlclient 可用" }

$args = @(
    "scripts/provision_system_db.py",
    "--host", $HostAddress,
    "--port", "$Port",
    "--user", $User,
    "--password", $Password,
    "--wrong-db", $WrongDb,
    "--system-db", $SystemDb,
    "--app-user", $AppUser
)
if ($AppPassword) { $args += @("--app-password", $AppPassword) }
if ($InitOnly) { $args += "--init-only" }
if ($DryRun) { $args += "--dry-run" }
if ($Yes) { $args += "--yes" }

& $py.Source @args
exit $LASTEXITCODE
