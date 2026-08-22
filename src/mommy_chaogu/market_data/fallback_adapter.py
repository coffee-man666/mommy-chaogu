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
- 指标统计口径：
  - primary_hits：主源一次调用即满足全部请求（批量接口要求全覆盖）；
  - partial_hits：主源有贡献但未全覆盖，缺口由下游源补齐；
  - fallback_hits：主源完全无贡献，结果来自下游源；
  - all_fail：所有源都无贡献。
  partial_hits 偏高正是"主源看似正常实则缺口"的信号，监控上应与
  primary_hits 分开看。
"""

from __future__ import annotations

import contextlib
import logging
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from mommy_chaogu.market_data.adapter import MarketDataAdapter

from mommy_chaogu.market_data.types import (
    AdjustmentType,
    Bar,
    BarInterval,
    Board,
    MoneyFlow,
    OrderBook,
    Quote,
    Tick,
)

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
            "partial_hits": 0,
            "fallback_hits": 0,
            "all_fail": 0,
            "calls": 0,
        }

    def stats(self) -> dict[str, dict[str, int]]:
        return self._stats

    def _try_call(self, method_name: str, *args: Any, **kwargs: Any) -> Any:
        """按顺序尝试每个 adapter 的 method_name。

        返回：第一个非 None 的结果；如果全部 None/异常 → 返回 None。
        """
        self._stats["__total__"]["calls"] += 1
        last_exc: Exception | None = None
        for idx, adapter in enumerate(self.adapters):
            self._stats[adapter.name]["calls"] += 1
            # adapter 可能未实现该方法：缺方法视为该源失败，继续向下，
            # 不得让 AttributeError 穿透 fallback 链抛给调用方。
            method = getattr(adapter, method_name, None)
            if method is None:
                self._stats[adapter.name]["fail"] += 1
                continue
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

    def _try_call_batch(self, method_name: str, codes: list[str]) -> list[Quote] | None:
        """批量接口：按 code 缺口在 adapter 链上续拉合并。

        单个 adapter 可能只覆盖部分市场（如 Massive 只认美股代码），
        返回非空不等于全部请求都成功——继续把缺失的 codes 交给下一个
        源，直到补齐或链尽。全部源都没贡献任何结果才返回 None（保持
        _try_call 的失败语义，缓存层据此保留旧数据）。
        """
        requested = list(dict.fromkeys(codes))
        remaining = list(requested)
        merged: dict[str, Quote] = {}
        any_ok = False
        for idx, adapter in enumerate(self.adapters):
            if not remaining:
                break
            self._stats[adapter.name]["calls"] += 1
            # 与 _try_call 同理：缺方法视为该源失败，继续沿链向下。
            method = getattr(adapter, method_name, None)
            if method is None:
                self._stats[adapter.name]["fail"] += 1
                continue
            try:
                result = method(remaining)
            except Exception as e:
                self._stats[adapter.name]["fail"] += 1
                _log.warning(
                    "fallback: %s.%s(%s) raised %s: %s",
                    adapter.name,
                    method_name,
                    remaining,
                    type(e).__name__,
                    e,
                )
                continue
            if not result:
                self._stats[adapter.name]["fail"] += 1
                continue
            self._stats[adapter.name]["ok"] += 1
            any_ok = True
            got = set()
            for item in result:
                merged[item.code] = item
                got.add(item.code)
            covered = [c for c in remaining if c in got]
            remaining = [c for c in remaining if c not in got]
            if idx == 0:
                # 主源全覆盖才算 primary_hits；部分覆盖单独计 partial_hits，
                # 避免"主源命中率"掩盖批量缺口（F1 想暴露的正是这类信号）。
                if not remaining:
                    self._stats["__total__"]["primary_hits"] += 1
                else:
                    self._stats["__total__"]["partial_hits"] += 1
            else:
                self._stats["__total__"]["fallback_hits"] += 1
                _log.info(
                    "fallback: %s used for %d/%d codes (primary %s.%s partial)",
                    adapter.name,
                    len(covered),
                    len(covered) + len(remaining),
                    self.adapters[0].name,
                    method_name,
                )
        if not any_ok:
            self._stats["__total__"]["all_fail"] += 1
            return None
        # 保持调用方的 code 顺序
        return [merged[c] for c in requested if c in merged]

    # ---------- MarketDataAdapter 接口实现 ----------

    def get_quote(self, code: str) -> Quote | None:
        return cast("Quote | None", self._try_call("get_quote", code))

    def get_quotes(self, codes: list[str]) -> list[Quote]:
        result = self._try_call_batch("get_quotes", codes)
        return result if result is not None else []

    def list_market_quotes(self) -> list[Quote]:
        result = cast("list[Quote] | None", self._try_call("list_market_quotes"))
        return result if result is not None else []

    def get_order_book(self, code: str) -> OrderBook | None:
        return cast("OrderBook | None", self._try_call("get_order_book", code))

    def get_bars(
        self,
        code: str,
        interval: BarInterval | None = None,
        adjustment: AdjustmentType | None = None,
        **kwargs: Any,
    ) -> list[Bar]:
        """K 线：fallback 链中任何一个能返回就用。"""
        if interval is not None and adjustment is not None:
            return cast(
                "list[Bar]",
                self._try_call(
                    "get_bars", code, interval=interval, adjustment=adjustment, **kwargs
                ),
            )
        return cast("list[Bar]", self._try_call("get_bars", code, **kwargs))

    def get_ticks(self, code: str, limit: int | None = None) -> list[Tick]:
        return cast("list[Tick]", self._try_call("get_ticks", code, limit=limit))

    def get_today_money_flow(self, code: str) -> list[MoneyFlow]:
        return cast("list[MoneyFlow]", self._try_call("get_today_money_flow", code))

    def get_history_money_flow(self, code: str, days: int = 30) -> list[MoneyFlow]:
        return cast("list[MoneyFlow]", self._try_call("get_history_money_flow", code, days=days))

    def get_belonging_boards(self, code: str) -> list[Board]:
        return cast("list[Board]", self._try_call("get_belonging_boards", code))

    def health_check(self) -> bool:
        """任何一个 adapter 健康就算健康。"""
        for adapter in self.adapters:
            with contextlib.suppress(Exception):
                if adapter.health_check():
                    return True
        return False
