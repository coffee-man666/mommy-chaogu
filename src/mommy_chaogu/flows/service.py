"""FlowService：资金流拉新 + 排行 + 查询。

API：
- pull_today(pool, force): 拉某池所有 code 的当日资金流 → 缓存
- pull_history(pool, days, force): 拉历史 N 天资金流 → 缓存
- top_today(pool, n, by): 当日按某指标排前 N（inflow / outflow）
- top_history(pool, days, n, by): 历史 N 天按累计某指标排前 N
- show(code, days): 查单只股票的资金流汇总
- stats(pool): 缓存覆盖度统计
- clear(pool): 清空某池的缓存

设计：
- 拉新走 CachedMarketDataAdapter（节流 + 缓存 + fallback 自动生效）
- force=True 时重置节流，让每个 code 真正打到接口
- 排行时直接从 CacheStore 读（不重复拉接口）
- 内部汇总用 dataclass，外部不暴露 ORM
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from mommy_chaogu.cache import CacheStore
from mommy_chaogu.cache.adapter import CachedMarketDataAdapter
from mommy_chaogu.flows.pool import PoolSource
from mommy_chaogu.market_data.types import Money, MoneyFlow

_log = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(UTC)


# ---------- 结果 dataclass ----------


@dataclass(frozen=True, slots=True)
class FlowSummary:
    """一只股票在某时段的资金流汇总。"""

    code: str
    name: str
    main_net: Decimal  # 主力净流入（元）
    super_large_net: Decimal  # 超大单净流入
    large_net: Decimal  # 大单净流入
    medium_net: Decimal  # 中单净流入
    small_net: Decimal  # 小单净流入
    main_net_ratio: Decimal | None  # 主力净流入占比（%）
    sample_count: int = 1  # 聚合了几条记录
    period: str = ""  # "today" / "history:2026-06-01~2026-06-29"

    def big_money_net(self) -> Decimal:
        """大资金（超大单+大单）净流入。"""
        return self.super_large_net + self.large_net


@dataclass(slots=True)
class PullResult:
    """一次批量拉新的结果（可变：调用过程中累计计数）。"""

    pool_name: str
    target: str  # "today" / "history:30d"
    ok: int = 0
    failed: int = 0
    failed_codes: list[str] = field(default_factory=list)
    elapsed_seconds: float = 0.0

    @property
    def total(self) -> int:
        return self.ok + self.failed


# ---------- Service ----------


class FlowService:
    """资金流高级 API。

    用法：
        service = FlowService.from_default(Path("data/market.db"))
        result = service.pull_today(SemiconPool(...), force=True)
        for s in service.top_today(pool, n=20, by="inflow"):
            print(s.code, s.main_net)
    """

    def __init__(
        self,
        adapter: CachedMarketDataAdapter,
        store: CacheStore,
    ) -> None:
        self.adapter = adapter
        self.store = store

    @classmethod
    def from_default(
        cls,
        db_path: Path,
        *,
        use_fallback: bool = True,
    ) -> FlowService:
        """默认构造：CacheStore + CachedMarketDataAdapter(Efinance + Tencent fallback)。"""
        from mommy_chaogu.cache import CachedMarketDataAdapter, CacheStore
        from mommy_chaogu.market_data import EfinanceAdapter, FallbackAdapter, TencentAdapter

        store = CacheStore(db_path)
        # base 必须是 MarketDataAdapter Protocol，但 TencentAdapter.get_bars 用了 **kw，
        # 跟 Protocol 里强类型签名不一致（运行时兼容）。所以这里统一用 Any 转一道。
        base: Any
        if use_fallback:
            base = FallbackAdapter([EfinanceAdapter(), TencentAdapter()])  # type: ignore[list-item]
        else:
            base = EfinanceAdapter()
        adapter = CachedMarketDataAdapter(base, store)
        return cls(adapter, store)

    # ============================================================
    # 拉新
    # ============================================================

    def _force_fetch_today(self, code: str) -> list[MoneyFlow]:
        """绕过 today_money_flow 节流，强制拉新。"""
        # 重置该 code 的拉新节流（私有 API，但 CacheManager 也用这招）
        self.adapter._last_fetch_attempt[f"today_flow:{code}"] = datetime.min.replace(tzinfo=UTC)
        flows = self.adapter.get_today_money_flow(code)
        return flows

    def _force_fetch_history(self, code: str, days: int) -> list[MoneyFlow]:
        self.adapter._last_fetch_attempt[f"history_flow:{code}"] = datetime.min.replace(tzinfo=UTC)
        flows = self.adapter.get_history_money_flow(code, days=days)
        return flows

    def pull_today(self, pool: PoolSource, *, force: bool = False) -> PullResult:
        """拉某池所有 code 的当日资金流。"""
        codes = pool.codes()
        t0 = _utcnow()
        result = PullResult(pool_name=pool.name, target="today")
        for code in codes:
            try:
                if force:
                    flows = self._force_fetch_today(code)
                else:
                    flows = self.adapter.get_today_money_flow(code)
                if flows:
                    result.ok += 1
                else:
                    result.failed += 1
                    result.failed_codes.append(code)
            except Exception as e:
                _log.warning("pull_today(%s) failed: %s", code, e)
                result.failed += 1
                result.failed_codes.append(code)
        result.elapsed_seconds = (_utcnow() - t0).total_seconds()
        return result

    def pull_history(
        self,
        pool: PoolSource,
        days: int = 30,
        *,
        force: bool = False,
    ) -> PullResult:
        """拉某池所有 code 的历史 N 天资金流。"""
        codes = pool.codes()
        t0 = _utcnow()
        result = PullResult(pool_name=pool.name, target=f"history:{days}d")
        for code in codes:
            try:
                if force:
                    flows = self._force_fetch_history(code, days)
                else:
                    flows = self.adapter.get_history_money_flow(code, days=days)
                if flows:
                    result.ok += 1
                else:
                    result.failed += 1
                    result.failed_codes.append(code)
            except Exception as e:
                _log.warning("pull_history(%s) failed: %s", code, e)
                result.failed += 1
                result.failed_codes.append(code)
        result.elapsed_seconds = (_utcnow() - t0).total_seconds()
        return result

    # ============================================================
    # 排行（直接读缓存，不打接口）
    # ============================================================

    def _summarize_today_from_cache(self, code: str) -> FlowSummary | None:
        raw = self.store.get_today_money_flow(code)
        if not raw:
            return None
        flows = [_money_flow_from_dict(d) for d in raw]
        return self._aggregate_today(code, flows)

    def _aggregate_today(self, code: str, flows: list[MoneyFlow]) -> FlowSummary:
        """当日资金流：取最新一条（efinance 当日数据是滚动更新，最后一条是当前累计）。"""
        if not flows:
            return FlowSummary(
                code=code,
                name="",
                main_net=Decimal(0),
                super_large_net=Decimal(0),
                large_net=Decimal(0),
                medium_net=Decimal(0),
                small_net=Decimal(0),
                main_net_ratio=None,
                sample_count=0,
                period="today",
            )
        latest = flows[-1]
        return FlowSummary(
            code=code,
            name=latest.name,
            main_net=latest.main_net.amount,
            super_large_net=latest.super_large_net.amount,
            large_net=latest.large_net.amount,
            medium_net=latest.medium_net.amount,
            small_net=latest.small_net.amount,
            main_net_ratio=latest.main_net_ratio,
            sample_count=len(flows),
            period="today",
        )

    def _aggregate_history(self, code: str, days: int, flows: list[MoneyFlow]) -> FlowSummary:
        """历史资金流：按天累加（每天的最末一条是当日累计）。"""
        # 按 trade_date 分组
        by_date: dict[str, list[MoneyFlow]] = {}
        for f in flows:
            d = f.timestamp.strftime("%Y-%m-%d")
            by_date.setdefault(d, []).append(f)
        if not by_date:
            return FlowSummary(
                code=code,
                name="",
                main_net=Decimal(0),
                super_large_net=Decimal(0),
                large_net=Decimal(0),
                medium_net=Decimal(0),
                small_net=Decimal(0),
                main_net_ratio=None,
                sample_count=0,
                period=f"history:{days}d",
            )
        # 每天取最后一条（当日累计），再把所有天相加
        main = super_large = large = medium = small = Decimal(0)
        name = ""
        for _d, fs in by_date.items():
            last = fs[-1]
            name = name or last.name
            main += last.main_net.amount
            super_large += last.super_large_net.amount
            large += last.large_net.amount
            medium += last.medium_net.amount
            small += last.small_net.amount
        return FlowSummary(
            code=code,
            name=name,
            main_net=main,
            super_large_net=super_large,
            large_net=large,
            medium_net=medium,
            small_net=small,
            main_net_ratio=None,  # 累加后比例没意义
            sample_count=len(by_date),
            period=f"history:{days}d",
        )

    def top_today(
        self,
        pool: PoolSource,
        n: int = 20,
        *,
        by: Literal["main_net", "big_money"] = "main_net",
        direction: Literal["in", "out"] = "in",
    ) -> list[FlowSummary]:
        """当日按主力（或大资金）净流入排行。

        Args:
            pool: 股票池
            n: 取前 N
            by: main_net（主力净流入） / big_money（超大单+大单）
            direction: in（流入最多） / out（流出最多）
        """
        summaries: list[FlowSummary] = []
        for code in pool.codes():
            s = self._summarize_today_from_cache(code)
            if s is not None:
                summaries.append(s)
        return self._sort_top(summaries, n, by=by, direction=direction)

    def top_history(
        self,
        pool: PoolSource,
        days: int = 30,
        n: int = 20,
        *,
        by: Literal["main_net", "big_money"] = "main_net",
        direction: Literal["in", "out"] = "in",
    ) -> list[FlowSummary]:
        """历史 N 天累计排行（直接读缓存里的 money_flow_cache）。"""
        summaries: list[FlowSummary] = []
        for code in pool.codes():
            raw = self.store.get_money_flow_history(code)
            if not raw:
                continue
            # raw: list[{"__trade_date__": "2026-XX-XX", "flows": [flow_dict, ...]}]
            all_flows: list[MoneyFlow] = []
            for d in raw:
                all_flows.extend(_money_flow_from_dict(f) for f in d.get("flows", []))
            s = self._aggregate_history(code, days, all_flows)
            summaries.append(s)
        return self._sort_top(summaries, n, by=by, direction=direction)

    def _sort_top(
        self,
        summaries: list[FlowSummary],
        n: int,
        *,
        by: str,
        direction: str,
    ) -> list[FlowSummary]:
        key_fn = (lambda s: s.big_money_net()) if by == "big_money" else (lambda s: s.main_net)
        if direction == "in":
            return sorted(summaries, key=key_fn, reverse=True)[:n]
        # direction == "out"  →  净流出最多 = 主力净流入最小的
        return sorted(summaries, key=key_fn)[:n]

    # ============================================================
    # 单只查询
    # ============================================================

    def get_market_caps(self, codes: list[str]) -> dict[str, tuple[str, Decimal]]:
        """批量拉取 (name, total_market_cap, circulating_market_cap)。

        走 CachedMarketDataAdapter.get_quote，自动启用节流 + 缓存。
        返回 {code: (name, circ_mcap)}，拿不到市值的 code 不在结果里。
        """
        out: dict[str, tuple[str, Decimal]] = {}
        # 强制重置节流（让监控模式能每轮都拿到最新市值）
        for code in codes:
            self.adapter._last_fetch_attempt[f"quote:{code}"] = datetime.min.replace(tzinfo=UTC)
        for code in codes:
            try:
                q = self.adapter.get_quote(code)
            except Exception as e:
                _log.warning("get_market_caps(%s) failed: %s", code, e)
                continue
            if q is None:
                continue
            circ = q.circulating_market_cap.amount if q.circulating_market_cap else None
            if circ is None or circ == 0:
                # fallback 到总市值（这种股很罕见）
                circ = q.total_market_cap.amount if q.total_market_cap else None
            if circ is None or circ == 0:
                continue
            out[code] = (q.name, circ)
        return out

    def show(self, code: str, days: int = 30) -> dict[str, Any]:
        """查单只：当日 + 最近 N 天历史 + 缓存新鲜度。"""
        today = self._summarize_today_from_cache(code)
        history_raw = self.store.get_money_flow_history(code)
        history_flows: list[MoneyFlow] = []
        if history_raw:
            for d in history_raw:
                history_flows.extend(_money_flow_from_dict(f) for f in d.get("flows", []))
        history = self._aggregate_history(code, days, history_flows) if history_flows else None
        return {
            "code": code,
            "today": today,
            "history": history,
            "history_days_cached": len({f.timestamp.strftime("%Y-%m-%d") for f in history_flows}),
        }

    # ============================================================
    # 统计 / 清理
    # ============================================================

    def stats(self, pool: PoolSource) -> dict[str, int]:
        """缓存覆盖度。"""
        all_codes = set(pool.codes())
        today_cached = 0
        history_cached = 0
        for code in all_codes:
            if self.store.get_today_money_flow(code):
                today_cached += 1
            if self.store.get_money_flow_history(code):
                history_cached += 1
        return {
            "pool_total": len(all_codes),
            "today_cached": today_cached,
            "history_cached": history_cached,
        }

    def clear(self, pool: PoolSource) -> dict[str, int]:
        """清空某池子的 today + history 缓存（不删其他池子的）。"""
        codes = set(pool.codes())
        from sqlalchemy import text

        n_today = 0
        n_history = 0
        with self.store.session() as s:
            for code in codes:
                r: Any = s.execute(
                    text("DELETE FROM today_money_flow_cache WHERE code = :code"),
                    {"code": code},
                )
                n_today += r.rowcount or 0
                r = s.execute(
                    text("DELETE FROM money_flow_cache WHERE code = :code"),
                    {"code": code},
                )
                n_history += r.rowcount or 0
        return {"today_deleted": n_today, "history_deleted": n_history}


# ---------- 内部：MoneyFlow 反序列化（与 adapter.py 同款） ----------


def _money_flow_from_dict(d: dict[str, Any]) -> MoneyFlow:
    from decimal import Decimal

    from mommy_chaogu.market_data.types import Money, MoneyFlow

    def _money(v: object) -> Money:
        if isinstance(v, dict):
            return Money(Decimal(str(v["amount"])), v.get("currency", "CNY"))
        return Money(Decimal(str(v)), "CNY")

    ts = d["timestamp"]
    if isinstance(ts, str):
        ts = datetime.fromisoformat(ts)
    return MoneyFlow(
        code=d["code"],
        name=d.get("name", ""),
        timestamp=ts,
        main_net=_money(d["main_net"]),
        small_net=_money(d["small_net"]),
        medium_net=_money(d["medium_net"]),
        large_net=_money(d["large_net"]),
        super_large_net=_money(d["super_large_net"]),
        main_net_ratio=Decimal(str(d["main_net_ratio"])) if d.get("main_net_ratio") else None,
    )
