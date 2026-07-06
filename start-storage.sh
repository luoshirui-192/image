#!/usr/bin/env bash
# 机器 B 一键配置：图片目录 + NFS 导出（不含 MySQL / Docker 应用）
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

if [ ! -f .env ]; then
  cp .env.storage.example .env
  echo "已创建 .env（来自 .env.storage.example）"
  echo "请编辑 DATA_UPLOAD_ROOT、MACHINE_A_HOSTS 后重新运行。"
  exit 0
fi

# shellcheck disable=SC1091
set -a
source <(grep -v '^#' .env | grep -v '^$' | sed 's/\r$//')
set +a

UPLOAD_ROOT="${DATA_UPLOAD_ROOT:-/data/image_db/upload}"
if [ ! -d "$UPLOAD_ROOT" ]; then
  echo "创建图片目录: $UPLOAD_ROOT"
  sudo mkdir -p "$UPLOAD_ROOT"
  sudo chmod 1777 "$UPLOAD_ROOT"
fi

chmod +x scripts/setup-nfs-export.sh
./scripts/setup-nfs-export.sh

echo ""
echo "=========================================="
echo " 机器 B 存储层已就绪"
echo " 图片目录: $UPLOAD_ROOT"
echo " NFS 已导出给: ${MACHINE_A_HOSTS:-（未设置）}"
echo ""
echo " 告知机器 A 管理员挂载："
B_IP="$(hostname -I | awk '{print $1}')"
EXPORT="${NFS_EXPORT_PATH:-$UPLOAD_ROOT}"
echo "  sudo mount -t nfs ${B_IP}:${EXPORT} /opt/image_db/upload"
echo " 详细说明: README-MACHINE-B.md"
echo "=========================================="
