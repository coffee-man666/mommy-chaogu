"""MCP server 空闲看门狗：宿主不回收 stdio 子进程时的自杀兜底。

DSH 宿主每个会话孵化一个 ``mommy_chaogu.agent.mcp_server``，会话断开后
宿主不回收子进程（实测泄漏 11+ 个、最老存活近 3 天）——server 自身是唯一
能兜底的一方。契约：

- 任何 MCP 请求（list_tools / call_tool）都会喂狗；
- 超过超时无请求则触发退出回调（生产路径 = log + ``os._exit(0)``）；
- 超时可由 ``MOMMY_MCP_IDLE_TIMEOUT`` 覆盖，非法值回退默认，0 禁用。
"""

from __future__ import annotations

import time
from collections.abc import Callable

import pytest

from mommy_chaogu.agent import mcp_server


class WatchdogHarness:
    """短超时看门狗 + 退出原因收集器（不真退进程）。"""

    def __init__(self, timeout_s: float) -> None:
        self.reasons: list[str] = []
        self.touch: Callable[[], None] = mcp_server._start_idle_watchdog(
            timeout_s, self.reasons.append
        )


class TestResolveIdleTimeout:
    def test_default_when_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("MOMMY_MCP_IDLE_TIMEOUT", raising=False)
        assert mcp_server._resolve_idle_timeout() == mcp_server.DEFAULT_IDLE_TIMEOUT_S

    def test_env_override_and_zero_disables(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MOMMY_MCP_IDLE_TIMEOUT", "120")
        assert mcp_server._resolve_idle_timeout() == 120.0
        monkeypatch.setenv("MOMMY_MCP_IDLE_TIMEOUT", "0")
        assert mcp_server._resolve_idle_timeout() == 0.0

    def test_invalid_env_falls_back_to_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MOMMY_MCP_IDLE_TIMEOUT", "soon")
        assert mcp_server._resolve_idle_timeout() == mcp_server.DEFAULT_IDLE_TIMEOUT_S

    def test_explicit_argument_wins(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MOMMY_MCP_IDLE_TIMEOUT", "120")
        assert mcp_server._resolve_idle_timeout(5.0) == 5.0
        assert mcp_server._resolve_idle_timeout(0.0) == 0.0


class TestIdleWatchdog:
    def test_exits_after_idle_timeout(self) -> None:
        dog = WatchdogHarness(0.05)
        time.sleep(0.12)
        assert len(dog.reasons) == 1
        assert "idle" in dog.reasons[0]

    def test_touch_keeps_it_alive(self) -> None:
        dog = WatchdogHarness(0.1)
        for _ in range(6):  # 总时长超过超时，但持续喂狗
            time.sleep(0.04)
            dog.touch()
        assert dog.reasons == []

    def test_watchdog_thread_is_daemon(self) -> None:
        import threading

        # 前序用例的同名看门狗线程可能尚未退出，按对象而非名字区分。
        before = set(threading.enumerate())
        WatchdogHarness(60.0)
        new = [t for t in threading.enumerate() if t not in before]
        assert any(t.name == "mommy-mcp-idle-watchdog" and t.daemon for t in new)
