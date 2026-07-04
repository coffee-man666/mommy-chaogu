"""统一数据库路径管理。

按用途分库，一库一职责：
- market.db — 行情数据（缓存 + 历史 K 线 + 资金流）
- portfolio.db — 用户数据（自选股 + 持仓 + 自定义告警）
- agent.db — 记忆系统（对话 + 事件 + 预测 + 知识 + 向量）
- reference.db — 参考库（半导体产业链 + 业绩前瞻/实际值）

所有路径可通过环境变量覆盖，默认值保证向后兼容。
"""

from __future__ import annotations

import os
from pathlib import Path


def _path(env_key: str, default: str) -> Path:
    """从环境变量读取路径，默认值兜底。"""
    return Path(os.environ.get(env_key, default))


# 行情数据（缓存 + 历史 K 线 + 资金流）
MARKET_DB: Path = _path("MOMMY_MARKET_DB", "data/market.db")

# 用户数据（自选股 + 持仓）
PORTFOLIO_DB: Path = _path("MOMMY_PORTFOLIO_DB", "data/portfolio.db")

# 记忆系统（对话 + 事件 + 预测 + 知识 + 向量）
AGENT_DB: Path = _path("MOMMY_AGENT_DB", "data/agent.db")

# 参考库（半导体产业链 + 业绩前瞻 + 业绩实际值）
REFERENCE_DB: Path = _path("MOMMY_REFERENCE_DB", "data/reference.db")

# 旧路径（仅用于自动迁移检测）
LEGACY_WATCHLIST_DB: Path = Path("data/watchlist.db")
LEGACY_SEMICON_DB: Path = Path("data/semicon.db")
LEGACY_EARNINGS_PREVIEW_DB: Path = Path("data/earnings_preview.db")
LEGACY_EARNINGS_ACTUAL_DB: Path = Path("data/earnings_actual.db")
LEGACY_BACKTEST_DB: Path = Path("data/semicon_backtest.db")
