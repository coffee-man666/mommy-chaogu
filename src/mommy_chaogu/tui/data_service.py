"""TUI 专用异步数据服务。

直接复用项目内部 adapter/store（参考 web/deps.py 的构造方式），
不走 HTTP。所有方法为 async，内部用 anyio 把同步调用丢到线程池，
避免阻塞 Textual 事件循环。
"""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from anyio import to_thread
from dotenv import load_dotenv

if TYPE_CHECKING:
    from mommy_chaogu.agent.service import AgentService
    from mommy_chaogu.cache import CachedMarketDataAdapter
    from mommy_chaogu.market_data import Quote
    from mommy_chaogu.portfolio.store import PortfolioStore
    from mommy_chaogu.watchlist.store import WatchlistStore

_log = logging.getLogger(__name__)


class TUIDataService:
    """TUI 专用数据服务，直接调项目内部 adapter/store。"""

    def __init__(self) -> None:
        load_dotenv()

        from mommy_chaogu.cache import CachedMarketDataAdapter, CacheStore
        from mommy_chaogu.db_paths import AGENT_DB, MARKET_DB, PORTFOLIO_DB
        from mommy_chaogu.market_data import (
            EfinanceAdapter,
            FallbackAdapter,
            TencentAdapter,
        )
        from mommy_chaogu.portfolio.store import PortfolioStore
        from mommy_chaogu.watchlist.store import WatchlistStore

        self.agent_db = AGENT_DB
        base: Any = FallbackAdapter([EfinanceAdapter(), TencentAdapter()])  # type: ignore[list-item]
        self.adapter: CachedMarketDataAdapter = CachedMarketDataAdapter(base, CacheStore(MARKET_DB))
        self.watchlist_store: WatchlistStore = WatchlistStore(PORTFOLIO_DB)
        self.portfolio_store: PortfolioStore = PortfolioStore(PORTFOLIO_DB)
        self._agent: AgentService | None = None
        self._agent_init_attempted = False

    # ------------------------------------------------------------------
    # Agent（lazy init，无 API key 时返回 None）
    # ------------------------------------------------------------------

    @property
    def agent(self) -> AgentService | None:
        """Lazy init AgentService（需要 API key）。

        初始化失败只尝试一次，后续直接返回 None。
        """
        if self._agent_init_attempted:
            return self._agent
        self._agent_init_attempted = True

        import os

        from mommy_chaogu.agent.service import AgentService
        from mommy_chaogu.agent.tools import ToolContext

        api_key = (
            os.environ.get("DEEPSEEK_API_KEY")
            or os.environ.get("OPENAI_API_KEY")
            or os.environ.get("ZAI_API_KEY")
            or os.environ.get("MOONSHOT_API_KEY")
        )
        if not api_key:
            _log.info("未配置 API key，Agent 功能不可用")
            return None

        try:
            ctx = ToolContext(
                adapter=self.adapter,
                watchlist_store=self.watchlist_store,
                portfolio_store=self.portfolio_store,
                db_path=self.agent_db,
            )
            self._agent = AgentService(ctx)
        except Exception as e:
            _log.warning("AgentService 初始化失败: %s", e)
            return None
        return self._agent

    # ------------------------------------------------------------------
    # 行情数据
    # ------------------------------------------------------------------

    async def get_quotes(self, codes: list[str]) -> list[Quote]:
        """批量获取报价（逐个拉，适配器内部有缓存节流）。"""
        if not codes:
            return []

        def _fetch() -> list[Quote]:
            results: list[Quote] = []
            for code in codes:
                try:
                    q = self.adapter.get_quote(code)
                    if q is not None:
                        results.append(q)
                except Exception as e:
                    _log.debug("拉取 %s 报价失败: %s", code, e)
            return results

        return await to_thread.run_sync(_fetch)

    async def get_indexes(self) -> list[dict[str, Any]]:
        """获取大盘指数（上证/深证/创业板等）。

        参考 web/routes/market.py，走 rankings.fetch_indexes()。
        """
        from mommy_chaogu.market_data.rankings import fetch_indexes

        def _fetch() -> list[dict[str, Any]]:
            try:
                items = fetch_indexes()
                return [
                    {
                        "code": i.code,
                        "name": i.name,
                        "price": i.price,
                        "change_pct": i.change_pct,
                        "prev_close": i.prev_close,
                    }
                    for i in items
                ]
            except Exception as e:
                _log.warning("拉取指数失败: %s", e)
                return []

        return await to_thread.run_sync(_fetch)

    async def get_bars(self, code: str, limit: int = 20) -> list[dict[str, Any]]:
        """获取日 K 线数据。"""
        from mommy_chaogu.market_data import BarInterval

        def _fetch() -> list[dict[str, Any]]:
            try:
                bars = self.adapter.get_bars(code, interval=BarInterval.D1, limit=limit)
                return [
                    {
                        "date": b.timestamp.strftime("%Y-%m-%d"),
                        "open": b.open,
                        "high": b.high,
                        "low": b.low,
                        "close": b.close,
                        "volume": b.volume,
                        "turnover": b.turnover.amount,
                        "change_pct": b.change_pct,
                    }
                    for b in bars
                ]
            except Exception as e:
                _log.warning("拉取 %s K 线失败: %s", code, e)
                return []

        return await to_thread.run_sync(_fetch)

    # ------------------------------------------------------------------
    # 自选股
    # ------------------------------------------------------------------

    async def get_watchlist_stocks(self) -> dict[str, list[dict[str, Any]]]:
        """获取自选股列表，按分组返回 {group_name: [{code, name, note}]}。"""

        def _fetch() -> dict[str, list[dict[str, Any]]]:
            try:
                grouped = self.watchlist_store.list_entries_by_group()
                return {
                    gname: [
                        {"code": e.code, "name": e.name or e.code, "note": e.note or ""}
                        for e in entries
                    ]
                    for gname, entries in grouped.items()
                }
            except Exception as e:
                _log.warning("拉取自选股失败: %s", e)
                return {}

        return await to_thread.run_sync(_fetch)

    async def get_all_watchlist_codes(self) -> list[str]:
        """获取所有自选股代码（去重）。"""

        def _fetch() -> list[str]:
            try:
                return self.watchlist_store.get_all_codes()
            except Exception as e:
                _log.warning("拉取自选股代码失败: %s", e)
                return []

        return await to_thread.run_sync(_fetch)

    # ------------------------------------------------------------------
    # 持仓
    # ------------------------------------------------------------------

    async def get_portfolio_summary(self) -> dict[str, Any]:
        """获取持仓总览（含实时盈亏）。

        参考 web/routes/portfolio.py 的逻辑。
        """

        def _fetch() -> dict[str, Any]:
            positions = self.portfolio_store.list_positions()
            if not positions:
                return {
                    "positions": [],
                    "total_cost": Decimal("0"),
                    "total_market_value": None,
                    "total_unrealized_pnl": None,
                    "total_unrealized_pnl_pct": None,
                    "n_positions": 0,
                }

            # 拉实时价格
            codes = list({p.code for p in positions})
            current_prices: dict[str, Decimal] = {}
            for code in codes:
                try:
                    q = self.adapter.get_quote(code)
                    if q is not None:
                        current_prices[code] = q.price
                except Exception:
                    pass

            try:
                return self.portfolio_store.summary(current_prices)
            except Exception as e:
                _log.warning("持仓 summary 失败: %s", e)
                return {
                    "positions": [],
                    "total_cost": Decimal("0"),
                    "total_market_value": None,
                    "total_unrealized_pnl": None,
                    "total_unrealized_pnl_pct": None,
                    "n_positions": 0,
                }

        return await to_thread.run_sync(_fetch)

    # ------------------------------------------------------------------
    # Agent 对话
    # ------------------------------------------------------------------

    async def chat(self, message: str, history: list[dict[str, str]] | None = None) -> str:
        """调 agent 对话。agent 不可用时返回提示文本。"""
        ag = self.agent
        if ag is None:
            return (
                "⚠️ Agent 不可用：未配置 API key（DEEPSEEK_API_KEY / OPENAI_API_KEY / ZAI_API_KEY）"
            )

        def _chat() -> str:
            try:
                resp = ag.chat(message, history=history)
                return resp.text
            except Exception as e:
                _log.warning("agent chat 失败: %s", e)
                return f"❌ Agent 调用失败: {e}"

        return await to_thread.run_sync(_chat)

    # ------------------------------------------------------------------
    # 辅助：当前时间
    # ------------------------------------------------------------------

    def get_current_time(self) -> str:
        """获取当前时间。"""
        return datetime.now().strftime("%H:%M:%S")
