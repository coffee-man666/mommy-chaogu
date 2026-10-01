"""板块多日相对强弱服务（L2 板块轮动·路径式排名）。

对齐 basket_service 模式：服务层持有 adapter（生产接线是
CachedMarketDataAdapter，板块日 K 自动落 bar_cache，二次计算零网络），
把「板块池枚举 → 逐板块日 K → N 日收益 → 排名 vs 上一窗口」组装成
一次调用，回答「过去 N 日哪些板块最强？钱在往哪走？」——是路径式
排名序列，不是当日截面。

诚实边界（docs/plans/trading-method-landing.md 阶段三 / §4.4）：
- 输出是「探索性观察」，不是回测结论；
- 板块池来自东财 clist 全量翻页枚举（fetch_sector_ranking 是固定 pn=1
  单页、凑满 limit 即 break 的截断涨幅榜，不能当全量池——翻页先例见
  sector_api.fetch_sector_stocks 的 for pn 循环）；
- 全量约 90 行业 + 400 概念，每板块一次 K 线请求：逐板块间必须限速
  （仅在上游真的被访问时 sleep——按 stats_counters 前后差值判定，
  CachedAdapter 缓存命中零网络，二次执行不限速等待）；首期默认只做
  行业板块，include_concept 显式扩概念；
- 拉新失败保留旧数据：板块列表拉不到时回退 bar_cache 里已缓存的
  板块代码，输出标注 pool_source / data_cutoff；
- 板块代码一律动态枚举 / search_sector 查询，不硬编码（BK0475 曾是
  半导体、现为银行Ⅱ的漂移教训）。
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import requests

from mommy_chaogu.cache.store import CacheStore
from mommy_chaogu.market_data.adapter import MarketDataAdapter
from mommy_chaogu.market_data.rankings import SECTOR_FS
from mommy_chaogu.market_data.types import AdjustmentType, Bar, BarInterval

_log = logging.getLogger(__name__)

_CLIST_URL = "http://push2.eastmoney.com/api/qt/clist/get"

# 行业板块 fs 复用 rankings.SECTOR_FS（"m:90+t:2"，申万行业）；
# 概念板块是 "m:90+t:1"（与 fetch_sector_ranking 合并两档时的取值一致）。
CONCEPT_FS = "m:90+t:1"

# 枚举翻页只取代码 + 名称（f12/f14，字段语义同 sector_api._DEFAULT_FIELDS）。
_POOL_FIELDS = "f12,f14"

# 服务层防御钳制：窗口太小退化成当日截面（get_sector_ranking 已覆盖），
# 太大则 2N+1 根日 K 超出单板块可回溯深度的概率上升。
MIN_DAYS = 2
MAX_DAYS = 60

PoolFetcher = Callable[..., "SectorPool"]
SleepFn = Callable[[float], None]
FetchJsonFn = Callable[[str, dict[str, str]], dict[str, Any]]


@dataclass(frozen=True)
class SectorBoard:
    """板块池成员（代码一律来自接口枚举，不硬编码）。"""

    code: str
    name: str
    board_type: str  # "industry" | "concept" | "cache"（回退池未知类型）


@dataclass(frozen=True)
class SectorPool:
    """板块池：clist 全量翻页枚举结果，或 bar_cache 回退池。"""

    boards: list[SectorBoard] = field(default_factory=list)
    complete: bool = True
    source: str = "clist"


def _requests_json(url: str, params: dict[str, str]) -> dict[str, Any]:
    """默认 clist 请求（可被测试注入替换）。异常向上抛，由翻页循环捕获。"""
    response = requests.get(url, params=params, timeout=10)
    return dict(response.json())


def fetch_all_sector_boards(
    include_concept: bool = False,
    *,
    page_size: int = 100,
    max_pages: int = 10,
    page_pause: float = 0.3,
    sleep_fn: SleepFn = time.sleep,
    fetch_json: FetchJsonFn | None = None,
) -> SectorPool:
    """clist 全量翻页枚举板块池（行业 + 可选概念）。

    与 fetch_sector_ranking 的区别：不按涨幅截断，pn 逐页推进直到
    total 取完（约 90 行业 / 400 概念，pz 放大后数页），翻页间限速。
    单页失败即停止该 fs 的翻页并标 complete=False（部分结果也返回，
    由调用方决定是否回退缓存池）。

    Args:
        include_concept: 是否纳入概念板块（默认只枚举行业板块）。
        page_size: 每页条数（pz）。
        max_pages: 单个 fs 的翻页上限（防御接口异常翻不完）。
        page_pause: 翻页间限速秒数。
        sleep_fn / fetch_json: 测试注入点。
    """
    fetch = fetch_json or _requests_json
    targets: list[tuple[str, str]] = [("industry", SECTOR_FS)]
    if include_concept:
        targets.append(("concept", CONCEPT_FS))

    boards: list[SectorBoard] = []
    seen: set[str] = set()
    complete = True
    for board_type, fs in targets:
        collected = 0
        for pn in range(1, max_pages + 1):
            try:
                payload = fetch(
                    _CLIST_URL,
                    {
                        "pn": str(pn),
                        "pz": str(page_size),
                        "po": "1",
                        "np": "1",
                        "fltt": "2",
                        "invt": "2",
                        "fs": fs,
                        "fields": _POOL_FIELDS,
                        "fid": "f12",
                    },
                )
            except Exception as e:
                _log.warning("fetch_all_sector_boards %s page %d failed: %s", fs, pn, e)
                complete = False
                break
            data = payload.get("data") or {}
            diff = data.get("diff") or []
            total = int(data.get("total") or 0)
            if not diff:
                break
            for row in diff:
                code = row.get("f12")
                if not code or str(code) in seen:
                    continue
                seen.add(str(code))
                boards.append(SectorBoard(str(code), str(row.get("f14") or ""), board_type))
            collected += len(diff)
            if total and collected >= total:
                break
            if pn < max_pages:
                sleep_fn(page_pause)
    return SectorPool(boards=boards, complete=complete, source="clist")


def _pct_change(end: Decimal, start: Decimal) -> Decimal | None:
    """(end/start - 1) * 100，保留两位；起点非正数返回 None（不凑数）。"""
    if start <= 0 or end <= 0:
        return None
    return ((end / start - Decimal("1")) * Decimal("100")).quantize(Decimal("0.01"))


class SectorMomentumService:
    """板块多日相对强弱：板块池 → 逐板块日 K → N 日收益 → 排名 vs 上一窗口。

    用法（agent 工具层接线见 agent/tools/sector.py）::

        service = SectorMomentumService(cached_adapter, store=cache_store)
        result = service.compute(days=20)  # dict，金额/涨幅保留 Decimal
    """

    def __init__(
        self,
        adapter: MarketDataAdapter,
        *,
        store: CacheStore | None = None,
        pool_fetcher: PoolFetcher | None = None,
        sleep_fn: SleepFn = time.sleep,
        board_pause: float = 0.5,
    ) -> None:
        self._adapter = adapter
        self._store = store
        self._pool_fetcher = pool_fetcher
        self._sleep_fn = sleep_fn
        self._board_pause = board_pause

    def compute(self, days: int = 20, *, include_concept: bool = False) -> dict[str, Any]:
        """计算 N 日收益与排名序列（排名 vs 上一窗口）。

        Returns:
            dict（JSON 可序列化，Decimal 在工具输出边界再转 float）：
            - days / include_concept / pool_source / pool_complete / pool_size
            - boards_evaluated / boards_missing（数据不足被剔除的板块数）
            - data_cutoff（全部已用 K 线的最新交易日，失败保旧时即数据截止日）
            - ranking: [{code, name, board_type, return_pct, return_pct_prev,
              rank, rank_prev, rank_change, bars_used, as_of}] 按 rank 升序；
              rank_change = rank_prev - rank > 0 表示排名上升（资金流入方向）
            - 板块池完全不可用时返回 {"error": ...}
        """
        window = max(MIN_DAYS, min(days, MAX_DAYS))
        limit = 2 * window + 1
        pool = self._resolve_pool(include_concept)
        if isinstance(pool, dict):  # 板块池不可用（无枚举结果且无缓存回退）
            return pool

        rows: list[dict[str, Any]] = []
        missing = 0
        for board in pool.boards:
            fetches_before = self._fetch_counter()
            try:
                bars = self._adapter.get_bars(
                    board.code,
                    interval=BarInterval.D1,
                    adjustment=AdjustmentType.FORWARD,
                    limit=limit,
                )
            except Exception as e:
                _log.warning("sector bars(%s) failed: %s", board.code, e)
                bars = []
            self._throttle_after_fetch(fetches_before)

            row = self._row_from_bars(board, bars or [], window)
            if row is None:
                missing += 1
                continue
            rows.append(row)

        self._assign_ranks(rows)
        rows.sort(key=lambda r: r["rank"])
        data_cutoff = max((r["as_of"] for r in rows), default=None)
        return {
            "days": window,
            "include_concept": include_concept,
            "pool_source": pool.source,
            "pool_complete": pool.complete,
            "pool_size": len(pool.boards),
            "boards_evaluated": len(rows),
            "boards_missing": missing,
            "data_cutoff": data_cutoff,
            "ranking": rows,
            "note": "探索性观察：板块多日相对强弱为历史序列计算（东财板块日 K），非回测结论",
        }

    # ---------- 内部 ----------

    def _resolve_pool(self, include_concept: bool) -> SectorPool | dict[str, Any]:
        """优先 clist 全量枚举；拉不到时回退 bar_cache 已缓存的板块代码。"""
        if self._pool_fetcher is not None:
            pool = self._pool_fetcher(include_concept=include_concept)
        else:
            pool = fetch_all_sector_boards(include_concept=include_concept, sleep_fn=self._sleep_fn)
        if pool.boards:
            return pool

        cached = self._fallback_codes()
        if cached:
            _log.warning("板块池枚举失败，回退 bar_cache 已缓存板块 %d 个", len(cached))
            return SectorPool(
                boards=[SectorBoard(code, "", "cache") for code in cached],
                complete=False,
                source="bar_cache",
            )
        return {
            "error": "板块池不可用：东财板块列表拉取失败，且本地 bar_cache 无板块日 K 缓存",
            "days_hint": "网络恢复后重试（首次成功后会缓存板块 K 线，之后离线可用）",
        }

    def _fallback_codes(self) -> list[str]:
        """从 bar_cache 枚举已缓存板块代码（拉新失败保留旧数据）。"""
        if self._store is None:
            return []
        try:
            return self._store.list_cached_bar_codes(
                "BK", BarInterval.D1.value, AdjustmentType.FORWARD.value
            )
        except Exception as e:
            _log.warning("list_cached_bar_codes failed: %s", e)
            return []

    def _fetch_counter(self) -> int | None:
        """读 adapter 的上游请求计数；非 CachedAdapter（无计数）返回 None。"""
        counters = getattr(self._adapter, "stats_counters", None)
        if isinstance(counters, dict):
            fetches = counters.get("fetches")
            if isinstance(fetches, int):
                return fetches
        return None

    def _throttle_after_fetch(self, fetches_before: int | None) -> None:
        """仅当上游真的被访问时 sleep；缓存命中零等待（二次执行不限速）。

        按 ``stats_counters["fetches"]`` 前后差值判定，而不是 ``last_source``：
        CachedAdapter 增量拉新路径（有缓存且节流窗口过期，即次日重跑的自然
        节奏）真实访问了上游，但结束时无条件回写 ``last_source = "cache"``
        （cache/adapter.py:392）——last_source 在该路径上不是「是否访问过
        上游」的可靠信号；计数器在两条路径（首拉 :342 / 增量 :371）上都在
        请求前自增、成败都计数，是可靠信号（失败请求同样消耗上游往返，
        也要限速）。无法感知计数的 adapter 保守起见总是限速。
        """
        fetches_after = self._fetch_counter()
        if fetches_before is None or fetches_after is None or fetches_after > fetches_before:
            self._sleep_fn(self._board_pause)

    @staticmethod
    def _row_from_bars(board: SectorBoard, bars: list[Bar], window: int) -> dict[str, Any] | None:
        """由日 K 计算 N 日收益（当前窗口 + 上一窗口）；K 线不足不凑数。"""
        closes = [(bar.timestamp, bar.close) for bar in bars if bar.close > 0]
        if len(closes) < window + 1:
            return None
        end_ts, end = closes[-1]
        _, boundary = closes[-(window + 1)]
        return_pct = _pct_change(end, boundary)
        if return_pct is None:
            return None

        return_pct_prev: Decimal | None = None
        if len(closes) >= 2 * window + 1:
            _, prev_start = closes[-(2 * window + 1)]
            return_pct_prev = _pct_change(boundary, prev_start)

        name = board.name or (bars[-1].name if bars and bars[-1].name else board.code)
        return {
            "code": board.code,
            "name": name,
            "board_type": board.board_type,
            "return_pct": return_pct,
            "return_pct_prev": return_pct_prev,
            "rank": 0,
            "rank_prev": None,
            "rank_change": None,
            "bars_used": len(closes),
            "as_of": end_ts.date().isoformat(),
        }

    @staticmethod
    def _assign_ranks(rows: list[dict[str, Any]]) -> None:
        """当前窗口与上一窗口分别按收益降序排名；rank_change > 0 = 排名上升。"""
        for rank, row in enumerate(
            sorted(rows, key=lambda r: r["return_pct"], reverse=True), start=1
        ):
            row["rank"] = rank
        with_prev = [row for row in rows if row["return_pct_prev"] is not None]
        for rank_prev, row in enumerate(
            sorted(with_prev, key=lambda r: r["return_pct_prev"], reverse=True), start=1
        ):
            row["rank_prev"] = rank_prev
            row["rank_change"] = rank_prev - row["rank"]
