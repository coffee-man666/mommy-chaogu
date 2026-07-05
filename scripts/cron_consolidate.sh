#!/usr/bin/env bash
# cron_consolidate.sh — 周度知识提炼（从 episodic + predictions 提炼 semantic knowledge）
#
# 用法（crontab）：
#   0 18 * * 5 cd /path/to/project && /path/to/scripts/cron_consolidate.sh
#
# 每周五 UTC+8 18:00 执行（盘后总结），
# 跑 consolidate（提炼知识 + 生成 insight_summary）+ verify（验证到期预测）。
#
# 日志写入 data/cron_consolidate.log。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."

LOG_FILE="data/cron_consolidate.log"
mkdir -p data

echo "=== $(date '+%Y-%m-%d %H:%M:%S') ===" >> "$LOG_FILE"

# 先验证到期预测
uv run mommy-agent verify >> "$LOG_FILE" 2>&1 || echo "⚠️ verify failed" >> "$LOG_FILE"

# 再提炼知识
uv run mommy-agent consolidate >> "$LOG_FILE" 2>&1 || echo "⚠️ consolidate failed" >> "$LOG_FILE"

echo "✅ Done" >> "$LOG_FILE"
