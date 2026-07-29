"""统一数据库路径管理。

按用途分库，一库一职责：
- market.db — 行情数据（缓存 + 历史 K 线 + 资金流）
- portfolio.db — 用户数据（自选股 + 持仓 + 自定义告警）
- agent.db — 记忆系统（对话 + 事件 + 预测 + 知识 + 向量）
- reference.db — 参考库（半导体产业链 + 业绩前瞻/实际值）

所有路径可通过环境变量覆盖。源码仓库默认使用 ``data/``，全局安装命令默认使用
``~/.local/share/mommy-chaogu/``，避免数据库随当前工作目录漂移。
"""

from __future__ import annotations

import os
from pathlib import Path


def default_data_dir() -> Path:
    """Use repo-local data in source checkouts and user data for installed tools."""
    override = os.environ.get("MOMMY_DATA_DIR", "").strip()
    if override:
        return Path(override).expanduser()

    cwd = Path.cwd()
    if (cwd / "pyproject.toml").is_file() and (cwd / "src" / "mommy_chaogu").is_dir():
        return Path("data")

    xdg_data_home = os.environ.get("XDG_DATA_HOME", "").strip()
    root = Path(xdg_data_home).expanduser() if xdg_data_home else Path.home() / ".local" / "share"
    return root / "mommy-chaogu"


DEFAULT_DATA_DIR = default_data_dir()


def _path(env_key: str, filename: str) -> Path:
    """Read an explicit database path or place it in the default data directory."""
    override = os.environ.get(env_key, "").strip()
    return Path(override).expanduser() if override else DEFAULT_DATA_DIR / filename


# 行情数据（缓存 + 历史 K 线 + 资金流）
MARKET_DB: Path = _path("MOMMY_MARKET_DB", "market.db")

# 用户数据（自选股 + 持仓）
PORTFOLIO_DB: Path = _path("MOMMY_PORTFOLIO_DB", "portfolio.db")

# 记忆系统（对话 + 事件 + 预测 + 知识 + 向量）
AGENT_DB: Path = _path("MOMMY_AGENT_DB", "agent.db")

# 参考库（半导体产业链 + 业绩前瞻 + 业绩实际值）
REFERENCE_DB: Path = _path("MOMMY_REFERENCE_DB", "reference.db")

# 旧路径（仅用于自动迁移检测）
LEGACY_WATCHLIST_DB: Path = Path("data/watchlist.db")
LEGACY_SEMICON_DB: Path = Path("data/semicon.db")
LEGACY_EARNINGS_PREVIEW_DB: Path = Path("data/earnings_preview.db")
LEGACY_EARNINGS_ACTUAL_DB: Path = Path("data/earnings_actual.db")
LEGACY_BACKTEST_DB: Path = Path("data/semicon_backtest.db")
