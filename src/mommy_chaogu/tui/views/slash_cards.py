"""斜杠命令卡片构建器。

从 :class:`ChatView` 拆出的数据拉取 + 卡片渲染层：每个 builder 读服务、
组装 :class:`~textual.widgets.Static` 卡片并返回。线程调度（worker）、
挂载和错误提示由 ChatView 负责，本模块不触碰 widget 树。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from rich.markup import escape
from textual.widgets import Static

from mommy_chaogu.tui.widgets import cards

_log = logging.getLogger(__name__)


def _fetch_flow_safe(data_svc: Any, code: str) -> Any:
    """线程内安全拉当日主力净流（委托统一服务层；无 adapter 返回 None）。"""
    adapter = getattr(data_svc, "adapter", None)
    if adapter is None:
        return None
    from mommy_chaogu.services.watchlist_quote_service import WatchlistQuoteService

    return WatchlistQuoteService(adapter)._fetch_flow_safe(code)


class SlashCardFactory:
    """按需从服务容器拉数据并渲染斜杠命令卡片。"""

    def __init__(
        self,
        services: Callable[[], Any],
        theme: Callable[[], str],
    ) -> None:
        self._get_services = services
        self._get_theme = theme

    # ---------- 内部 ----------

    def _services(self) -> Any:
        return self._get_services()

    def _theme(self) -> str:
        return self._get_theme()

    def _call_service(self, fn: Callable[[], Any] | None) -> Any:
        """安全调用服务方法：不可用或失败都返回 None。"""
        if fn is None or not callable(fn):
            return None
        try:
            return fn()
        except Exception as e:
            _log.warning("TUI 服务调用失败: %s", e)
            return None

    def hint_static(self, text: str) -> Static:
        """服务未配置 / 数据缺失时的提示卡。"""
        return Static(f"[yellow]⚠[/] {escape(text)}", classes="hint-card")

    # ---------- 各命令的卡片 builder ----------

    def today_card(self) -> Static | None:
        svc = self._services()
        indexes = self._call_service(getattr(svc, "indexes", None)) or []
        data_svc = getattr(svc, "data", None)
        rows = data_svc.watchlist_quotes() if data_svc is not None else []
        up = sum(1 for r in rows if (r.get("change_pct") or 0) > 0)
        down = sum(1 for r in rows if (r.get("change_pct") or 0) < 0)
        signals = self._call_service(getattr(svc, "signals_recent", None)) or []
        pending = 0
        memory_db = getattr(svc, "memory_db", None)
        if memory_db and callable(memory_db.get("predictions")):
            stats = self._call_service(memory_db["predictions"])
            if stats:
                pending = int(stats.get("pending", 0) or 0)
        return cards.overview_card(
            indexes, len(rows), up, down, len(signals), pending, self._theme()
        )

    def watch_card(self) -> Static | None:
        svc = self._services()
        data_svc = getattr(svc, "data", None)
        rows = data_svc.watchlist_quotes() if data_svc is not None else []
        return cards.watch_card(rows, self._theme())

    def us_market_card(self) -> Static | None:
        """美股大盘卡：三大指数 + VIX + 10Y 美债利率。"""
        svc = self._services()
        data_svc = getattr(svc, "data", None)
        adapter = getattr(data_svc, "adapter", None) if data_svc is not None else None
        if adapter is None:
            return self.hint_static("行情服务未配置")
        from mommy_chaogu.services.us_market_service import fetch_us_market_brief

        items = fetch_us_market_brief(adapter)
        if not items:
            return self.hint_static("美股行情源暂时不可用")
        return cards.us_market_card(items, self._theme())

    def portfolio_card(self) -> Static | None:
        svc = self._services()
        data_svc = getattr(svc, "data", None)
        if data_svc is None:
            return self.hint_static("持仓服务未配置")
        return cards.portfolio_card(data_svc.portfolio_snapshot(), self._theme())

    def predictions_card(self) -> Static | None:
        svc = self._services()
        memory_db = getattr(svc, "memory_db", None)
        if not memory_db:
            return self.hint_static("记忆系统未配置")
        stats = self._call_service(memory_db.get("predictions"))
        recent = self._call_service(memory_db.get("predictions_recent")) or []
        return cards.predictions_card(stats, recent, self._theme())

    def signals_card(self) -> Static | None:
        svc = self._services()
        fn = getattr(svc, "signals_recent", None)
        if fn is None:
            return self.hint_static("信号服务未配置")
        signals = self._call_service(fn) or []
        return cards.signals_card(signals, self._theme())

    def memory_card(self) -> Static | None:
        svc = self._services()
        memory_db = getattr(svc, "memory_db", None)
        if not memory_db:
            return self.hint_static("记忆系统未配置")
        return cards.memory_card(memory_db, self._theme())

    def status_card(self) -> Static:
        """/status 卡（无 IO，同步组装）。"""
        svc = self._services()
        agent = getattr(svc, "agent", None)
        provider = agent.provider_name() if agent is not None else None
        model = agent.model_name() if agent is not None else None
        ai_label = f"AI🟢 {provider}" if provider else "AI⚪ 未配置"
        data_svc = getattr(svc, "data", None)
        source = data_svc.source_label() if data_svc is not None else ""
        counters = getattr(getattr(data_svc, "adapter", None), "stats_counters", None)
        from mommy_chaogu.db_paths import AGENT_DB, MARKET_DB, PORTFOLIO_DB, REFERENCE_DB

        paths = {
            "market": str(MARKET_DB),
            "portfolio": str(PORTFOLIO_DB),
            "agent": str(AGENT_DB),
            "reference": str(REFERENCE_DB),
        }
        return cards.status_card(ai_label, model, source, counters, paths, self._theme())

    def quote_card(self, code: str) -> Static | None:
        """报价卡（/quote 与 6 位代码快捷入口共用）。"""
        svc = self._services()
        data_svc = getattr(svc, "data", None)
        adapter = getattr(data_svc, "adapter", None) if data_svc is not None else None
        if adapter is None:
            return self.hint_static("行情服务未配置")
        quote = adapter.get_quote(code)
        if quote is None:
            return self.hint_static(f"未找到 {code} 的行情")
        data: dict[str, Any] = {
            "code": code,
            "name": getattr(quote, "name", code),
            "price": getattr(quote, "price", None),
            "change_pct": getattr(quote, "change_pct", None),
            "open": getattr(quote, "open", None),
            "high": getattr(quote, "high", None),
            "low": getattr(quote, "low", None),
            "prev_close": getattr(quote, "prev_close", None),
            "volume": getattr(quote, "volume", None),
            "turnover": getattr(getattr(quote, "turnover", None), "amount", None),
            "turnover_rate": getattr(quote, "turnover_rate", None),
            "volume_ratio": getattr(quote, "volume_ratio", None),
        }
        if data_svc is not None:
            flow = _fetch_flow_safe(data_svc, code)
            if flow is not None:
                data["main_flow"] = flow
        return cards.quote_card(data, self._theme())

    def flows_card(self, code: str) -> Static | None:
        """个股资金流卡（/flows <代码>）。"""
        svc = self._services()
        flows_service = getattr(svc, "flows", None)
        if flows_service is None:
            return self.hint_static("资金流服务未配置")
        info = flows_service.show(code, days=30)
        return cards.flows_command_card(code, info, self._theme())

    def watchlist_flows_card(self) -> Static | None:
        """无参数 /flows：自选股主力净流入榜。"""
        svc = self._services()
        data_svc = getattr(svc, "data", None)
        rows = data_svc.watchlist_quotes() if data_svc is not None else []
        with_flow = [r for r in rows if r.get("main_flow") is not None]
        with_flow.sort(key=lambda r: abs(float(r["main_flow"])), reverse=True)
        items = [
            {"code": r.get("code", ""), "name": r.get("name", ""), "main_net": r["main_flow"]}
            for r in with_flow[:10]
        ]
        return cards.flow_multi_card(items, self._theme())
