"""Services 容器装配（§5.1）。

App 启动时组装一次 Services 容器，widget 通过 self.app.services 访问。
测试时注入 FakeServices。
"""

from __future__ import annotations

import contextlib
import logging
import threading
from collections.abc import Callable
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
        quote_error = False
        try:
            quotes = self.adapter.get_quotes(codes)
        except Exception as e:
            _log.debug("批量拉取报价失败: %s", e)
            quotes = []
            quote_error = True
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
                if quote_error:
                    rows.append(
                        {
                            "code": code,
                            "name": code,
                            "price": None,
                            "change_pct": None,
                            "change_amount": None,
                            "main_flow": flows_by_code.get(code),
                            "quote_unavailable": True,
                        }
                    )
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
                except Exception as e:
                    _log.debug("持仓实时报价拉取失败: %s", e)
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
    _memory: Any = None

    def route(self, text: str) -> Any:
        """尝试路由匹配。返回 RouteResult。"""
        if self._router is None:
            return None
        return self._router.route(text)

    def execute_workflow(
        self,
        route_result: Any,
        text: str,
        on_step_start: Any = None,
        on_step_done: Any = None,
        is_cancelled: Any = None,
    ) -> Any:
        if self._router is None:
            return None
        return self._router.execute_route(
            route_result,
            text,
            on_step_start=on_step_start,
            on_step_done=on_step_done,
            is_cancelled=is_cancelled,
        )

    def has_agent(self) -> bool:
        return self._agent is not None

    def provider_name(self) -> str | None:
        """agent 的 provider 名（TopBar AI🟢 状态用）；无 agent 返回 None。"""
        if self._agent is None:
            return None
        return getattr(self._agent, "_provider", None)

    def model_name(self) -> str | None:
        """agent 当前模型名（/status 卡用）；无 agent 返回 None。"""
        if self._agent is None:
            return None
        return getattr(self._agent, "_model", None)

    def watch_background(self, on_done: Callable[[], None]) -> bool:
        """挂上后台记忆线程的 watcher：全部结束后回调 on_done（记忆回执）。

        返回是否确实挂上了 watcher（无 agent / 无后台线程时返回 False，
        调用方不显示回执）。on_done 在 watcher 线程执行，UI 更新需
        call_from_thread。
        """
        agent = self._agent
        threads = list(getattr(agent, "_bg_threads", []) or []) if agent is not None else []
        if not threads:
            return False

        def _watch() -> None:
            for t in threads:
                t.join()
            on_done()

        threading.Thread(target=_watch, daemon=True).start()
        return True

    def chat(
        self,
        message: str,
        history: list[dict[str, str]] | None = None,
        on_tool_call: Any = None,
        on_tool_result: Any = None,
        on_chunk: Any = None,
        cancel_event: Any = None,
        usage_out: Any = None,
        on_status: Any = None,
    ) -> Any:
        if self._agent is None:
            return None
        kwargs = {
            "history": history,
            "on_tool_call": on_tool_call,
            "on_tool_result": on_tool_result,
            "on_chunk": on_chunk,
            "cancel_event": cancel_event,
            "usage_out": usage_out,
            "on_status": on_status,
        }
        if self._memory is not None:
            kwargs["memory"] = self._memory
        return self._agent.chat(message, **kwargs)


