"""Services 容器装配（§5.1）。

App 启动时组装一次 Services 容器，widget 通过 self.app.services 访问。
测试时注入 FakeServices。
"""

from __future__ import annotations

import contextlib
import logging
import os
from concurrent.futures import ThreadPoolExecutor
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
        """批量获取自选股报价 + 主力资金流。

        报价走 adapter.get_quotes（批量，底层腾讯一次 HTTP 拉 80 只）；
        资金流无批量 API，但有 5 分钟节流缓存，用 4 线程并发拉。
        """
        if self.adapter is None:
            return []
        codes: list[str] = []
        if self.watchlist_store:
            with contextlib.suppress(Exception):
                codes = self.watchlist_store.get_all_codes()
        if not codes:
            return []

        # 批量报价（一次 HTTP 拉所有 code）
        try:
            quotes = self.adapter.get_quotes(codes)
        except Exception as e:
            _log.debug("批量拉取报价失败: %s", e)
            quotes = []
        quotes_by_code: dict[str, Any] = {getattr(q, "code", ""): q for q in quotes}

        # 资金流并发拉（无批量 API，5 分钟节流缓存，max_workers=4 控并发）
        flows_by_code: dict[str, Any] = {}
        with ThreadPoolExecutor(max_workers=4) as pool:
            flow_results = list(pool.map(self._fetch_flow_safe, codes))
        for code, flow_val in zip(codes, flow_results, strict=True):
            if flow_val is not None:
                flows_by_code[code] = flow_val

        rows: list[dict[str, Any]] = []
        for code in codes:
            q = quotes_by_code.get(code)
            if q is None:
                continue
            rows.append(
                {
                    "code": code,
                    "name": getattr(q, "name", code),
                    "price": q.price,
                    "change_pct": getattr(q, "change_pct", None),
                    "change_amount": getattr(q, "change", None),
                    "main_flow": flows_by_code.get(code),
                }
            )

        self._source_label = (
            self.adapter.format_source_label()
            if hasattr(self.adapter, "format_source_label")
            else ""
        )
        return rows

    def _fetch_flow_safe(self, code: str) -> Any:
        """线程池内安全拉资金流，失败返回 None。"""
        try:
            flows = self.adapter.get_today_money_flow(code)
            if flows:
                return getattr(flows[-1], "main_net", None)
        except Exception as e:
            _log.debug("拉资金流 %s 失败: %s", code, e)
        return None

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
            if self.adapter and codes:
                # 批量拉报价（一次 HTTP）
                try:
                    for q in self.adapter.get_quotes(codes):
                        prices[q.code] = q.price
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

    def execute_workflow(
        self, route_result: Any, text: str, on_step_start: Any = None, on_step_done: Any = None
    ) -> Any:
        if self._router is None:
            return None
        return self._router.execute_route(
            route_result, text, on_step_start=on_step_start, on_step_done=on_step_done
        )

    def has_agent(self) -> bool:
        return self._agent is not None

    def chat(
        self,
        message: str,
        history: list[dict[str, str]] | None = None,
        on_tool_call: Any = None,
        on_tool_result: Any = None,
        on_chunk: Any = None,
        cancel_event: Any = None,
        usage_out: Any = None,
    ) -> Any:
        if self._agent is None:
            return None
        return self._agent.chat(
            message,
            history=history,
            on_tool_call=on_tool_call,
            on_tool_result=on_tool_result,
            on_chunk=on_chunk,
            cancel_event=cancel_event,
            usage_out=usage_out,
        )


