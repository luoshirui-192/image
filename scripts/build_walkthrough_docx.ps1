# Merge docs/code-walkthrough/*.md into a single Word document.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$DocDir = Join-Path $Root "docs\code-walkthrough"
$Out = Join-Path $DocDir "code-walkthrough.docx"

$Files = Get-ChildItem -LiteralPath $DocDir -Filter "*.md" |
    Sort-Object {
        if ($_.Name -eq "README.md") { "00-README.md" } else { $_.Name }
    } |
    ForEach-Object { $_.FullName }

if ($Files.Count -lt 2) {
    throw "No walkthrough markdown files found in $DocDir"
}

& pandoc @Files `
    -o $Out `
    --from markdown `
    --to docx `
    --toc `
    --toc-depth=2 `
    --metadata title="图像路径式数据库管理系统 — 代码导读" `
    --metadata lang=zh-CN

Write-Host "Wrote $Out"
