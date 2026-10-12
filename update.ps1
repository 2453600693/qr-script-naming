# QR脚本命名工具 · 更新到最新版
# 用法（二选一）：
#   1) 在 PowerShell 里：  & "<本文件路径>"
#   2) 如果提示脚本被禁止运行： powershell -ExecutionPolicy Bypass -File "<本文件路径>"

$dir = $PSScriptRoot
if (-not $dir) { $dir = Split-Path -Parent $MyInvocation.MyCommand.Definition }
Set-Location $dir

Write-Host "目录：$dir"

if (-not (Test-Path (Join-Path $dir ".git"))) {
    Write-Host "`n这个目录不是 git 仓库，没法自动更新。" -ForegroundColor Yellow
    Write-Host "说明当初是手动拷贝安装的。请改成重新克隆："
    Write-Host "  1) 把当前目录删掉"
    Write-Host "  2) git clone https://github.com/2453600693/qr-script-naming.git"
    exit 1
}

Write-Host "`n更新前：" -ForegroundColor Cyan
git log --oneline -1

Write-Host "`n正在拉取…" -ForegroundColor Cyan
git pull

Write-Host "`n更新后：" -ForegroundColor Cyan
git log --oneline -1

Write-Host "`n完成。请重启 Claude Code / DSH，skill 是启动时加载的，不重启还在用旧版。" -ForegroundColor Green