@dataclass
class Services:
    """服务容器，所有 widget 通过 self.app.services 访问。"""

    data: DataService = field(default_factory=DataService)
    agent: AgentBridge = field(default_factory=AgentBridge)
    flows: Any = None  # FlowService，无 MARKET_DB 退化为 None
    memory_db: Any = None  # 记忆统计可调用字典（见 _make_memory_stats）

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
            from mommy_chaogu.workflow.definitions import get_default_registry
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
            agent_bridge._router = NLRouter(get_default_registry(), executor=executor)
        except Exception as e:
            _log.warning("NLRouter 初始化失败: %s", e)

        # FlowService（/flows slash 命令用）
        flows_service = None
        try:
            from mommy_chaogu.flows.service import FlowService

            flows_service = FlowService.from_default(MARKET_DB)
        except Exception as e:
            _log.warning("FlowService 初始化失败: %s", e)

        # 记忆统计可调用（/memory slash 命令用，无 api_key 也能查统计）
        memory_stats = _make_memory_stats(AGENT_DB)

        return cls(data=data_svc, agent=agent_bridge, flows=flows_service, memory_db=memory_stats)


def _make_memory_stats(agent_db: Any) -> dict[str, Any] | None:
    """构造记忆统计 dict（含各 summary()/stats() 调用器）。

    返回 None 表示记忆系统不可用（db 初始化失败）。
    """
    try:
        from mommy_chaogu.agent.episodic_memory import EpisodicMemory
        from mommy_chaogu.agent.prediction_tracker import PredictionTracker
        from mommy_chaogu.agent.semantic_memory import SemanticMemory

        return {
            "episodic": EpisodicMemory(agent_db).summary,
            "predictions": PredictionTracker(agent_db).stats,
            "semantic": SemanticMemory(agent_db).summary,
        }
    except Exception as e:
        _log.warning("记忆统计初始化失败: %s", e)
        return None


@dataclass
class FakeServices:
    """测试用假数据服务。"""

    data: DataService = field(default_factory=DataService)
    agent: AgentBridge = field(default_factory=AgentBridge)
    flows: Any = None
    memory_db: Any = None

    @classmethod
    def create(cls) -> FakeServices:
        """创建带假数据的 Services。"""
        fake_rows = [
            {
                "code": "688981",
                "name": "中芯国际",
                "price": Decimal("87.45"),
                "change_pct": 2.31,
                "change_amount": 1.98,
                "main_flow": Decimal("230000000"),
            },
            {
                "code": "600519",
                "name": "贵州茅台",
                "price": Decimal("1680.00"),
                "change_pct": -0.52,
                "change_amount": -8.80,
                "main_flow": Decimal("-80000000"),
            },
            {
                "code": "002129",
                "name": "TCL中环",
                "price": Decimal("12.34"),
                "change_pct": 5.23,
                "change_amount": 0.61,
                "main_flow": Decimal("150000000"),
            },
        ]
        data = DataService()
        data._source_label = "东方财富 实时"

        # Monkey-patch for fake data
        data.watchlist_quotes = lambda: fake_rows  # type: ignore[method-assign]
        data.portfolio_snapshot = (  # type: ignore[method-assign]
            lambda: {
                "positions": fake_rows[:2],
                "total_market_value": Decimal("50000"),
                "total_unrealized_pnl": Decimal("1200"),
                "total_unrealized_pnl_pct": 2.4,
                "total_cost": Decimal("48800"),
            }
        )

        # Fake flows + memory（供 /flows /memory slash 命令测试）
        from types import SimpleNamespace

        fake_flows = SimpleNamespace(
            show=lambda code, days=30: {
                "code": code,
                "today": SimpleNamespace(
                    name="测试股",
                    main_net=Decimal("100000000"),
                    super_large_net=Decimal("60000000"),
                    large_net=Decimal("40000000"),
                    medium_net=Decimal("-20000000"),
                    small_net=Decimal("-80000000"),
                    main_net_ratio=Decimal("12.5"),
                    sample_count=1,
                    period="today",
                    big_money_net=Decimal("100000000"),
                ),
                "history": None,
                "history_days_cached": 0,
            }
        )
        fake_memory_db = {
            "episodic": lambda: {"total": 15, "by_type": {"signal": 8, "news": 7}},
            "predictions": lambda: {
                "total": 10,
                "hit": 4,
                "missed": 1,
                "pending": 5,
                "hit_rate": 0.8,
            },
            "semantic": lambda: {"total": 23, "active": 20},
        }

        return cls(data=data, agent=AgentBridge(), flows=fake_flows, memory_db=fake_memory_db)
