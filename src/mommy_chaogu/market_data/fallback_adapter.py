"""FallbackAdapter: 多数据源按顺序 fallback 包装器。

设计：
- 接收 list[MarketDataAdapter]，按顺序尝试
- 主源失败（抛异常或返回 None）→ 下一个源
- 业务层不感知，妈妈无感透明加速

配合缓存层使用：
    CachedMarketDataAdapter(
        FallbackAdapter([EfinanceAdapter(), TencentAdapter()]),
        store
    )

注意：
- 不缓存 fallback 结果（避免缓存层 + fallback 层互相干扰）
- 每个方法独立 fallback（一个方法在主源失败不影响其他方法）
- 指标统计：primary_hits / fallback_hits / all_fail
"""

from __future__ import annotations

import contextlib
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mommy_chaogu.market_data.adapter import MarketDataAdapter

_log = logging.getLogger(__name__)


class FallbackAdapter:
    """多数据源 fallback 装饰器。

    用法：
        adapter = FallbackAdapter([EfinanceAdapter(), TencentAdapter()])
        quote = adapter.get_quote("600519")
        # 优先 EfinanceAdapter，失败时自动用 TencentAdapter
    """

    def __init__(
        self,
        adapters: list[MarketDataAdapter],
        name: str | None = None,
    ) -> None:
        if not adapters:
            raise ValueError("FallbackAdapter 需要至少一个 adapter")
        self.adapters = list(adapters)
        self.name = name or f"fallback({','.join(a.name for a in adapters)})"
        # 指标
        self._stats: dict[str, dict[str, int]] = {
            adapter.name: {"calls": 0, "ok": 0, "fail": 0} for adapter in self.adapters
        }
        self._stats["__total__"] = {
            "primary_hits": 0,
            "fallback_hits": 0,
            "all_fail": 0,
            "calls": 0,
        }

    def stats(self) -> dict[str, dict[str, int]]:
        return self._stats

    def _try_call(self, method_name: str, *args, **kwargs):
        """按顺序尝试每个 adapter 的 method_name。

        返回：第一个非 None 的结果；如果全部 None/异常 → 返回 None。
        """
        self._stats["__total__"]["calls"] += 1
        last_exc: Exception | None = None
        for idx, adapter in enumerate(self.adapters):
            self._stats[adapter.name]["calls"] += 1
            method = getattr(adapter, method_name)
            try:
                result = method(*args, **kwargs)
            except Exception as e:
                self._stats[adapter.name]["fail"] += 1
                _log.warning(
                    "fallback: %s.%s(%s) raised %s: %s",
                    adapter.name,
                    method_name,
                    args,
                    type(e).__name__,
                    e,
                )
                last_exc = e
                continue
            if result is None or result == [] or result == {}:
                # 返回空也算失败（不算 OK）
                self._stats[adapter.name]["fail"] += 1
                continue
            self._stats[adapter.name]["ok"] += 1
            if idx == 0:
                self._stats["__total__"]["primary_hits"] += 1
            else:
                self._stats["__total__"]["fallback_hits"] += 1
                _log.info(
                    "fallback: %s used (primary %s.%s failed)",
                    adapter.name,
                    self.adapters[0].name,
                    method_name,
                )
            return result
        self._stats["__total__"]["all_fail"] += 1
        if last_exc is not None:
            _log.debug(
                "fallback: all %d adapters failed for %s(%s), last exc: %s",
                len(self.adapters),
                method_name,
                args,
                last_exc,
            )
        return None

    # ---------- MarketDataAdapter 接口实现 ----------

    def get_quote(self, code: str):
        return self._try_call("get_quote", code)

    def get_quotes(self, codes: list[str]):
        result = self._try_call("get_quotes", codes)
        return result if result is not None else []

    def list_market_quotes(self):
        result = self._try_call("list_market_quotes")
        return result if result is not None else []

    def get_order_book(self, code: str):
        return self._try_call("get_order_book", code)

    def get_bars(self, code, interval=None, adjustment=None, **kwargs):
        """K 线：fallback 链中任何一个能返回就用。"""
        if interval is not None and adjustment is not None:
            return self._try_call(
                "get_bars", code, interval=interval, adjustment=adjustment, **kwargs
            )
        return self._try_call("get_bars", code, **kwargs)

    def get_ticks(self, code, limit=None):
        return self._try_call("get_ticks", code, limit=limit)

    def get_today_money_flow(self, code):
        return self._try_call("get_today_money_flow", code)

    def get_history_money_flow(self, code, days=30):
        return self._try_call("get_history_money_flow", code, days=days)

    def get_belonging_boards(self, code):
        return self._try_call("get_belonging_boards", code)

    def health_check(self) -> bool:
        """任何一个 adapter 健康就算健康。"""
        for adapter in self.adapters:
            with contextlib.suppress(Exception):
                if adapter.health_check():
                    return True
        return False
