"""缓存配置。

设计原则：
- 不靠 TTL 决定"数据是否可用"
- 只控制"拉新频率"（避免对东财接口高频打）
- 拉新失败 = 数据保留 + warning，不抛异常

拉新间隔默认（可调整）：
- quote: 5 分钟（"几分钟一次算稳定"）
- today_money_flow: 5 分钟
- market_snapshot: 1 小时（5867 只股票拉一次很贵）
- bars: 1 天（按日期永久保留，重复日期不重拉）
- money_flow_history: 1 天（按日期永久保留）

全市场快照保留 N 份历史，默认 30 份（够看一个月内的变化）。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CacheConfig:
    """缓存配置。

    所有 fetch_*_interval_seconds 控制"拉新间隔"：
    - 上次拉新时间距离现在 < interval → 跳过拉新（用旧数据）
    - 上次拉新时间距离现在 >= interval → 尝试拉新
    """

    quote_fetch_interval_seconds: int = 300  # 5 分钟
    today_money_flow_fetch_interval_seconds: int = 300  # 5 分钟
    market_snapshot_fetch_interval_seconds: int = 3600  # 1 小时
    bar_fetch_interval_seconds: int = 86400  # 1 天
    money_flow_history_fetch_interval_seconds: int = 86400  # 1 天

    market_snapshot_history_keep: int = 30  # 保留最近 N 份全市场快照


def default_config() -> CacheConfig:
    return CacheConfig()
