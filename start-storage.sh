#!/usr/bin/env bash
# 机器 B 一键配置：MinIO 前缀初始化（不含 MySQL / Docker 应用）
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

if [[ ! -f .env ]]; then
  cp .env.storage.example .env
  echo "已创建 .env（来自 .env.storage.example）"
  echo "请编辑 MINIO_ACCESS_KEY、MINIO_SECRET_KEY、MACHINE_A_HOSTS 后重新运行。"
  exit 0
fi

chmod +x scripts/setup-minio-prefix.sh
./scripts/setup-minio-prefix.sh

echo ""
echo "========================================"
echo " 机器 B（MinIO 存储层）已就绪"
echo "========================================"
echo " 请将 MinIO 配置交给机器 A，详见 README-MACHINE-B.md"
echo ""
