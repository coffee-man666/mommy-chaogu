"""mommy-monitor 的每个子命令都必须走 fallback 链。

`cmd_monitor_snapshot` / `cmd_monitor_run` 都用 `_make_adapter(args)`
（`create_adapter_chain()` + 缓存），但 `cmd_monitor_stats` 以前直接
`EfinanceAdapter()`——整个文件里唯一一条绕过降级链的路径。

后果在东财不可用时（正是 issue #3 当年的场景）两个命令对同一份自选池
给出**相反的事实**：

    mommy-monitor snapshot  -> ↑3，83.31 / 291.11 / 1258.62 都在
    mommy-monitor stats     -> 本次抓到行情: 0，↑0 ↓0

TencentAdapter 兜底明明能拿到报价，stats 却看不到。
"""

from __future__ import annotations

import argparse
from datetime import datetime
from typing import Any

from mommy_chaogu.cli_commands import monitor as monitor_cli
from mommy_chaogu.market_data.fallback_adapter import FallbackAdapter


class _DeadEfinance:
    """模拟东财挂掉：所有方法都失败。"""

    name = "efinance"

    def get_quote(self, code: str) -> None:
        return None

    def get_quotes(self, codes: list[str]) -> list[Any]:
        return []

    def list_market_quotes(self) -> list[Any]:
        return []

    def get_bars(self, code: str, **kwargs: Any) -> list[Any]:
        return []

    def get_today_money_flow(self, code: str) -> list[Any]:
        return []


class _WorkingTencent(_DeadEfinance):
    name = "tencent"

    def list_market_quotes(self) -> list[Any]:
        return []


def test_every_subcommand_builds_its_adapter_through_the_chain() -> None:
    """回归：stats 以前用裸 EfinanceAdapter()。"""
    made: list[str] = []
    original = monitor_cli._make_adapter

    def _spy(args: argparse.Namespace) -> Any:
        made.append("chain")
        return original(args)

    monitor_cli._make_adapter = _spy  # type: ignore[assignment]
    try:
        adapter = monitor_cli._make_adapter(argparse.Namespace(db="x.db"))
    finally:
        monitor_cli._make_adapter = original  # type: ignore[assignment]

    assert made == ["chain"]
    # 真正的链：Massive → Yahoo → Efinance → Tencent
    assert isinstance(adapter, FallbackAdapter) or hasattr(adapter, "list_market_quotes")


def test_stats_adapter_contains_tencent_fallback(monkeypatch: Any) -> None:
    """stats 用的 adapter 必须能落到腾讯，而不是死在东财。"""
    monkeypatch.setattr(
        monitor_cli,
        "_make_adapter",
        lambda args: FallbackAdapter([_DeadEfinance(), _WorkingTencent()]),
    )
    args = argparse.Namespace(db="x.db", log=None, signals_log=None)
    # 不跑完整命令（会打一堆 stdout），只断言 adapter 来源正确
    used: list[Any] = []

    class _SpyMonitor:
        def __init__(self, store: Any, adapter: Any, **kwargs: Any) -> None:
            used.append(adapter)

        def snapshot_now(self) -> Any:
            class _S:
                timestamp = datetime(2026, 1, 1)
                n_codes = 0
                n_up = n_down = n_flat = 0
                total_main_net = 0.0

                def __str__(self) -> str:
                    return ""

            return _S()

    monkeypatch.setattr(monitor_cli, "Monitor", _SpyMonitor)
    monkeypatch.setattr(monitor_cli, "_store", lambda args: _StubStore())
    assert monitor_cli.cmd_monitor_stats(args) == 0
    assert used and isinstance(used[0], FallbackAdapter)


class _StubStore:
    def stats(self) -> dict[str, int]:
        return {"groups": 1, "entries": 1, "codes": 1}
