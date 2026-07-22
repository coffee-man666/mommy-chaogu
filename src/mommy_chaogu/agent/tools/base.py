"""工具层共享基础设施：ToolDef / ToolContext / ToolHandler + JSON 序列化辅助。

设计：
- ToolDef: 工具定义（name + description + JSON Schema parameters）
- ToolContext: 共享的依赖注入容器（adapter + stores）
- ToolHandler: 工具实现函数签名（同步函数，内部直接调 adapter，
  已被 CachedMarketDataAdapter 包装；AgentService 负责用 asyncio.to_thread 包装）

各域工具实现见同级模块（quote / sector / flows / bars / holdings /
intel / alerts / memory / themes），注册聚合见 registry.py。
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mommy_chaogu.market_data.adapter import MarketDataAdapter
from mommy_chaogu.market_data.types import Quote
from mommy_chaogu.portfolio.store import PortfolioStore
from mommy_chaogu.watchlist.store import WatchlistStore


@dataclass(frozen=True)
class ToolDef:
    """单个工具的定义。"""

    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema

    def to_openai_dict(self) -> dict[str, Any]:
        """转 OpenAI function-calling 格式。"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


@dataclass
class ToolContext:
    """工具层的共享依赖。

    数据库路径按职责拆分（见 db_paths.py）：
    - ``agent_db``: 记忆系统（episodic / predictions / semantic）
    - ``market_db``: 行情缓存（CacheStore：K 线回填 / 资金流 / quote 缓存）
    - ``portfolio_db``: 用户数据（自选股 / 持仓 / 自定义告警）

    旧字段 ``db_path`` 保留作向后兼容：工具优先读专用字段，专用字段为
    None 时回退 ``db_path``（见 ``resolved_*`` 属性）。
    """

    adapter: MarketDataAdapter
    watchlist_store: WatchlistStore | None = None
    portfolio_store: PortfolioStore | None = None
    db_path: Path | None = None
    agent_db: Path | None = None
    market_db: Path | None = None
    portfolio_db: Path | None = None
    # LLM / embedding client（OpenAI 兼容），记忆查询工具需要。
    # 为 None 时记忆工具降级为无 LLM 模式。
    client: Any | None = None
    model: str | None = None
    # 独立记忆服务（MCP 等非 AgentService 入口用）
    memory_service: Any | None = None

    @property
    def resolved_agent_db(self) -> Path | None:
        """记忆系统数据库：``agent_db``，缺省回退 ``db_path``。"""
        return self.agent_db or self.db_path

    @property
    def resolved_market_db(self) -> Path | None:
        """行情缓存数据库：``market_db``，缺省回退 ``db_path``。"""
        return self.market_db or self.db_path

    @property
    def resolved_portfolio_db(self) -> Path | None:
        """用户数据数据库：``portfolio_db``，缺省回退 ``db_path``。"""
        return self.portfolio_db or self.db_path


ToolHandler = Callable[[ToolContext, dict[str, Any]], str]


def _quote_to_dict(q: Quote) -> dict[str, Any]:
    return {
        "code": q.code,
        "name": q.name,
        "price": float(q.price),
        "change_pct": float(q.change_pct),
        "change": float(q.change),
        "open": float(q.open),
        "high": float(q.high),
        "low": float(q.low),
        "prev_close": float(q.prev_close),
        "volume": q.volume,
        "turnover": float(q.turnover.amount),
        "turnover_rate": float(q.turnover_rate) if q.turnover_rate else None,
        "volume_ratio": float(q.volume_ratio) if q.volume_ratio else None,
        "pe": float(q.pe_dynamic) if q.pe_dynamic else None,
        "total_market_cap": float(q.total_market_cap.amount) if q.total_market_cap else None,
        "circulating_market_cap": (
            float(q.circulating_market_cap.amount) if q.circulating_market_cap else None
        ),
        "timestamp": q.timestamp.isoformat(),
    }


def _json(obj: Any) -> str:
    """安全 JSON 序列化（处理 Decimal / datetime）。"""
    return json.dumps(obj, ensure_ascii=False, default=str, separators=(",", ":"))
