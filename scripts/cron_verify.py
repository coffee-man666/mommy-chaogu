#!/usr/bin/env python
"""cron_verify.py — 验证到期预测（可移植版，不依赖 shell）。

直接 import 并复用 ``cmd_agent_verify`` 的核心逻辑，不经过 CLI 解析，
方便在 Windows / 非 bash 环境或容器里跑。

日志同时输出到 stdout 和 ``data/cron_verify.log``。

用法::

    uv run python scripts/cron_verify.py
    uv run python scripts/cron_verify.py --db data/agent.db
    uv run python scripts/cron_verify.py --log data/cron_verify.log

crontab 用法（与 shell 版等价）::

    0 16 * * 1-5 cd /path/to/project && uv run python scripts/cron_verify.py
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

DEFAULT_AGENT_DB = "data/agent.db"
DEFAULT_LOG = "data/cron_verify.log"


def _setup_logger(log_path: Path) -> logging.Logger:
    """配置 logger：同时写 stdout 和 log 文件。"""
    log_path.parent.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("cron_verify")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    fmt = logging.Formatter("[%(asctime)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

    stream_h = logging.StreamHandler(sys.stdout)
    stream_h.setFormatter(fmt)
    logger.addHandler(stream_h)

    file_h = logging.FileHandler(log_path, encoding="utf-8")
    file_h.setFormatter(fmt)
    logger.addHandler(file_h)

    return logger


def run_verify(db_path: Path, logger: logging.Logger) -> dict[str, int]:
    """执行验证并返回统计 dict。

    复用 ``cmd_agent_verify`` 里的依赖装配 + ``verify_pending`` 调用，
    而不是走 argparse，这样 cron 调用更轻量也更可测。
    """
    from mommy_chaogu.agent.episodic_memory import EpisodicMemory
    from mommy_chaogu.agent.prediction_tracker import PredictionTracker
    from mommy_chaogu.agent.verify_engine import verify_pending
    from mommy_chaogu.cache import CachedMarketDataAdapter, CacheStore
    from mommy_chaogu.db_paths import MARKET_DB
    from mommy_chaogu.market_data import (
        EfinanceAdapter,
        FallbackAdapter,
        TencentAdapter,
    )

    tracker = PredictionTracker(db_path)
    episodic = EpisodicMemory(db_path)

    # 行情缓存属于 market.db（与缓存层读取一致），不写进 agent.db
    store = CacheStore(MARKET_DB)
    base = FallbackAdapter([EfinanceAdapter(), TencentAdapter()])
    adapter = CachedMarketDataAdapter(base, store)

    logger.info("🔍 验证到期预测...")
    logger.info("%s", "─" * 60)

    results = verify_pending(
        tracker=tracker,
        episodic=episodic,
        adapter=adapter,
        cache_store=store,
    )
    return results


def main() -> int:
    parser = argparse.ArgumentParser(
        description="验证到期预测（cron 用，可移植版）",
    )
    parser.add_argument(
        "--db",
        default=DEFAULT_AGENT_DB,
        help=f"数据库路径 (默认 {DEFAULT_AGENT_DB})",
    )
    parser.add_argument(
        "--log",
        default=DEFAULT_LOG,
        help=f"日志文件路径 (默认 {DEFAULT_LOG})",
    )
    args = parser.parse_args()

    db_path = Path(args.db)
    log_path = Path(args.log)
    logger = _setup_logger(log_path)

    try:
        results = run_verify(db_path, logger)
    except Exception:
        logger.exception("cron_verify 失败")
        return 1

    # 统计摘要
    logger.info("验证 %d 条预测", results["total"])
    logger.info("  ✅ hit: %d", results["hit"])
    logger.info("  ❌ missed: %d", results["missed"])
    logger.info("  ⚠️  data_unavailable: %d", results["data_unavailable"])
    logger.info("  ⏰ expired: %d", results["expired"])

    decided = results["hit"] + results["missed"]
    if decided > 0:
        rate = results["hit"] / decided * 100
        logger.info("命中率: %.0f%%", rate)

    logger.info("cron_verify 完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
