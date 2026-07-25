"""Tests for 单屏对话新交互（§1.2）。

Covers:
- @ 股票联想（候选 → Tab 插入代码 → Enter 接受）
- 6 位代码直接看报价卡
- busy 时 Enter 排队（轮次结束自动发出）
- Esc 中断（cancel_event，保留已流部分标注「（已中断）」）
- 重试状态（on_status → 工作行「正在重试 (1/3)」）
- 记忆回执（后台线程结束后追加「✎ 已记住…」）
- renderers 工具结果卡片分发（quote/flow/bars/predictions/其他/截断）
- friendly_error 错误文案映射
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Coroutine
from types import SimpleNamespace
from typing import Any

from mommy_chaogu.tui.services.errors import friendly_error
from mommy_chaogu.tui.services.renderers import is_truncated, render_tool_result


def _run(coro: Coroutine[Any, Any, None]) -> None:
    asyncio.run(coro)


# ---------------------------------------------------------------------------
# friendly_error
# ---------------------------------------------------------------------------


class TestFriendlyError:
    def test_401(self) -> None:
        assert friendly_error(Exception("401 Unauthorized")) == "API key 无效，请检查 .env 配置"
        assert "API key" in friendly_error(Exception("Error code: 401 - invalid api key"))

    def test_429(self) -> None:
        assert friendly_error(Exception("429 Too Many Requests")) == "请求被限流，请稍后再试"
        assert "限流" in friendly_error(Exception("Rate limit reached"))

    def test_timeout(self) -> None:
        assert friendly_error(Exception("Request timed out")) == "网络超时，请稍后重试"
        assert friendly_error(Exception("连接超时")) == "网络超时，请稍后重试"

    def test_connection(self) -> None:
        assert friendly_error(Exception("Connection error")) == "网络连接失败，请检查网络"

    def test_fallback_first_line(self) -> None:
        msg = friendly_error(Exception("奇怪的错误\n第二行堆栈"))
        assert msg == "出错了：奇怪的错误"

    def test_fallback_truncated(self) -> None:
        msg = friendly_error(Exception("x" * 300))
        assert len(msg) <= len("出错了：") + 120


# ---------------------------------------------------------------------------
# renderers
# ---------------------------------------------------------------------------


class TestRenderers:
    def test_is_truncated(self) -> None:
        assert is_truncated('{"a": 1}... "[truncated, 100 bytes omitted]"')
        assert not is_truncated('{"a": 1}')

    def test_quote_renders_card(self) -> None:
        result = (
            '{"code": "600519", "name": "贵州茅台", "price": 1680.0, "change_pct": 0.5,'
            ' "open": 1670.0, "high": 1690.0, "low": 1660.0, "prev_close": 1672.0,'
            ' "volume": 23000, "turnover": 180000000}'
        )
        card = render_tool_result("get_quote", result)
        assert card is not None
        assert "quote-card" in card.classes
        content = str(card.content)  # type: ignore[attr-defined]
        assert "贵州茅台" in content
        assert "1680.00" in content

    def test_flow_single_renders_card(self) -> None:
        result = (
            '{"code": "688981", "name": "中芯国际", "main_net": 100000000,'
            ' "super_large_net": 60000000, "large_net": 40000000,'
            ' "medium_net": -20000000, "small_net": -80000000, "main_net_ratio": 12.5}'
        )
        card = render_tool_result("get_money_flow_today", result)
        assert card is not None
        assert "flow-card" in card.classes
        content = str(card.content)  # type: ignore[attr-defined]
        assert "中芯国际" in content
        assert "超大单" in content

    def test_flow_multi_renders_card(self) -> None:
        result = '[{"code": "688981", "name": "中芯国际", "main_net": 100000000}]'
        card = render_tool_result("get_money_flow_today", result)
        assert card is not None
        assert "flow-card" in card.classes

    def test_bars_renders_mini_table_capped_at_10(self) -> None:
        import json

        bars = [
            {
                "code": "600519",
                "name": "贵州茅台",
                "timestamp": f"2026-07-{i:02d}T00:00:00",
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.0 + i,
                "volume": 1000 * i,
                "turnover": 1e6,
                "change_pct": 0.1 * i,
            }
            for i in range(1, 21)
        ]
        card = render_tool_result("get_bars", json.dumps(bars))
        assert card is not None
        assert "bars-card" in card.classes
        content = str(card.content)  # type: ignore[attr-defined]
        # 20 根只渲染最近 10 行（07-11 ~ 07-20）
        assert "2026-07-20" in content
        assert "2026-07-10" not in content

    def test_prediction_history_renders_card(self) -> None:
        result = (
            '[{"id": 1, "code": "688981", "name": "中芯国际",'
            ' "prediction": "看高一线", "direction": "up", "timeframe": "5d",'
            ' "status": "pending", "verify_after": "2099-01-01T00:00:00"}]'
        )
        card = render_tool_result("get_prediction_history", result)
        assert card is not None
        assert "predictions-card" in card.classes
        assert "中芯国际" in str(card.content)  # type: ignore[attr-defined]

    def test_other_tools_return_none(self) -> None:
        assert render_tool_result("search_news", '{"items": []}') is None
        assert render_tool_result("get_watchlist", "[]") is None

    def test_error_and_non_json_return_none(self) -> None:
        assert render_tool_result("get_quote", '{"error": "未找到股票"}') is None
        assert render_tool_result("get_quote", "不是 JSON") is None

    def test_truncated_returns_none(self) -> None:
        result = '{"code": "600519"... "[truncated, 100 bytes omitted]"'
        assert render_tool_result("get_quote", result) is None


# ---------------------------------------------------------------------------
# Pilot: @ 股票联想
# ---------------------------------------------------------------------------


class TestAtSuggestion:
    def test_candidates_show_and_tab_inserts_code(self) -> None:
        from textual.widgets import Input

        from mommy_chaogu.tui.app import MommyTuiApp
        from mommy_chaogu.tui.services.bootstrap import FakeServices
        from mommy_chaogu.tui.views.chat import ChatView
        from mommy_chaogu.tui.widgets.hint_bar import HintBar

        async def _test() -> None:
            app = MommyTuiApp(services=FakeServices.create())  # type: ignore[arg-type]
            async with app.run_test() as pilot:
                chat = app.query_one(ChatView)
                hint = chat.query_one(HintBar)
                prompt = chat.query_one("#prompt", Input)
                prompt.value = "@茅"
                await pilot.pause()

                # 候选出现（HintBar 股票候选态）
                assert hint.mode == "stock-suggestions"
                assert chat._stock_matches == [("600519", "贵州茅台")]

                # Tab → 插入代码
                await pilot.press("tab")
                await pilot.pause()
                assert prompt.value == "600519 "

        _run(_test())

    def test_mid_sentence_at_token(self) -> None:
        """句子中间的 @token 也能联想，替换时保留前文。"""
        from textual.widgets import Input

        from mommy_chaogu.tui.app import MommyTuiApp
        from mommy_chaogu.tui.services.bootstrap import FakeServices
        from mommy_chaogu.tui.views.chat import ChatView

        async def _test() -> None:
            app = MommyTuiApp(services=FakeServices.create())  # type: ignore[arg-type]
            async with app.run_test() as pilot:
                chat = app.query_one(ChatView)
                prompt = chat.query_one("#prompt", Input)
                prompt.value = "分析一下 @中芯"
                await pilot.pause()
                assert chat._stock_matches == [("688981", "中芯国际")]
                await pilot.press("tab")
                await pilot.pause()
                assert prompt.value == "分析一下 688981 "

        _run(_test())

    def test_enter_accepts_selection_instead_of_sending(self) -> None:
        from textual.widgets import Input

        from mommy_chaogu.tui.app import MommyTuiApp
        from mommy_chaogu.tui.services.bootstrap import FakeServices
        from mommy_chaogu.tui.views.chat import ChatView

        async def _test() -> None:
            app = MommyTuiApp(services=FakeServices.create())  # type: ignore[arg-type]
            async with app.run_test() as pilot:
                chat = app.query_one(ChatView)
                prompt = chat.query_one("#prompt", Input)
                prompt.value = "@茅"
                await pilot.pause()
                await pilot.press("enter")
                await pilot.pause()
                # Enter 接受联想（插入代码），不发送
                assert prompt.value == "600519 "
                assert len(chat.query(".user-msg")) == 0

        _run(_test())


# ---------------------------------------------------------------------------
# Pilot: 6 位代码 → 报价卡
# ---------------------------------------------------------------------------


class TestCodeQuickQuote:
    def test_six_digits_renders_quote_card(self) -> None:
        from textual.widgets import Input

        from mommy_chaogu.tui.app import MommyTuiApp
        from mommy_chaogu.tui.services.bootstrap import FakeServices
        from mommy_chaogu.tui.views.chat import ChatView
        from tests.test_tui_smoke import _wait_for

        services = FakeServices.create()
        # 假 adapter：get_quote 返回命名元组形态
        fake_quote = SimpleNamespace(
            code="600519",
            name="贵州茅台",
            price=1680.0,
            change_pct=0.5,
            open=1670.0,
            high=1690.0,
            low=1660.0,
            prev_close=1672.0,
            volume=23000,
            turnover=SimpleNamespace(amount=180000000.0),
            turnover_rate=0.3,
            volume_ratio=1.1,
        )
        from decimal import Decimal

        services.data.adapter = SimpleNamespace(
            get_quote=lambda code: fake_quote,
            get_today_money_flow=lambda code: [SimpleNamespace(main_net=Decimal("50000000"))],
        )

        async def _test() -> None:
            app = MommyTuiApp(services=services)  # type: ignore[arg-type]
            async with app.run_test() as pilot:
                chat = app.query_one(ChatView)
                prompt = chat.query_one("#prompt", Input)
                prompt.value = "600519"
                await pilot.pause()
                await pilot.press("enter")
                assert await _wait_for(pilot, lambda: len(chat.query(".quote-card")) == 1)
                content = str(chat.query(".quote-card")[0].content)  # type: ignore[attr-defined]
                assert "贵州茅台" in content
                assert "主力净流入" in content  # FakeServices 的 flow 也拼进来了
                # 不走 AI 对话（无 user-msg 之外的 assistant 消息）
                assert len(chat.query(".assistant-msg")) == 0

        _run(_test())


# ---------------------------------------------------------------------------
# Pilot: busy 排队
# ---------------------------------------------------------------------------


class _SlowAgent:
    """等 gate 事件放行才返回的假 agent（模拟慢 LLM）。"""

    def __init__(self) -> None:
        self.gate = threading.Event()
        self.calls: list[str] = []

    def chat(self, message: str, **kwargs: Any) -> Any:  # type: ignore[no-untyped-def]
        self.calls.append(message)
        self.gate.wait(timeout=10)
        self.gate.clear()
        return SimpleNamespace(
            text=f"回复：{message}",
            tool_calls=[],
            rounds=1,
            usage={},
            interrupted=False,
        )


class TestBusyQueue:
    def test_enter_while_busy_queues_and_auto_sends(self) -> None:
        from textual.widgets import Input

        from mommy_chaogu.tui.app import MommyTuiApp
        from mommy_chaogu.tui.services.bootstrap import FakeServices
        from mommy_chaogu.tui.views.chat import ChatView
        from mommy_chaogu.tui.widgets.working_indicator import WorkingIndicator
        from tests.test_tui_smoke import _wait_for

        agent = _SlowAgent()
        services = FakeServices.create()
        services.agent._agent = agent

        async def _test() -> None:
            app = MommyTuiApp(services=services)  # type: ignore[arg-type]
            async with app.run_test() as pilot:
                chat = app.query_one(ChatView)
                prompt = chat.query_one("#prompt", Input)

                # 第一条消息 → busy
                prompt.value = "第一条"
                await pilot.pause()
                await pilot.press("enter")
                assert await _wait_for(pilot, lambda: chat._busy)

                # busy 时第二条 → 排队（不并发）
                prompt.value = "第二条"
                await pilot.pause()
                await pilot.press("enter")
                await pilot.pause()
                assert chat.queued_count() == 1
                assert agent.calls == ["第一条"]  # 没起第二个并发 worker
                working = chat.query_one(WorkingIndicator)
                assert "已排队 1 条" in str(working.content)  # type: ignore[attr-defined]

                # 放行第一轮 → 自动发出第二条
                agent.gate.set()
                assert await _wait_for(pilot, lambda: agent.calls == ["第一条", "第二条"])
                agent.gate.set()
                assert await _wait_for(pilot, lambda: not chat._busy)
                assert chat.queued_count() == 0
                # 两条用户消息都上屏
                assert len(chat.query(".user-msg")) == 2

        _run(_test())


# ---------------------------------------------------------------------------
# Pilot: Esc 中断
# ---------------------------------------------------------------------------


class _StreamingAgent:
    """流式输出途中等待 cancel_event 的假 agent。"""

    def chat(self, message: str, **kwargs: Any) -> Any:  # type: ignore[no-untyped-def]
        on_chunk = kwargs.get("on_chunk")
        cancel_event = kwargs.get("cancel_event")
        if on_chunk is not None:
            on_chunk("分析报告：第一部分。")
        # 等 Esc 取消（真实 agent 在流式途中/重试等待中检查 cancel_event）
        if cancel_event is not None:
            cancel_event.wait(timeout=10)
        return SimpleNamespace(
            text="分析报告：第一部分。",
            tool_calls=[],
            rounds=1,
            usage={},
            interrupted=True,
        )


class TestEscInterrupt:
    def test_esc_cancels_and_keeps_partial(self) -> None:
        from textual.widgets import Input, Markdown

        from mommy_chaogu.tui.app import MommyTuiApp
        from mommy_chaogu.tui.services.bootstrap import FakeServices
        from mommy_chaogu.tui.views.chat import ChatView
        from tests.test_tui_smoke import _wait_for

        services = FakeServices.create()
        services.agent._agent = _StreamingAgent()

        async def _test() -> None:
            app = MommyTuiApp(services=services)  # type: ignore[arg-type]
            async with app.run_test() as pilot:
                chat = app.query_one(ChatView)
                prompt = chat.query_one("#prompt", Input)
                prompt.value = "分析一下茅台"
                await pilot.pause()
                await pilot.press("enter")
                # 等流式 widget 出现
                assert await _wait_for(pilot, lambda: chat._stream_widget is not None)
                assert await _wait_for(pilot, lambda: chat._busy)

                # Esc 中断
                await pilot.press("escape")
                assert await _wait_for(pilot, lambda: not chat._busy)

                # 已流出部分保留 + 标注（已中断）
                assert await _wait_for(pilot, lambda: len(chat.query(".assistant-msg")) == 1)
                md = chat.query_one(".assistant-msg", Markdown)
                assert "第一部分" in str(md.source)  # type: ignore[attr-defined]
                assert "（已中断）" in str(md.source)  # type: ignore[attr-defined]
                # 没有重复的"（无回复）"消息
                assert len(chat.query(".assistant-msg")) == 1

        _run(_test())


# ---------------------------------------------------------------------------
# Pilot: 重试状态
# ---------------------------------------------------------------------------


class _RetryAgent:
    """先回调 on_status('retry', ...) 再返回的假 agent。"""

    def chat(self, message: str, **kwargs: Any) -> Any:  # type: ignore[no-untyped-def]
        on_status = kwargs.get("on_status")
        if on_status is not None:
            on_status("retry", {"attempt": 1, "max": 4, "delay": 2.0})
            time.sleep(0.2)  # 给 UI 一拍渲染重试态
        return SimpleNamespace(
            text="重试后成功",
            tool_calls=[],
            rounds=1,
            usage={},
            interrupted=False,
        )


class TestRetryStatus:
    def test_retry_status_shown_on_working_indicator(self) -> None:
        from textual.widgets import Input

        from mommy_chaogu.tui.app import MommyTuiApp
        from mommy_chaogu.tui.services.bootstrap import FakeServices
        from mommy_chaogu.tui.views.chat import ChatView
        from mommy_chaogu.tui.widgets.working_indicator import WorkingIndicator
        from tests.test_tui_smoke import _wait_for

        services = FakeServices.create()
        services.agent._agent = _RetryAgent()

        async def _test() -> None:
            app = MommyTuiApp(services=services)  # type: ignore[arg-type]
            async with app.run_test() as pilot:
                chat = app.query_one(ChatView)
                prompt = chat.query_one("#prompt", Input)
                prompt.value = "你好"
                await pilot.pause()
                await pilot.press("enter")

                # max=4（总尝试次数）→ 显示为重试进度 (1/3)
                def _retry_shown() -> bool:
                    ws = chat.query(WorkingIndicator)
                    return bool(ws) and "正在重试 (1/3)" in str(ws[0].content)  # type: ignore[attr-defined]

                assert await _wait_for(pilot, _retry_shown)
                assert await _wait_for(pilot, lambda: not chat._busy)

        _run(_test())


# ---------------------------------------------------------------------------
# Pilot: 记忆回执
# ---------------------------------------------------------------------------


class _MemoryAgent:
    """chat 返回后留下一个短寿命后台线程的假 agent（模拟记忆提取）。"""

    def __init__(self) -> None:
        self._bg_threads: list[threading.Thread] = []

    def chat(self, message: str, **kwargs: Any) -> Any:  # type: ignore[no-untyped-def]
        t = threading.Thread(target=lambda: time.sleep(0.1), daemon=True)
        t.start()
        self._bg_threads.append(t)
        return SimpleNamespace(
            text="已回答",
            tool_calls=[],
            rounds=1,
            usage={},
            interrupted=False,
        )


class TestMemoryReceipt:
    def test_receipt_appears_after_background_done(self) -> None:
        from textual.widgets import Input

        from mommy_chaogu.tui.app import MommyTuiApp
        from mommy_chaogu.tui.services.bootstrap import FakeServices
        from mommy_chaogu.tui.views.chat import ChatView
        from tests.test_tui_smoke import _wait_for

        services = FakeServices.create()
        services.agent._agent = _MemoryAgent()

        async def _test() -> None:
            app = MommyTuiApp(services=services)  # type: ignore[arg-type]
            async with app.run_test() as pilot:
                chat = app.query_one(ChatView)
                prompt = chat.query_one("#prompt", Input)
                prompt.value = "茅台怎么样"
                await pilot.pause()
                await pilot.press("enter")
                assert await _wait_for(pilot, lambda: not chat._busy)
                # 后台线程结束后追加记忆回执
                assert await _wait_for(pilot, lambda: len(chat.query(".memory-receipt")) == 1)
                content = str(chat.query(".memory-receipt")[0].content)  # type: ignore[attr-defined]
                assert "已记住" in content

        _run(_test())


# ---------------------------------------------------------------------------
# Pilot: TopBar AI🟢（有 agent 时）
# ---------------------------------------------------------------------------


class TestTopBarAiConfigured:
    def test_ai_green_when_agent_present(self) -> None:
        from mommy_chaogu.tui.app import MommyTuiApp
        from mommy_chaogu.tui.services.bootstrap import FakeServices
        from mommy_chaogu.tui.widgets.top_bar import TopBar

        services = FakeServices.create()
        services.agent._agent = SimpleNamespace(_provider="deepseek", _model="deepseek-chat")

        async def _test() -> None:
            app = MommyTuiApp(services=services)  # type: ignore[arg-type]
            async with app.run_test():
                top = app.query_one(TopBar)
                assert top.ai_label == "AI🟢 deepseek"

        _run(_test())
