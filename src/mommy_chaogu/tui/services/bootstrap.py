"""Services 容器装配（§5.1）。

App 启动时组装一次 Services 容器，widget 通过 self.app.services 访问。
测试时注入 FakeServices。
"""

from __future__ import annotations

import contextlib
import logging
import os
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from dotenv import load_dotenv

_log = logging.getLogger(__name__)


@dataclass
class DataService:
    """行情/持仓数据服务，封装 adapter。"""

    adapter: Any = None
    watchlist_store: Any = None
    portfolio_store: Any = None
    _source_label: str = "初始化中"

    def watchlist_quotes(self) -> list[dict[str, Any]]:
        """批量获取自选股报价 + 主力资金流。"""
        if self.adapter is None:
            return []
        codes: list[str] = []
        if self.watchlist_store:
            with contextlib.suppress(Exception):
                codes = self.watchlist_store.get_all_codes()
        if not codes:
            return []

        rows: list[dict[str, Any]] = []
        for code in codes:
            try:
                q = self.adapter.get_quote(code)
                if q is None:
                    continue
                flow_val = None
                try:
                    flows = self.adapter.get_today_money_flow(code)
                    if flows:
                        flow_val = getattr(flows[-1], "main_net", None)
                except Exception:
                    pass
                rows.append({
                    "code": code,
                    "name": getattr(q, "name", code),
                    "price": q.price,
                    "change_pct": getattr(q, "change_pct", None),
                    "change_amount": getattr(q, "change", None),
                    "main_flow": flow_val,
                })
            except Exception as e:
                _log.debug("拉取 %s 失败: %s", code, e)

        self._source_label = self.adapter.format_source_label() if hasattr(self.adapter, "format_source_label") else ""
        return rows

    def portfolio_snapshot(self) -> dict[str, Any]:
        """持仓快照 = portfolio.db × 实时报价 join。"""
        if self.portfolio_store is None:
            return {"positions": [], "total_market_value": None, "total_unrealized_pnl": None}
        try:
            positions = self.portfolio_store.list_positions()
            if not positions:
                return {"positions": [], "total_market_value": None, "total_unrealized_pnl": None}
            codes = list({p.code for p in positions})
            prices: dict[str, Decimal] = {}
            if self.adapter:
                for code in codes:
                    try:
                        q = self.adapter.get_quote(code)
                        if q:
                            prices[code] = q.price
                    except Exception:
                        pass
            return self.portfolio_store.summary(prices)  # type: ignore[no-any-return]
        except Exception as e:
            _log.warning("持仓快照失败: %s", e)
            return {"positions": [], "total_market_value": None, "total_unrealized_pnl": None}

    def source_label(self) -> str:
        return self._source_label


@dataclass
class AgentBridge:
    """路由 + agent 流式 + 取消。"""

    _agent: Any = None
    _router: Any = None

    def route(self, text: str) -> Any:
        """尝试路由匹配。返回 RouteResult。"""
        if self._router is None:
            return None
        return self._router.route(text)

    def execute_workflow(self, route_result: Any, text: str, on_step_start: Any = None, on_step_done: Any = None) -> Any:
        if self._router is None:
            return None
        return self._router.execute_route(route_result, text, on_step_start=on_step_start, on_step_done=on_step_done)

    def has_agent(self) -> bool:
        return self._agent is not None

    def chat(self, message: str, history: list[dict[str, str]] | None = None, on_tool_call: Any = None) -> Any:
        if self._agent is None:
            return None
        return self._agent.chat(message, history=history, on_tool_call=on_tool_call)


