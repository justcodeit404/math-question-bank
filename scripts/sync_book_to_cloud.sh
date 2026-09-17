#!/usr/bin/env bash
# 单册题库构建产物上云 + sha256 校验（bank-math 不进部署包，走 bank 文件同步，见 docs/server.md）
# 用法: bash scripts/sync_book_to_cloud.sh 1000题
set -euo pipefail

BOOK="${1:-}"
if [[ -z "$BOOK" ]]; then
  echo "用法: bash scripts/sync_book_to_cloud.sh <题库目录名，如 1000题>" >&2
  exit 1
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REMOTE="ubuntu@122.51.26.195"
REMOTE_BANK="/home/ubuntu/kaoyan/apps/bank-math"
LOCAL_DIR="$ROOT/$BOOK/math-bank"

for f in data.js index.html; do
  [[ -f "$LOCAL_DIR/$f" ]] || { echo "缺少 $LOCAL_DIR/$f" >&2; exit 1; }
done
[[ -f "$ROOT/stats.js" ]] || { echo "缺少 $ROOT/stats.js（先跑 generate_data_js.py）" >&2; exit 1; }

scp "$LOCAL_DIR/data.js" "$LOCAL_DIR/index.html" "$REMOTE:$REMOTE_BANK/$BOOK/math-bank/"
scp "$ROOT/stats.js" "$REMOTE:$REMOTE_BANK/stats.js"

LOCAL_HASH=$(sha256sum "$LOCAL_DIR/data.js" | cut -d' ' -f1)
REMOTE_HASH=$(ssh "$REMOTE" "sha256sum '$REMOTE_BANK/$BOOK/math-bank/data.js'" | cut -d' ' -f1)
if [[ "$LOCAL_HASH" != "$REMOTE_HASH" ]]; then
  echo "校验失败: 云端 data.js 哈希不一致" >&2
  echo "  local : $LOCAL_HASH" >&2
  echo "  remote: $REMOTE_HASH" >&2
  exit 1
fi

echo "OK: $BOOK 已上云并通过 sha256 校验"
echo "验证: https://study.xinghebox.cloud/banks/math/$BOOK/math-bank/ （Ctrl+F5）"
