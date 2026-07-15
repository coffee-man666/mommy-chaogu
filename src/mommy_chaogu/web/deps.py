"""依赖注入：FastAPI Depends() 全局单例。

设计：
- Adapter / Store / Alerter / Cache 全部 lazy-init 单例
- 测试时用 app.dependency_overrides 替换
- 不在 import 时拉网络（fail-fast 但不起连接）

数据库分库（见 db_paths.py）：
- market.db — 行情缓存
- portfolio.db — 自选股 + 持仓
- agent.db — 记忆系统
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from mommy_chaogu.cache import CachedMarketDataAdapter, CacheStore
from mommy_chaogu.db_paths import AGENT_DB, MARKET_DB, PORTFOLIO_DB
from mommy_chaogu.market_data import (
    EfinanceAdapter,
    FallbackAdapter,
    MarketDataAdapter,
    TencentAdapter,
)
from mommy_chaogu.portfolio import PortfolioStore
from mommy_chaogu.signals import Alerter
from mommy_chaogu.watchlist import WatchlistStore


@lru_cache(maxsize=1)
def get_market_db() -> Path:
    """行情数据库路径。"""
    return MARKET_DB


@lru_cache(maxsize=1)
def get_portfolio_db() -> Path:
    """用户数据库路径（自选股 + 持仓）。"""
    return PORTFOLIO_DB


@lru_cache(maxsize=1)
def get_agent_db() -> Path:
    """记忆系统数据库路径。"""
    return AGENT_DB


# 向后兼容：旧代码引用 get_db_path() 的地方
@lru_cache(maxsize=1)
def get_db_path() -> Path:
    """全局 DB 路径（向后兼容，指向 portfolio.db）。"""
    return PORTFOLIO_DB


@lru_cache(maxsize=1)
def get_adapter() -> MarketDataAdapter:
    """全局数据源装饰器链：CachedMarketDataAdapter(Fallback([Efinance, Tencent]))。

    走项目核心设计（DESIGN §2 P2/P3/P4）：
    - Fallback：主源挂 → 备源
    - Cache：DB 有就用，没有才拉新，失败 fallback 旧数据
    """
    adapter = CachedMarketDataAdapter(
        FallbackAdapter([EfinanceAdapter(), TencentAdapter()]),
        CacheStore(get_market_db()),
    )
    return adapter


@lru_cache(maxsize=1)
def get_watchlist_store() -> WatchlistStore:
    """全局自选池存储。"""
    return WatchlistStore(get_portfolio_db())


@lru_cache(maxsize=1)
def get_alerter() -> Alerter:
    """全局告警器。"""
    log_path = Path("data/signals.log")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    return Alerter.default(log_path=log_path)


@lru_cache(maxsize=1)
def get_portfolio_store() -> PortfolioStore:
    """全局持仓存储。"""
    return PortfolioStore(get_portfolio_db())


# ---------- 记忆系统 ----------


@lru_cache(maxsize=1)
def get_agent_memory() -> object:
    """全局 ConversationMemory 单例。"""
    from mommy_chaogu.agent.memory import ConversationMemory

    return ConversationMemory(get_agent_db())


@lru_cache(maxsize=1)
def get_episodic_memory() -> object:
    """全局 EpisodicMemory 单例（情景记忆）。"""
    from mommy_chaogu.agent.episodic_memory import EpisodicMemory

    return EpisodicMemory(get_agent_db())


@lru_cache(maxsize=1)
def get_prediction_tracker() -> object:
    """全局 PredictionTracker 单例（预测追踪）。"""
    from mommy_chaogu.agent.prediction_tracker import PredictionTracker

    return PredictionTracker(get_agent_db())


@lru_cache(maxsize=1)
def get_semantic_memory() -> object:
    """全局 SemanticMemory 单例（语义知识库）。"""
    from mommy_chaogu.agent.semantic_memory import SemanticMemory

    return SemanticMemory(get_agent_db())


@lru_cache(maxsize=1)
def get_memory_service() -> object:
    """全局 MemoryService 单例。

    封装 MemoryPipeline + ConversationMemory，
    任何需要记忆能力的入口（AgentService / MCP）都可使用。
    """
    from mommy_chaogu.agent.memory_pipeline import MemoryPipeline
    from mommy_chaogu.agent.memory_service import MemoryService

    episodic = get_episodic_memory()
    tracker = get_prediction_tracker()
    semantic = get_semantic_memory()

    pipeline = None
    if episodic is not None and tracker is not None:
        # MemoryPipeline 需要 LLM client 做事实提取，
        # 但这里不传 client — get_context 不需要 LLM，
        # record_analysis 的 LLM 提取在 AgentService 构造后补充。
        pipeline = MemoryPipeline(
            episodic=episodic,
            tracker=tracker,
            semantic=semantic,
        )

    return MemoryService(
        pipeline=pipeline,
        memory=get_agent_memory(),
    )


@lru_cache(maxsize=1)
def get_agent_service() -> object:
    """全局 AgentService 单例（lazy init）。

    通过 load_config() 解析 provider（shell env > .env > config.toml），
    自动读取对应的 API key。如果未配置则返回 None（路由层处理降级）。
    """
    from mommy_chaogu.agent.service import AgentService
    from mommy_chaogu.agent.tools import ToolContext
    from mommy_chaogu.config import load_config

    cfg = load_config()
    if not cfg.agent.api_key:
        return None  # type: ignore[return-value]

    ctx = ToolContext(
        adapter=get_adapter(),
        watchlist_store=get_watchlist_store(),
        portfolio_store=get_portfolio_store(),
        db_path=get_agent_db(),
    )

    # AgentService 内部会从散件构造 MemoryPipeline（带 LLM client），
    # 所以这里直接传 episodic/tracker/semantic 保持兼容。
    return AgentService(
        ctx,
        provider=cfg.agent.provider,
        model=cfg.agent.model,
        api_key=cfg.agent.api_key,
        episodic=get_episodic_memory(),
        tracker=get_prediction_tracker(),
        semantic=get_semantic_memory(),
    )


def close_cached_dependencies() -> None:
    """Close owned resources and clear dependency singletons.

    Only dependencies that were actually constructed are evaluated, so
    shutdown never creates a resource merely to close it.
    """
    resource_factories = (
        get_adapter,
        get_watchlist_store,
        get_portfolio_store,
        get_agent_memory,
        get_episodic_memory,
        get_prediction_tracker,
        get_semantic_memory,
    )
    for factory in resource_factories:
        cache_info = getattr(factory, "cache_info", None)
        if cache_info is None or cache_info().currsize == 0:
            continue
        resource = factory()
        close = getattr(resource, "close", None)
        if close is not None:
            close()

    for factory in (
        get_agent_service,
        get_memory_service,
        *resource_factories,
        get_alerter,
    ):
        cache_clear = getattr(factory, "cache_clear", None)
        if cache_clear is not None:
            cache_clear()