@dataclass
class Services:
    """服务容器，所有 widget 通过 self.app.services 访问。"""

    data: DataService = field(default_factory=DataService)
    agent: AgentBridge = field(default_factory=AgentBridge)
    flows: Any = None  # FlowService，无 MARKET_DB 退化为 None
    memory_db: Any = None  # 记忆统计可调用字典（见 _make_memory_stats）
    # 对话内卡片数据源（§1.2②③）：全部为无参 callable，失败返回 None 表示不可用
    indexes: Callable[[], list[dict[str, Any]]] | None = None  # 大盘指数快照
    signals_recent: Callable[[], list[dict[str, Any]]] | None = None  # 近期信号
    stock_candidates: Callable[[], list[tuple[str, str]]] | None = None  # @ 联想（code, name）

    @classmethod
    def bootstrap(cls) -> Services:
        """生产环境装配：从项目内部构建 adapter + agent。"""
        load_dotenv()
        from mommy_chaogu.cache import CachedMarketDataAdapter, CacheStore
        from mommy_chaogu.db_paths import AGENT_DB, MARKET_DB, PORTFOLIO_DB
        from mommy_chaogu.market_data import create_adapter_chain
        from mommy_chaogu.portfolio.store import PortfolioStore
        from mommy_chaogu.watchlist.store import WatchlistStore

        base = create_adapter_chain()
        adapter = CachedMarketDataAdapter(base, CacheStore(MARKET_DB))
        data_svc = DataService(
            adapter=adapter,
            watchlist_store=WatchlistStore(PORTFOLIO_DB),
            portfolio_store=PortfolioStore(PORTFOLIO_DB),
        )

        agent_bridge = AgentBridge()

        # 尝试初始化 agent。
        # 探测链与实际读 key 链必须一致（L4）：detect_provider 找到哪个
        # provider 有 key，就把它显式传给 AgentService——不能依赖
        # AGENT_PROVIDER 默认值，否则「只配了 OPENAI_API_KEY」时探测通过、
        # 初始化却因读 DEEPSEEK_API_KEY 失败，agent 静默不可用。
        from mommy_chaogu.agent import llm as llm_provider

        detected = llm_provider.detect_provider()
        if detected is not None:
            try:
                from mommy_chaogu.agent.episodic_memory import EpisodicMemory
                from mommy_chaogu.agent.memory import ConversationMemory
                from mommy_chaogu.agent.prediction_tracker import PredictionTracker
                from mommy_chaogu.agent.semantic_memory import SemanticMemory
                from mommy_chaogu.agent.service import AgentService
                from mommy_chaogu.agent.tools import ToolContext, ToolRegistry

                ctx = ToolContext(
                    adapter=adapter,
                    watchlist_store=WatchlistStore(PORTFOLIO_DB),
                    portfolio_store=PortfolioStore(PORTFOLIO_DB),
                    agent_db=AGENT_DB,
                    market_db=MARKET_DB,
                    portfolio_db=PORTFOLIO_DB,
                )
                agent_bridge._agent = AgentService(
                    ctx,
                    provider=detected,
                    episodic=EpisodicMemory(AGENT_DB),
                    tracker=PredictionTracker(AGENT_DB),
                    semantic=SemanticMemory(AGENT_DB),
                )
                agent_bridge._memory = ConversationMemory(AGENT_DB)
            except Exception as e:
                _log.warning("AgentService 初始化失败: %s", e)
        else:
            _log.info("未检测到任何 LLM API key，agent 不可用（聊天模式降级）")

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
                agent_db=AGENT_DB,
                market_db=MARKET_DB,
                portfolio_db=PORTFOLIO_DB,
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

        # 记忆统计可调用（/memory /predictions slash 命令用，无 api_key 也能查统计）
        memory_stats = _make_memory_stats(AGENT_DB)

        # 对话内卡片数据源（§1.2②③）：指数快照 / 近期信号 / @ 股票联想
        indexes_fn = _make_index_fetcher()
        signals_fn = _make_signals_fetcher(MARKET_DB)
        stocks_fn = _make_stock_candidates(
            data_svc.watchlist_store,
            getattr(adapter, "store", None),
        )

        return cls(
            data=data_svc,
            agent=agent_bridge,
            flows=flows_service,
            memory_db=memory_stats,
            indexes=indexes_fn,
            signals_recent=signals_fn,
            stock_candidates=stocks_fn,
        )


def _make_memory_stats(agent_db: Any) -> dict[str, Any] | None:
    """构造记忆统计 dict（含各 summary()/stats() 调用器）。

    返回 None 表示记忆系统不可用（db 初始化失败）。
    键：episodic / predictions / semantic / predictions_recent / tokens / cost，
    每项为 callable；单项不可用时缺键，卡片渲染方按键缺失降级。
    """
    try:
        from mommy_chaogu.agent.episodic_memory import EpisodicMemory
        from mommy_chaogu.agent.prediction_tracker import PredictionTracker
        from mommy_chaogu.agent.semantic_memory import SemanticMemory

        tracker = PredictionTracker(agent_db)
        stats: dict[str, Any] = {
            "episodic": EpisodicMemory(agent_db).summary,
            "predictions": tracker.stats,
            "predictions_recent": lambda: tracker.all(limit=8),
            "semantic": SemanticMemory(agent_db).summary,
        }
        try:
            from mommy_chaogu.agent.token_tracker import TokenTracker

            token_tracker = TokenTracker(agent_db)
            stats["tokens"] = token_tracker.totals
            stats["cost"] = token_tracker.cost_estimate
        except Exception as e:
            _log.warning("TokenTracker 初始化失败，/memory 不显示 token 用量: %s", e)
        return stats
    except Exception as e:
        _log.warning("记忆统计初始化失败: %s", e)
        return None


def _make_index_fetcher() -> Callable[[], list[dict[str, Any]]] | None:
    """大盘指数快照（TopBar + /today + 欢迎卡用）；失败返回 None 由调用方降级。"""

    def _fetch() -> list[dict[str, Any]]:
        from mommy_chaogu.market_data.rankings import fetch_indexes

        return [
            {"name": iq.name, "price": iq.price, "change_pct": float(iq.change_pct)}
            for iq in fetch_indexes()
        ]

    return _fetch


