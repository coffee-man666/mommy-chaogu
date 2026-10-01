"""板块多日相对强弱服务单测（全离线：fake adapter + fake 翻页 + tmp_path 库）。

覆盖 services/sector_momentum.py：
- fetch_all_sector_boards：clist 全量翻页枚举（翻页推进 / total 停止 / 去重 /
  include_concept 扩概念 / 单页失败部分结果 + complete=False / 翻页间限速）
- SectorMomentumService.compute：N 日收益与排名 vs 上一窗口的数学、
  K 线不足不凑数、逐板块限速只在真实访问上游时发生、板块池拉不到时
  回退 bar_cache 已缓存板块并标注 pool_source/data_cutoff、池完全不可用
  返回 error 不产出假排名
- CacheStore.list_cached_bar_codes：前缀 + interval + adj_type 过滤（只读）
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from mommy_chaogu.cache.store import CacheStore
from mommy_chaogu.market_data.types import AdjustmentType, Bar, BarInterval, Money
from mommy_chaogu.services.sector_momentum import (
    SectorBoard,
    SectorMomentumService,
    SectorPool,
    fetch_all_sector_boards,
)


def _bar(code: str, day: int, close: str, name: str = "") -> Bar:
    return Bar(
        code=code,
        name=name,
        interval=BarInterval.D1,
        adjustment=AdjustmentType.FORWARD,
        timestamp=datetime(2026, 7, 1) + timedelta(days=day),
        open=Decimal(close),
        high=Decimal(close),
        low=Decimal(close),
        close=Decimal(close),
        volume=100,
        turnover=Money.from_yuan("100"),
        change_pct=Decimal("0"),
    )


class FakeAdapter:
    """按代码返回预设日 K；last_source 模拟 CachedAdapter 的网络命中标记。"""

    name = "fake"

    def __init__(
        self,
        bars_by_code: dict[str, list[Bar]],
        network_codes: set[str] | None = None,
    ) -> None:
        self._bars = bars_by_code
        self._network_codes = network_codes or set()
        # 模拟 CachedMarketDataAdapter 的上游访问计数（服务层按
        # stats_counters["fetches"] 差值判定是否限速）：network_codes
        # 中的代码每次 get_bars 计数 +1，其余视为缓存命中（计数不变）。
        self.stats_counters: dict[str, int] = {"fetches": 0, "fetch_ok": 0, "fetch_fail": 0}
        self.calls: list[tuple[str, int | None]] = []

    def get_bars(
        self,
        code: str,
        interval: BarInterval = BarInterval.D1,
        adjustment: AdjustmentType = AdjustmentType.FORWARD,
        start: Any = None,
        end: Any = None,
        limit: int | None = None,
    ) -> list[Bar]:
        self.calls.append((code, limit))
        if code in self._network_codes:
            self.stats_counters["fetches"] += 1
        bars = self._bars.get(code, [])
        return list(bars[-limit:]) if limit is not None else list(bars)


class PlainAdapter:
    """无 stats_counters 的裸 adapter（服务层应保守限速）。"""

    name = "plain"

    def __init__(self, bars_by_code: dict[str, list[Bar]]) -> None:
        self._bars = bars_by_code

    def get_bars(
        self,
        code: str,
        interval: BarInterval = BarInterval.D1,
        adjustment: AdjustmentType = AdjustmentType.FORWARD,
        start: Any = None,
        end: Any = None,
        limit: int | None = None,
    ) -> list[Bar]:
        bars = self._bars.get(code, [])
        return list(bars[-limit:]) if limit is not None else list(bars)


class SleepRecorder:
    def __init__(self) -> None:
        self.pauses: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.pauses.append(seconds)


# ---------- fetch_all_sector_boards（板块池全量翻页枚举） ----------


def _page(diff: list[dict[str, Any]], total: int) -> dict[str, Any]:
    return {"data": {"diff": diff, "total": total}}


class TestFetchAllSectorBoards:
    def test_paginates_until_total_collected(self) -> None:
        queries: list[dict[str, str]] = []

        def fake_fetch(url: str, params: dict[str, str]) -> dict[str, Any]:
            queries.append(params)
            pages = {
                "1": _page(
                    [{"f12": "BK1036", "f14": "半导体"}, {"f12": "BK0475", "f14": "银行"}], 3
                ),
                "2": _page([{"f12": "BK1106", "f14": "创新药"}], 3),
            }
            return pages[params["pn"]]

        pool = fetch_all_sector_boards(page_size=2, sleep_fn=SleepRecorder(), fetch_json=fake_fetch)

        assert [b.code for b in pool.boards] == ["BK1036", "BK0475", "BK1106"]
        assert pool.complete is True
        assert pool.source == "clist"
        assert all(b.board_type == "industry" for b in pool.boards)
        # 翻页推进到 pn=2，凑满 total 后停止
        assert [q["pn"] for q in queries] == ["1", "2"]
        assert all(q["fs"] == "m:90+t:2" for q in queries)
        assert queries[0]["fields"] == "f12,f14"

    def test_include_concept_adds_second_fs(self) -> None:
        def fake_fetch(url: str, params: dict[str, str]) -> dict[str, Any]:
            if params["fs"] == "m:90+t:2":
                return _page([{"f12": "BK1036", "f14": "半导体"}], 1)
            return _page([{"f12": "BK0817", "f14": "人工智能"}], 1)

        pool = fetch_all_sector_boards(
            include_concept=True, sleep_fn=SleepRecorder(), fetch_json=fake_fetch
        )
        types = {b.board_type for b in pool.boards}
        assert types == {"industry", "concept"}
        assert pool.complete is True

    def test_dedups_same_code_across_fs(self) -> None:
        def fake_fetch(url: str, params: dict[str, str]) -> dict[str, Any]:
            return _page([{"f12": "BK1036", "f14": "半导体"}], 1)

        pool = fetch_all_sector_boards(
            include_concept=True, sleep_fn=SleepRecorder(), fetch_json=fake_fetch
        )
        assert [b.code for b in pool.boards] == ["BK1036"]

    def test_page_failure_returns_partial_and_incomplete(self) -> None:
        def fake_fetch(url: str, params: dict[str, str]) -> dict[str, Any]:
            if params["pn"] == "1":
                return _page(
                    [{"f12": "BK1036", "f14": "半导体"}, {"f12": "BK0475", "f14": "银行"}], 5
                )
            raise ConnectionError("eastmoney unreachable")

        pool = fetch_all_sector_boards(page_size=2, sleep_fn=SleepRecorder(), fetch_json=fake_fetch)
        assert len(pool.boards) == 2
        assert pool.complete is False

    def test_rate_limits_between_pages_only(self) -> None:
        recorder = SleepRecorder()

        def fake_fetch(url: str, params: dict[str, str]) -> dict[str, Any]:
            pages = {
                "1": _page([{"f12": "BK1036", "f14": "半导体"}], 2),
                "2": _page([{"f12": "BK0475", "f14": "银行"}], 2),
            }
            return pages[params["pn"]]

        fetch_all_sector_boards(page_pause=0.3, sleep_fn=recorder, fetch_json=fake_fetch)
        # 2 页之间 sleep 一次；凑满 total 后不再 sleep
        assert recorder.pauses == [0.3]


# ---------- SectorMomentumService.compute ----------


def _closes(code: str, values: list[str], name: str = "") -> list[Bar]:
    return [_bar(code, day, close, name) for day, close in enumerate(values)]


class TestCompute:
    def test_returns_and_rank_vs_previous_window(self) -> None:
        # days=2 → 需要 5 根收盘：cur = close[-1]/close[-3] - 1；prev = close[-3]/close[-5] - 1
        adapter = FakeAdapter(
            {
                # A：当前窗口 +21%，上一窗口 0% → rank 1，rank_prev 2（上升 +1）
                "BK1036": _closes("BK1036", ["100", "100", "100", "110", "121"], "半导体"),
                # B：当前窗口 0%，上一窗口 +10% → rank 2，rank_prev 1（下降 -1）
                "BK0475": _closes("BK0475", ["100", "100", "110", "105", "110"], "银行"),
            }
        )
        service = SectorMomentumService(
            adapter,
            pool_fetcher=lambda **_: SectorPool(
                boards=[
                    SectorBoard("BK1036", "半导体", "industry"),
                    SectorBoard("BK0475", "银行", "industry"),
                ]
            ),
            sleep_fn=SleepRecorder(),
        )
        result = service.compute(days=2)

        assert result["days"] == 2
        assert result["pool_source"] == "clist"
        assert result["boards_evaluated"] == 2
        assert result["boards_missing"] == 0
        ranking = result["ranking"]
        assert ranking[0]["code"] == "BK1036"
        assert ranking[0]["return_pct"] == Decimal("21.00")
        assert ranking[0]["return_pct_prev"] == Decimal("0.00")
        assert ranking[0]["rank"] == 1
        assert ranking[0]["rank_prev"] == 2
        assert ranking[0]["rank_change"] == 1
        assert ranking[1]["code"] == "BK0475"
        assert ranking[1]["rank_change"] == -1
        # 名字透传
        assert ranking[0]["name"] == "半导体"
        assert "探索性观察" in result["note"]

    def test_insufficient_bars_excluded_or_partial_prev(self) -> None:
        adapter = FakeAdapter(
            {
                # 恰好 days+1=3 根：可算当前窗口、无上一窗口
                "BK1036": _closes("BK1036", ["100", "110", "121"], "半导体"),
                # 2 根不足 days+1：剔除
                "BK0475": _closes("BK0475", ["100", "110"], "银行"),
            }
        )
        service = SectorMomentumService(
            adapter,
            pool_fetcher=lambda **_: SectorPool(
                boards=[
                    SectorBoard("BK1036", "半导体", "industry"),
                    SectorBoard("BK0475", "银行", "industry"),
                ]
            ),
            sleep_fn=SleepRecorder(),
        )
        result = service.compute(days=2)

        assert result["boards_evaluated"] == 1
        assert result["boards_missing"] == 1
        row = result["ranking"][0]
        assert row["return_pct"] == Decimal("21.00")
        assert row["return_pct_prev"] is None
        assert row["rank_prev"] is None
        assert row["rank_change"] is None

    def test_no_bars_counts_missing_not_fake_signal(self) -> None:
        adapter = FakeAdapter({"BK1036": _closes("BK1036", ["100", "110", "121"], "半导体")})
        service = SectorMomentumService(
            adapter,
            pool_fetcher=lambda **_: SectorPool(
                boards=[
                    SectorBoard("BK1036", "半导体", "industry"),
                    SectorBoard("BK9999", "缺失", "industry"),
                ]
            ),
            sleep_fn=SleepRecorder(),
        )
        result = service.compute(days=2)
        assert result["boards_evaluated"] == 1
        assert result["boards_missing"] == 1
        assert [r["code"] for r in result["ranking"]] == ["BK1036"]

    def test_throttles_only_when_upstream_hit(self) -> None:
        adapter = FakeAdapter(
            {
                "BK1036": _closes("BK1036", ["100", "100", "110", "110", "121"]),
                "BK0475": _closes("BK0475", ["100", "100", "100", "100", "100"]),
                "BK1106": _closes("BK1106", ["100", "100", "100", "100", "100"]),
            },
            network_codes={"BK1036", "BK0475"},  # 前两个走网络，第三个缓存命中
        )
        recorder = SleepRecorder()
        service = SectorMomentumService(
            adapter,
            pool_fetcher=lambda **_: SectorPool(
                boards=[
                    SectorBoard("BK1036", "", "industry"),
                    SectorBoard("BK0475", "", "industry"),
                    SectorBoard("BK1106", "", "industry"),
                ]
            ),
            sleep_fn=recorder,
            board_pause=0.5,
        )
        service.compute(days=2)
        # 只有真实访问上游的两次限速；缓存命中的板块零等待（二次执行快）
        assert recorder.pauses == [0.5, 0.5]
        # name 缺失时从 K 线回填（fallback 池场景）
        assert all(r["name"] == r["code"] for r in service.compute(days=2)["ranking"])

    def test_incremental_refetch_after_window_expiry_is_throttled(self, tmp_path: Path) -> None:
        """回归（评审问题）：warm cache + 节流窗口过期（次日重跑）时增量拉新真实
        访问上游，必须限速——即使 CachedAdapter 此时 last_source 仍为 "cache"。

        复现路径：cache/adapter.py 增量拉新分支访问 inner 后无条件回写
        last_source="cache"（:392），按 last_source 判定会漏掉这条路径，
        约 90 行业（含概念约 490）次请求零间隔连发。
        """
        from mommy_chaogu.cache import CacheConfig, CachedMarketDataAdapter

        class CountingInner:
            name = "counting"

            def __init__(self, bars: list[Bar]) -> None:
                self.bars = bars
                self.calls = 0

            def get_bars(self, code: str, **kwargs: Any) -> list[Bar]:
                self.calls += 1
                return list(self.bars)

        bars = _closes("BK1036", ["100", "100", "100", "110", "121"], "半导体")

        def pool(**kwargs: Any) -> SectorPool:
            return SectorPool(boards=[SectorBoard("BK1036", "半导体", "industry")])

        store = CacheStore(tmp_path / "market.db")
        inner = CountingInner(bars)
        # bar_fetch_interval_seconds=0 → 节流窗口总是过期 = 次日重跑场景
        cached = CachedMarketDataAdapter(inner, store, CacheConfig(bar_fetch_interval_seconds=0))

        first_sleeps: list[float] = []
        SectorMomentumService(cached, pool_fetcher=pool, sleep_fn=first_sleeps.append).compute(
            days=2
        )
        assert inner.calls == 1  # 首次：无缓存，走网络路径
        assert first_sleeps  # 首拉限速

        second_sleeps: list[float] = []
        second = SectorMomentumService(
            cached, pool_fetcher=pool, sleep_fn=second_sleeps.append
        ).compute(days=2)
        # 增量拉新真实访问了上游（inner 再被调用一次）……
        assert inner.calls == 2
        # ……且 last_source 仍是 "cache"（该路径的无条件回写）——恰好是
        # 按 last_source 判定会漏掉的场景
        assert cached.last_source == "cache"
        # 但限速必须发生：计数器差值检测不依赖 last_source
        assert second_sleeps == [0.5]
        assert second["ranking"][0]["return_pct"] == Decimal("21.00")
        store.close()

    def test_plain_adapter_without_counters_throttles_conservatively(self) -> None:
        """无法感知上游访问计数的裸 adapter：保守起见每个板块都限速。"""
        adapter = PlainAdapter(
            {
                "BK1036": _closes("BK1036", ["100", "100", "100", "110", "121"]),
                "BK0475": _closes("BK0475", ["100", "100", "100", "100", "100"]),
            }
        )
        recorder = SleepRecorder()
        service = SectorMomentumService(
            adapter,
            pool_fetcher=lambda **_: SectorPool(
                boards=[
                    SectorBoard("BK1036", "半导体", "industry"),
                    SectorBoard("BK0475", "银行", "industry"),
                ]
            ),
            sleep_fn=recorder,
            board_pause=0.5,
        )
        service.compute(days=2)
        assert recorder.pauses == [0.5, 0.5]

    def test_bars_land_in_bar_cache_and_second_run_is_cache_hit(self, tmp_path: Path) -> None:
        """经真实 CachedMarketDataAdapter：日 K 落 bar_cache，二次计算零网络零限速。"""
        from mommy_chaogu.cache import CachedMarketDataAdapter

        store = CacheStore(tmp_path / "market.db")
        inner = FakeAdapter(
            {"BK1036": _closes("BK1036", ["100", "100", "100", "110", "121"], "半导体")}
        )
        cached = CachedMarketDataAdapter(inner, store)
        service = SectorMomentumService(
            cached,
            pool_fetcher=lambda **_: SectorPool(
                boards=[SectorBoard("BK1036", "半导体", "industry")]
            ),
            sleep_fn=SleepRecorder(),
            board_pause=0.5,
        )

        first = service.compute(days=2)
        # 首次经 CachedAdapter 拉新 → K 线已落 bar_cache（TEXT 主键，零 schema 变更）
        assert first["ranking"][0]["return_pct"] == Decimal("21.00")
        assert store.get_bars("BK1036", "1d", "forward") is not None
        assert cached.stats_counters["fetch_ok"] >= 1

        # 二次执行：节流窗口内走缓存（last_source=cache）→ 不再限速等待
        recorder = SleepRecorder()
        service2 = SectorMomentumService(
            cached,
            pool_fetcher=lambda **_: SectorPool(
                boards=[SectorBoard("BK1036", "半导体", "industry")]
            ),
            sleep_fn=recorder,
            board_pause=0.5,
        )
        second = service2.compute(days=2)
        assert second["ranking"][0]["return_pct"] == Decimal("21.00")
        assert recorder.pauses == []
        # inner 只在首次被访问过一次——二次执行零网络
        assert len(inner.calls) == 1
        assert inner.calls[0][0] == "BK1036"
        store.close()

    def test_pool_failure_falls_back_to_bar_cache(self, tmp_path: Path) -> None:
        store = CacheStore(tmp_path / "market.db")
        for code in ["BK0475", "BK1036"]:
            store.set_bar(code, "1d", "forward", "2026-09-30", {"close": "10"})

        adapter = FakeAdapter({"BK1036": _closes("BK1036", ["100", "100", "100", "110", "121"])})
        service = SectorMomentumService(
            adapter,
            store=store,
            pool_fetcher=lambda **_: SectorPool(boards=[], complete=False),
            sleep_fn=SleepRecorder(),
        )
        result = service.compute(days=2)

        # 拉新失败保留旧数据：回退 bar_cache 板块池并如实标注
        assert result["pool_source"] == "bar_cache"
        assert result["pool_complete"] is False
        assert result["pool_size"] == 2
        # BK0475 无 K 线 → missing；BK1036 正常评估
        assert result["boards_evaluated"] == 1
        assert result["boards_missing"] == 1
        assert result["ranking"][0]["code"] == "BK1036"
        store.close()

    def test_pool_unavailable_without_cache_returns_error(self) -> None:
        adapter = FakeAdapter({"BK1036": _closes("BK1036", ["100", "110", "121"])})
        service = SectorMomentumService(
            adapter,
            pool_fetcher=lambda **_: SectorPool(boards=[], complete=False),
            sleep_fn=SleepRecorder(),
        )
        result = service.compute(days=2)
        assert "error" in result
        assert "板块池不可用" in result["error"]
        assert "ranking" not in result

    def test_days_clamped_defensively(self) -> None:
        adapter = FakeAdapter({"BK1036": _closes("BK1036", ["100", "110", "121"])})
        service = SectorMomentumService(
            adapter,
            pool_fetcher=lambda **_: SectorPool(
                boards=[SectorBoard("BK1036", "半导体", "industry")]
            ),
            sleep_fn=SleepRecorder(),
        )
        assert service.compute(days=999)["days"] == 60
        assert service.compute(days=1)["days"] == 2


# ---------- CacheStore.list_cached_bar_codes（回退池的只读枚举） ----------


class TestListCachedBarCodes:
    def test_filters_by_prefix_interval_and_adj_type(self, tmp_path: Path) -> None:
        store = CacheStore(tmp_path / "market.db")
        for code in ["BK1036", "BK0475", "600519"]:
            store.set_bar(code, "1d", "forward", "2026-09-30", {"close": "10"})
        store.set_bar("BK9999", "5m", "forward", "2026-09-30", {"close": "10"})
        store.set_bar("BK8888", "1d", "none", "2026-09-30", {"close": "10"})

        assert store.list_cached_bar_codes("BK", "1d", "forward") == ["BK0475", "BK1036"]
        assert store.list_cached_bar_codes("600", "1d", "forward") == ["600519"]
        assert store.list_cached_bar_codes("CX", "1d", "forward") == []
        store.close()

    def test_is_read_only(self, tmp_path: Path) -> None:
        store = CacheStore(tmp_path / "market.db")
        store.set_bar("BK1036", "1d", "forward", "2026-09-30", {"close": "10"})
        before = store.get_bars("BK1036", "1d", "forward")
        store.list_cached_bar_codes("BK", "1d", "forward")
        assert store.get_bars("BK1036", "1d", "forward") == before
        store.close()


def test_service_with_default_pool_fetcher_uses_injected_sleep(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """默认池枚举走 fetch_all_sector_boards 且把服务的 sleep_fn 传入（翻页限速同源）。"""
    adapter = FakeAdapter({"BK1036": _closes("BK1036", ["100", "110", "121"])})
    recorder = SleepRecorder()

    def fake_fetch_all(**kwargs: Any) -> SectorPool:
        assert kwargs["sleep_fn"] is recorder
        return SectorPool(boards=[SectorBoard("BK1036", "半导体", "industry")])

    monkeypatch.setattr(
        "mommy_chaogu.services.sector_momentum.fetch_all_sector_boards", fake_fetch_all
    )
    service = SectorMomentumService(adapter, sleep_fn=recorder)
    result = service.compute(days=2)
    assert result["ranking"][0]["code"] == "BK1036"
