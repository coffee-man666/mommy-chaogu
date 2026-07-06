#!/usr/bin/env bash
# cron_verify.sh — 验证到期预测（A 股收盘后自动跑）
#
# 用法（crontab）：
#   0 16 * * 1-5 cd /path/to/project && /path/to/scripts/cron_verify.sh
#
# 每天周一到周五 UTC+8 16:00 执行（A 股 15:00 收盘后 1 小时），
# 避开 15:00-15:30 的数据空窗。
#
# 日志写入 data/cron_verify.log。
set -euo pipefail

# 切到脚本所在项目的根目录（crontab 里 cd 不一定可靠）
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."

LOG_FILE="data/cron_verify.log"

# 确保 data 目录存在
mkdir -p data

{
    echo "======================================"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] cron_verify 开始"
    echo "======================================"
} >> "$LOG_FILE"

if uv run mommy-agent verify >> "$LOG_FILE" 2>&1; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] cron_verify 成功" >> "$LOG_FILE"
else
    rc=$?
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] cron_verify 失败 (exit $rc)" >> "$LOG_FILE"
    echo "cron_verify 失败 (exit $rc)，详见 $LOG_FILE" >&2
    exit "$rc"
fi
