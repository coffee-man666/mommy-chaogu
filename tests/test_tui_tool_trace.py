"""工具轨迹语义摘要（format_digest）与展开详情单测。"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Coroutine
from typing import Any

from textual.app import App, ComposeResult
from textual.containers import Vertical

from mommy_chaogu.tui.widgets.tool_indicator import (
    ToolIndicator,
    format_digest,
    format_result_digest,
)


def _run(coro: Coroutine[Any, Any, None]) -> None:
    asyncio.run(coro)


class _Host(App[None]):
    def compose(self) -> ComposeResult:
        yield Vertical()


class TestFormatDigest:
    def test_quote_semantic(self) -> None:
        result = json.dumps(
            {"code": "600519", "name": "贵州茅台", "price": 1680.0, "change_pct": -0.52},
            ensure_ascii=False,
        )
        assert format_digest("get_quote", result) == "贵州茅台 1680.0 -0.52%"

    def test_flow_semantic(self) -> None:
        result = json.dumps(
            {"name": "贵州茅台", "main_net": -80000000, "main_net_ratio": -3.12},
            ensure_ascii=False,
        )
        digest = format_digest("get_money_flow_today", result)
        assert "贵州茅台" in digest
        assert "净流出" in digest
        assert "8000万" in digest
        assert "3.12%" in digest

    def test_bars_semantic(self) -> None:
        bars = [{"close": 100.0 + i, "timestamp": f"2026-08-{i + 1:02d}"} for i in range(5)]
        digest = format_digest("get_bars", json.dumps(bars))
        assert "5 根K线" in digest
        assert "104.0" in digest

    def test_list_counts(self) -> None:
        news = [{"title": f"n{i}"} for i in range(3)]
        assert format_digest("search_news", json.dumps(news)) == "3 条新闻"
        assert format_digest("get_watchlist", json.dumps(news)) == "3 只自选"

    def test_fallback_raw_json_first_line(self) -> None:
        result = '{"unknown": "structure"}'
        assert format_digest("mystery_tool", result) == '{"unknown": "structure"}'

    def test_fallback_broken_json(self) -> None:
        assert format_digest("get_quote", "这不是JSON") == "这不是JSON"

    def test_extractor_crash_falls_back(self) -> None:
        # get_quote 提取器拿到 list 会走 isinstance 分支返回空 → fallback
        assert format_digest("get_quote", "[1, 2, 3]") == "[1, 2, 3]"

    def test_truncated_result_still_falls_back(self) -> None:
        # 截断标记让 JSON 解析失败 → 原样首行摘要
        result = '{"a": 1}... "[truncated, 100 bytes omitted]"'
        assert format_digest("get_quote", result) == format_result_digest(result)


class TestExpandableDetail:
    def _run_mounted(self, indicator: ToolIndicator, check: Any) -> None:
        async def scenario() -> None:
            app = _Host()
            async with app.run_test() as pilot:
                host = app.query_one(Vertical)
                await host.mount(indicator)
                await pilot.pause()
                check(indicator)

        _run(scenario())

    def test_toggle_requires_result(self) -> None:
        def check(ind: ToolIndicator) -> None:
            ind.action_toggle_detail()  # 没有结果时不展开
            assert not ind.has_class("-expanded")

        self._run_mounted(ToolIndicator("get_quote", "600519", args={"code": "600519"}), check)

    def test_toggle_after_complete(self) -> None:
        result = json.dumps({"code": "600519", "name": "贵州茅台", "price": 1680.0})

        def check(ind: ToolIndicator) -> None:
            ind.set_complete("贵州茅台 1680.0", 842, result=result)
            ind.action_toggle_detail()
            assert ind.has_class("-expanded")
            content = str(ind.query_one(".ti-more").content)
            assert "参数:" in content
            assert "结果:" in content
            assert "贵州茅台" in content
            ind.action_toggle_detail()
            assert not ind.has_class("-expanded")

        self._run_mounted(ToolIndicator("get_quote", "600519", args={"code": "600519"}), check)

    def test_long_result_preview_clipped(self) -> None:
        long_result = json.dumps([{"title": "x" * 40} for _ in range(60)])

        def check(ind: ToolIndicator) -> None:
            ind.set_complete("60 条新闻", 120, result=long_result)
            ind.action_toggle_detail()
            content = str(ind.query_one(".ti-more").content)
            assert "预览已截断" in content

        self._run_mounted(ToolIndicator("search_news", "", args={}), check)

    def test_denied_state(self) -> None:
        def check(ind: ToolIndicator) -> None:
            ind.set_denied()
            content = str(ind.query_one(".ti-detail").content)
            assert "已拒绝" in content

        self._run_mounted(ToolIndicator("strategy_save", "", args={}), check)
