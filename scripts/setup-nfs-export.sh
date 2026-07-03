#!/usr/bin/env bash
# 在机器 B 上配置 NFS 导出 upload 目录（Ubuntu/Debian）
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [ ! -f .env ]; then
  echo "错误: 未找到 .env"
  exit 1
fi

# shellcheck disable=SC1091
set -a
source <(grep -v '^#' .env | grep -v '^$' | sed 's/\r$//')
set +a

EXPORT_PATH="${NFS_EXPORT_PATH:-${DATA_UPLOAD_ROOT:-/data/image_db/upload}}"
HOSTS="${MACHINE_A_HOSTS:-}"

if [ -z "$HOSTS" ]; then
  echo "错误: .env 中 MACHINE_A_HOSTS 未设置"
  exit 1
fi

if [ ! -d "$EXPORT_PATH" ]; then
  sudo mkdir -p "$EXPORT_PATH"
  sudo chmod 1777 "$EXPORT_PATH"
fi

if ! dpkg -l nfs-kernel-server >/dev/null 2>&1; then
  echo "安装 nfs-kernel-server ..."
  sudo apt-get update
  sudo apt-get install -y nfs-kernel-server
fi

EXPORTS_LINE=""
for IP in $HOSTS; do
  EXPORTS_LINE+="${EXPORT_PATH} ${IP}(rw,sync,no_subtree_check,no_root_squash) "
done

MARKER="# image-db-machine-b"
if grep -q "$MARKER" /etc/exports 2>/dev/null; then
  sudo sed -i "/$MARKER/,/${MARKER}-end/d" /etc/exports
fi

{
  echo "$MARKER"
  echo "$EXPORTS_LINE"
  echo "${MARKER}-end"
} | sudo tee -a /etc/exports >/dev/null

sudo exportfs -ra
sudo systemctl enable nfs-server
sudo systemctl restart nfs-server

echo "NFS 已导出: $EXPORT_PATH"
echo "机器 A 挂载示例:"
for IP in $HOSTS; do
  echo "  sudo mount -t nfs $(hostname -I | awk '{print $1}'):${EXPORT_PATH} /opt/image_db/upload"
done