@dataclass
class Services:
    """服务容器，所有 widget 通过 self.app.services 访问。"""

    data: DataService = field(default_factory=DataService)
    agent: AgentBridge = field(default_factory=AgentBridge)

    @classmethod
    def bootstrap(cls) -> Services:
        """生产环境装配：从项目内部构建 adapter + agent。"""
        load_dotenv()
        from mommy_chaogu.cache import CachedMarketDataAdapter, CacheStore
        from mommy_chaogu.db_paths import AGENT_DB, MARKET_DB, PORTFOLIO_DB
        from mommy_chaogu.market_data import EfinanceAdapter, FallbackAdapter, TencentAdapter
        from mommy_chaogu.portfolio.store import PortfolioStore
        from mommy_chaogu.watchlist.store import WatchlistStore

        base = FallbackAdapter([EfinanceAdapter(), TencentAdapter()])  # type: ignore[list-item]
        adapter = CachedMarketDataAdapter(base, CacheStore(MARKET_DB))  # type: ignore[arg-type]
        data_svc = DataService(
            adapter=adapter,
            watchlist_store=WatchlistStore(PORTFOLIO_DB),
            portfolio_store=PortfolioStore(PORTFOLIO_DB),
        )

        agent_bridge = AgentBridge()

        # 尝试初始化 agent
        api_key = (
            os.environ.get("DEEPSEEK_API_KEY")
            or os.environ.get("OPENAI_API_KEY")
            or os.environ.get("ZAI_API_KEY")
            or os.environ.get("MOONSHOT_API_KEY")
        )
        if api_key:
            try:
                from mommy_chaogu.agent.episodic_memory import EpisodicMemory
                from mommy_chaogu.agent.prediction_tracker import PredictionTracker
                from mommy_chaogu.agent.semantic_memory import SemanticMemory
                from mommy_chaogu.agent.service import AgentService
                from mommy_chaogu.agent.tools import ToolContext, ToolRegistry

                ctx = ToolContext(
                    adapter=adapter,
                    watchlist_store=WatchlistStore(PORTFOLIO_DB),
                    portfolio_store=PortfolioStore(PORTFOLIO_DB),
                    db_path=AGENT_DB,
                )
                agent_bridge._agent = AgentService(
                    ctx,
                    episodic=EpisodicMemory(AGENT_DB),
                    tracker=PredictionTracker(AGENT_DB),
                    semantic=SemanticMemory(AGENT_DB),
                )
            except Exception as e:
                _log.warning("AgentService 初始化失败: %s", e)

        # 尝试初始化 router
        try:
            from mommy_chaogu.agent.tools import ToolContext, ToolRegistry
            from mommy_chaogu.workflow.engine import WorkflowExecutor
            from mommy_chaogu.workflow.router import NLRouter

            ctx = ToolContext(
                adapter=adapter,
                watchlist_store=WatchlistStore(PORTFOLIO_DB),
                portfolio_store=PortfolioStore(PORTFOLIO_DB),
                db_path=AGENT_DB,
            )
            tool_registry = ToolRegistry(ctx)

            llm_summarizer = None
            if agent_bridge._agent is not None:
                class _Adapter:
                    def __init__(self, svc: Any) -> None:
                        self._svc = svc

                    def summarize(self, template: str, context: str) -> str:
                        prompt = template.format(context=context)
                        resp = self._svc.chat_raw([{"role": "user", "content": prompt}])
                        return resp.text  # type: ignore[no-any-return]

                llm_summarizer = _Adapter(agent_bridge._agent)

            executor = WorkflowExecutor(tool_registry, llm_summarizer=llm_summarizer)
            agent_bridge._router = NLRouter(executor=executor)
        except Exception as e:
            _log.warning("NLRouter 初始化失败: %s", e)

        return cls(data=data_svc, agent=agent_bridge)


@dataclass
class FakeServices:
    """测试用假数据服务。"""

    data: DataService = field(default_factory=DataService)
    agent: AgentBridge = field(default_factory=AgentBridge)

    @classmethod
    def create(cls) -> FakeServices:
        """创建带假数据的 Services。"""
        fake_rows = [
            {"code": "688981", "name": "中芯国际", "price": Decimal("87.45"), "change_pct": 2.31, "change_amount": 1.98, "main_flow": Decimal("230000000")},
            {"code": "600519", "name": "贵州茅台", "price": Decimal("1680.00"), "change_pct": -0.52, "change_amount": -8.80, "main_flow": Decimal("-80000000")},
            {"code": "002129", "name": "TCL中环", "price": Decimal("12.34"), "change_pct": 5.23, "change_amount": 0.61, "main_flow": Decimal("150000000")},
        ]
        data = DataService()
        data._source_label = "东方财富 实时"

        # Monkey-patch for fake data
        data.watchlist_quotes = lambda: fake_rows  # type: ignore[method-assign]
        data.portfolio_snapshot = lambda: {  # type: ignore[method-assign]
            "positions": fake_rows[:2],
            "total_market_value": Decimal("50000"),
            "total_unrealized_pnl": Decimal("1200"),
            "total_unrealized_pnl_pct": 2.4,
            "total_cost": Decimal("48800"),
        }
        return cls(data=data, agent=AgentBridge())
