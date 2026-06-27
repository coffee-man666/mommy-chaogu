"""后台轮询 + WebSocket 推送服务。

架构：
                   ┌─────────────────────────┐
                   │ Poller（单 asyncio task）│
                   │  每 N 秒轮询一次         │
                   └────────────┬────────────┘
                                │
              ┌─────────────────┼─────────────────┐
              ↓                 ↓                 ↓
        quote_subscribers  signal_subscribers  cache (写回)
              ↓                 ↓
           WS clients         WS clients

关键设计：
- 单 poller（不是每个客户端一个）—— 100 个客户端 = 1 次轮询
- 内存缓存最新 snapshot（重复请求直接返回，不查 DB）
- WS 客户端用 set 管理，broadcast 时遍历
- 优雅启停（lifespan 事件）
"""
from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from mommy_chaogu.monitor import Monitor, Snapshot
from mommy_chaogu.push import SignalNotifier
from mommy_chaogu.signals import Alerter
from mommy_chaogu.watchlist import WatchlistStore

if TYPE_CHECKING:

    from fastapi import WebSocket

    from mommy_chaogu.market_data import MarketDataAdapter

_log = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(UTC)


class BackgroundService:
    """后台轮询 + WS 广播。"""

    def __init__(
        self,
        adapter: MarketDataAdapter,
        watchlist: WatchlistStore,
        alerter: Alerter,
        poll_interval_seconds: float = 5.0,
        notifier: SignalNotifier | None = None,
    ) -> None:
        self.adapter = adapter
        self.watchlist = watchlist
        self.alerter = alerter
        self.poll_interval = poll_interval_seconds
        self.notifier = notifier

        self.monitor = Monitor(
            store=watchlist,
            adapter=adapter,
            alerter=alerter,
        )
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()

        # 最新数据（API 直接返回，不再走 adapter）
        self._latest_snapshot: Snapshot | None = None
        self._latest_signals: list[Any] = []
        self._last_poll_at: datetime | None = None
        self._started_at: datetime = _utcnow()
        self._pushed_signals: list[Any] = []  # 最近推送成功的信号

        # WS 客户端集合
        self._quote_subscribers: set[WebSocket] = set()
        self._signal_subscribers: set[WebSocket] = set()

    # ---------- 生命周期 ----------

    async def start(self) -> None:
        """启动后台轮询任务。"""
        if self._task is not None:
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run_loop(), name="poller-loop")
        _log.info("background poller started (interval=%.1fs)", self.poll_interval)

    async def stop(self) -> None:
        """停止后台轮询任务。"""
        if self._task is None:
            return
        self._stop_event.set()
        try:
            await asyncio.wait_for(self._task, timeout=5.0)
        except TimeoutError:
            self._task.cancel()
        self._task = None
        _log.info("background poller stopped")

    # ---------- 主循环 ----------

    async def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                await self._tick()
            except Exception:
                _log.exception("poller tick failed")
            # 等待下一次（被 stop_event 唤醒可立即退出）
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self.poll_interval,
                )
            except TimeoutError:
                pass

    async def _tick(self) -> None:
        """单次轮询。"""
        codes = self.watchlist.get_all_codes()
        if not codes:
            return

        snapshot = self.monitor.snapshot_now()
        self._latest_snapshot = snapshot
        self._last_poll_at = _utcnow()

        # 信号评估
        signals = self.alerter.evaluate(snapshot)
        self._latest_signals = signals

        # 推送（如果配置了 notifier）
        if self.notifier and signals:
            try:
                pushed = self.notifier.notify_batch(signals)
                if pushed:
                    self._pushed_signals.extend(pushed)
                    # 保留最近 100 条
                    self._pushed_signals = self._pushed_signals[-100:]
            except Exception:
                _log.exception("notifier notify failed (signals broadcast will continue)")

        # 广播
        if self._quote_subscribers:
            await self._broadcast_quotes(snapshot)
        if signals and self._signal_subscribers:
            await self._broadcast_signals(signals)

    # ---------- WebSocket 订阅 ----------

    async def add_quote_subscriber(self, ws: WebSocket) -> None:
        self._quote_subscribers.add(ws)
        _log.info("quote subscriber added (total=%d)", len(self._quote_subscribers))
        # 立即推送最新一份
        if self._latest_snapshot is not None:
            from mommy_chaogu.web.routes.ws import push_snapshot
            await push_snapshot(ws, self._latest_snapshot)

    def remove_quote_subscriber(self, ws: WebSocket) -> None:
        self._quote_subscribers.discard(ws)
        _log.info("quote subscriber removed (total=%d)", len(self._quote_subscribers))

    async def add_signal_subscriber(self, ws: WebSocket) -> None:
        self._signal_subscribers.add(ws)
        _log.info("signal subscriber added (total=%d)", len(self._signal_subscribers))

    def remove_signal_subscriber(self, ws: WebSocket) -> None:
        self._signal_subscribers.discard(ws)
        _log.info("signal subscriber removed (total=%d)", len(self._signal_subscribers))

    async def _broadcast_quotes(self, snapshot: Snapshot) -> None:
        from mommy_chaogu.web.routes.ws import push_snapshot

        dead: list[WebSocket] = []
        for ws in self._quote_subscribers:
            try:
                await push_snapshot(ws, snapshot)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._quote_subscribers.discard(ws)

    async def _broadcast_signals(self, signals: list[Any]) -> None:
        from mommy_chaogu.web.routes.ws import push_signals

        dead: list[WebSocket] = []
        for ws in self._signal_subscribers:
            try:
                await push_signals(ws, signals)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._signal_subscribers.discard(ws)

    # ---------- 状态查询 ----------

    @property
    def latest_snapshot(self) -> Snapshot | None:
        return self._latest_snapshot

    @property
    def latest_signals(self) -> list[Any]:
        return self._latest_signals

    def uptime_seconds(self) -> float:
        return (_utcnow() - self._started_at).total_seconds()

    def last_poll_at(self) -> datetime | None:
        return self._last_poll_at

    @property
    def pushed_signals(self) -> list[Any]:
        """最近推送成功的信号（最近 100 条）。"""
        return self._pushed_signals


# 全局单例（FastAPI lifespan 管理生命周期）
_service: BackgroundService | None = None


def get_service() -> BackgroundService:
    if _service is None:
        raise RuntimeError("BackgroundService not started")
    return _service


def set_service(service: BackgroundService) -> None:
    global _service
    _service = service