def _make_signals_fetcher(market_db: Any) -> Callable[[], list[dict[str, Any]]] | None:
    """近期信号（/signals + /today 用）；SignalStore 初始化失败返回 None。"""
    try:
        from mommy_chaogu.signals.store import SignalStore

        store = SignalStore(market_db)
    except Exception as e:
        _log.warning("SignalStore 初始化失败，/signals 不可用: %s", e)
        return None

    def _fetch() -> list[dict[str, Any]]:
        return store.list(limit=8)

    return _fetch


def _make_stock_candidates(
    watchlist_store: Any,
    cache_store: Any,
) -> Callable[[], list[tuple[str, str]]]:
    """@ 股票联想数据源：自选股（优先）+ 半导体库 + quote_cache 名称，按 code 去重。"""

    def _fetch() -> list[tuple[str, str]]:
        # 名称表：quote_cache 里的历史报价名称（自选股条目本身不存名称）
        names: dict[str, str] = {}
        if cache_store is not None:
            with contextlib.suppress(Exception):
                for entry in cache_store.get_all_quote_entries():
                    name = getattr(getattr(entry, "quote", None), "name", "") or ""
                    if name and entry.code not in names:
                        names[entry.code] = name

        result: list[tuple[str, str]] = []
        seen: set[str] = set()

        def _add(code: str, name: str) -> None:
            if code and code not in seen:
                seen.add(code)
                result.append((code, name))

        # 1. 自选股优先
        if watchlist_store is not None:
            with contextlib.suppress(Exception):
                for code in watchlist_store.get_all_codes():
                    _add(code, names.get(code, ""))
        # 2. 半导体产业链参考库
        with contextlib.suppress(Exception):
            from mommy_chaogu.db_paths import REFERENCE_DB
            from mommy_chaogu.semicon.store import SemiconStore

            for stock in SemiconStore(REFERENCE_DB).list_all():
                _add(stock.code, stock.name)
        # 3. quote_cache 其余（查过行情的股票）
        for code, name in names.items():
            _add(code, name)
        return result

    return _fetch


@dataclass
class FakeServices:
    """测试用假数据服务。"""

    data: DataService = field(default_factory=DataService)
    agent: AgentBridge = field(default_factory=AgentBridge)
    flows: Any = None
    memory_db: Any = None
    indexes: Callable[[], list[dict[str, Any]]] | None = None
    signals_recent: Callable[[], list[dict[str, Any]]] | None = None
    stock_candidates: Callable[[], list[tuple[str, str]]] | None = None

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
            "predictions_recent": lambda: [
                {
                    "id": 1,
                    "code": "688981",
                    "name": "中芯国际",
                    "prediction": "放量突破 20 日线后看高一线",
                    "direction": "up",
                    "timeframe": "5d",
                    "status": "pending",
                    "verify_after": "2099-01-01T00:00:00+00:00",
                },
                {
                    "id": 2,
                    "code": "600519",
                    "name": "贵州茅台",
                    "prediction": "跌破 1700 后走弱",
                    "direction": "down",
                    "timeframe": "3d",
                    "status": "hit",
                    "verify_after": "2026-07-20T00:00:00+00:00",
                },
            ],
            "semantic": lambda: {"total": 23, "active": 20},
            "tokens": lambda: {
                "prompt_tokens": 12000,
                "completion_tokens": 3000,
                "total_tokens": 15000,
                "calls": 8,
            },
            "cost": lambda: {"total_usd": 0.0123},
        }

        def fake_indexes() -> list[dict[str, Any]]:
            return [
                {"name": "上证指数", "price": Decimal("3847.51"), "change_pct": 0.6},
                {"name": "深证成指", "price": Decimal("12345.67"), "change_pct": 0.9},
                {"name": "创业板指", "price": Decimal("2345.67"), "change_pct": -0.3},
            ]

        def fake_signals() -> list[dict[str, Any]]:
            return [
                {
                    "timestamp": "2026-07-25 10:30:00",
                    "severity": "critical",
                    "code": "688981",
                    "name": "中芯国际",
                    "title": "主力资金大幅流入",
                },
                {
                    "timestamp": "2026-07-25 09:45:00",
                    "severity": "warning",
                    "code": "600519",
                    "name": "贵州茅台",
                    "title": "跌破 5 日线",
                },
            ]

        def fake_stocks() -> list[tuple[str, str]]:
            return [(str(r["code"]), str(r["name"])) for r in fake_rows]

        return cls(
            data=data,
            agent=AgentBridge(),
            flows=fake_flows,
            memory_db=fake_memory_db,
            indexes=fake_indexes,
            signals_recent=fake_signals,
            stock_candidates=fake_stocks,
        )
