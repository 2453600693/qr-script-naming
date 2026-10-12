#!/usr/bin/env bash
# QR脚本命名工具 · 更新到最新版（macOS / Linux）
# 用法： bash update.sh
set -e
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"
echo "目录：$DIR"

if [ ! -d .git ]; then
  echo ""
  echo "这个目录不是 git 仓库，没法自动更新。"
  echo "说明当初是手动拷贝安装的。请改成重新克隆："
  echo "  1) 把当前目录删掉"
  echo "  2) git clone https://github.com/2453600693/qr-script-naming.git"
  exit 1
fi

echo ""
echo "更新前："
git log --oneline -1
echo ""
echo "正在拉取…"
git pull
echo ""
echo "更新后："
git log --oneline -1
echo ""
echo "完成。请重启 Claude Code / DSH，skill 是启动时加载的，不重启还在用旧版。"
