"""自选股行情 + 当日主力资金流服务。

工具层（agent tools）和入口层（TUI / web routes）共用，消除
"批量报价 + 并发拉资金流 join" 的平行实现（此前 TUI DataService 与
ThemeService 各持一份同模式代码）。

- 报价走 ``adapter.get_quotes``（批量，底层腾讯源一次 HTTP 拉约 80 只）
- 资金流无批量 API，逐只拉（受 5 分钟节流缓存保护），
  ``FLOW_MAX_WORKERS`` 线程控并发
- 批量报价整体失败时，仍按 code 返回占位行（``quote_unavailable=True``），
  资金流照常 join——"拉新失败保留旧数据/部分可用"的既定语义
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from typing import NotRequired, TypedDict

from mommy_chaogu.market_data.adapter import MarketDataAdapter
from mommy_chaogu.market_data.types import Money, MoneyFlow

_log = logging.getLogger(__name__)

#: 资金流逐只拉取的并发上限（防打爆上游；节流缓存另有一层保护）
FLOW_MAX_WORKERS = 4


class WatchlistQuoteRow(TypedDict):
    """单只股票的报价 + 当日主力净流入 join 行。

    ``quote_unavailable`` 仅在批量报价整体失败时的占位行上出现。
    """

    code: str
    name: str
    price: Decimal | None
    change_pct: Decimal | None
    change_amount: Decimal | None
    main_flow: Money | None
    quote_unavailable: NotRequired[bool]


class WatchlistQuoteService:
    """批量报价 + 资金流 join 服务。

    用法::

        svc = WatchlistQuoteService(adapter)
        rows = svc.fetch(["600519", "000001"])
        label = svc.last_source_label  # 数据源标签（如"腾讯 实时"）
    """

    def __init__(self, adapter: MarketDataAdapter | None = None) -> None:
        self._adapter = adapter
        self.last_source_label: str = ""

    def fetch(self, codes: list[str]) -> list[WatchlistQuoteRow]:
        """拉取一批 code 的报价 + 当日主力净流入。

        Args:
            codes: 股票代码列表（调用方决定来源：自选股 / 主题成分 / 任意集合）

        Returns:
            与输入顺序一致的行列表；无 adapter 或空列表时返回空。
        """
        if self._adapter is None or not codes:
            self.last_source_label = ""
            return []
        adapter = self._adapter

        # ---- 批量报价（一次 HTTP 拉所有 code）----
        quote_error = False
        try:
            quotes = adapter.get_quotes(codes)
        except Exception as e:
            _log.debug("批量拉取报价失败: %s", e)
            quotes = []
            quote_error = True
        # duck-typed getattr 与既有 TUI 行为一致（FakeServices 可能传非 Quote 对象）
        quotes_by_code: dict[str, object] = {
            str(getattr(q, "code", "")): q for q in quotes
        }

        # ---- 资金流并发拉（无批量 API，5 分钟节流缓存）----
        flows_by_code: dict[str, Money | None] = {}
        with ThreadPoolExecutor(max_workers=FLOW_MAX_WORKERS) as pool:
            flow_results = list(pool.map(self._fetch_flow_safe, codes))
        for code, flow_val in zip(codes, flow_results, strict=True):
            if flow_val is not None:
                flows_by_code[code] = flow_val

        rows: list[WatchlistQuoteRow] = []
        for code in codes:
            q = quotes_by_code.get(code)
            if q is None:
                if quote_error:
                    rows.append(
                        WatchlistQuoteRow(
                            code=code,
                            name=code,
                            price=None,
                            change_pct=None,
                            change_amount=None,
                            main_flow=flows_by_code.get(code),
                            quote_unavailable=True,
                        )
                    )
                continue
            rows.append(
                WatchlistQuoteRow(
                    code=code,
                    name=str(getattr(q, "name", None) or code),
                    price=getattr(q, "price", None),
                    change_pct=getattr(q, "change_pct", None),
                    change_amount=getattr(q, "change", None),
                    main_flow=flows_by_code.get(code),
                )
            )

        self.last_source_label = (
            str(adapter.format_source_label())
            if hasattr(adapter, "format_source_label")
            else ""
        )
        return rows

    def _fetch_flow_safe(self, code: str) -> Money | None:
        """线程池内安全拉当日资金流，失败返回 None。"""
        try:
            flows: list[MoneyFlow] = self._adapter.get_today_money_flow(code)  # type: ignore[union-attr]
            if flows:
                return getattr(flows[-1], "main_net", None)
        except Exception as e:
            _log.debug("拉资金流 %s 失败: %s", code, e)
        return None
