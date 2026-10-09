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
import contextlib
import logging
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Any

from mommy_chaogu.monitor import Monitor, Snapshot
from mommy_chaogu.push import SignalNotifier
from mommy_chaogu.signals import Alerter, Signal
from mommy_chaogu.signals.custom_alerts import CustomAlertStore
from mommy_chaogu.signals.custom_evaluation import (
    evaluate_custom_alerts,
    load_enabled_custom_alerts,
)
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
        weixin_sender: Callable[[list[Any]], int] | None = None,
        custom_alerts: CustomAlertStore | None = None,
        earnings_job: Callable[[], list[Signal]] | None = None,
    ) -> None:
        self.adapter = adapter
        self.watchlist = watchlist
        self.alerter = alerter
        self.poll_interval = poll_interval_seconds
        self.notifier = notifier
        self.weixin_sender = weixin_sender
        self.custom_alerts = custom_alerts
        self.earnings_job = earnings_job

        self.monitor = Monitor(
            store=watchlist,
            adapter=adapter,
            alerter=alerter,
        )
        self._task: asyncio.Task[None] | None = None
        self._weixin_task: asyncio.Task[None] | None = None
        self._weixin_queue: asyncio.Queue[list[Any] | None] | None = None
        self._earnings_task: asyncio.Task[None] | None = None
        self._last_earnings_run: date | None = None
        self._stop_event = asyncio.Event()

        # 最新数据（API 直接返回，不再走 adapter）
        self._latest_snapshot: Snapshot | None = None
        self._latest_signals: list[Any] = []
        self._last_signal_keys: set[tuple[str, str]] = set()  # 上一轮 (code, rule_id)
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
        if self.weixin_sender is not None:
            self._weixin_queue = asyncio.Queue(maxsize=1)
            self._weixin_task = asyncio.create_task(
                self._run_weixin_worker(), name="weixin-notification-worker"
            )
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
        if self._earnings_task is not None and not self._earnings_task.done():
            self._earnings_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, TimeoutError):
                await asyncio.wait_for(self._earnings_task, timeout=2.0)
        self._earnings_task = None
        if self._weixin_queue is not None and self._weixin_task is not None:
            if self._weixin_queue.full():
                with contextlib.suppress(asyncio.QueueEmpty):
                    self._weixin_queue.get_nowait()
            self._weixin_queue.put_nowait(None)
            try:
                await asyncio.wait_for(self._weixin_task, timeout=5.0)
            except TimeoutError:
                self._weixin_task.cancel()
            self._weixin_task = None
            self._weixin_queue = None
        _log.info("background poller stopped")

    # ---------- 主循环 ----------

    async def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                await self._tick()
            except Exception:
                _log.exception("poller tick failed")
            # 等待下一次（被 stop_event 唤醒可立即退出）
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self.poll_interval,
                )

    async def _tick(self) -> None:
        """单次轮询。"""
        # 评估代码集 = 自选股 ∪ 启用的自定义告警（阶段五任务 2）：
        # 自选股为空但存在告警时评估循环仍进入；告警代码不必先加自选股。
        alerts = load_enabled_custom_alerts(self.custom_alerts)
        alert_codes = {a.code for a in alerts}
        codes = set(self.watchlist.get_all_codes()) | alert_codes
        if not codes:
            return

        snapshot = self.monitor.snapshot_now()
        self._latest_snapshot = snapshot
        self._last_poll_at = _utcnow()

        # 信号评估：内置规则吃 Snapshot；自定义告警直接吃 Quote
        # （告警代码不在 Snapshot 行内时经 adapter 补拉，不构造 SnapshotRow）
        signals = self.alerter.evaluate(snapshot)
        if alerts:
            quotes = {row.quote.code: row.quote for row in snapshot.rows}
            signals = signals + evaluate_custom_alerts(
                alerts,
                quotes,
                fetch_quote=self.adapter.get_quote,
            )
        self._latest_signals = signals

        # 持久化：只在信号集「新增」时落库（边沿触发）。_tick 默认 5s 一轮，
        # 规则是无状态阈值判断，条件持续满足会每轮重复触发——若每轮都写，
        # 同一条信号一天会被写入上万行。按 (code, rule_id) 对比上一轮集合，
        # 新出现的才写 SignalStore + 文本日志，与推送层 Deduper 的口径一致。
        current_keys = {(s.code, s.rule_id) for s in signals}
        fresh = [s for s in signals if (s.code, s.rule_id) not in self._last_signal_keys]
        if fresh:
            try:
                self.alerter.write_signals_log(fresh)
            except Exception:
                _log.exception("signals log write failed")
        self._last_signal_keys = current_keys

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

        # 微信通道走独立有界队列；即使无信号也入队，以清除已解除的活跃状态。
        self._enqueue_weixin(signals)

        # earnings 日频任务（收盘后当日一次，异步分派不阻塞本轮 tick）
        self._maybe_dispatch_earnings()

    # ---------- earnings 日频调度 ----------

    def _maybe_dispatch_earnings(self) -> None:
        """收盘后（Asia/Shanghai 15:35 起）且当日未跑过时，派发 earnings 任务。"""
        if self.earnings_job is None:
            return
        from mommy_chaogu.earnings import daily as earnings_daily

        now = _utcnow()
        if not earnings_daily.should_run(now, self._last_earnings_run):
            return
        self._last_earnings_run = now.astimezone(earnings_daily.MARKET_TZ).date()
        self._earnings_task = asyncio.create_task(
            self._run_earnings_job(), name="earnings-daily-job"
        )
        _log.info("earnings daily job dispatched")

    async def _run_earnings_job(self) -> None:
        """跑 earnings pull+score+evaluate；信号走既有 SignalNotifier / 微信管道。"""
        job = self.earnings_job
        if job is None:
            return
        try:
            signals = await asyncio.to_thread(job)
        except Exception:
            _log.exception("earnings daily job failed")
            return
        if not signals:
            _log.info("earnings daily job completed: no signals")
            return
        _log.info("earnings daily job produced %d signals", len(signals))
        try:
            self.alerter.write_signals_log(signals)
        except Exception:
            _log.exception("earnings signals log write failed")
        if self.notifier:
            try:
                pushed = self.notifier.notify_batch(signals)
                if pushed:
                    self._pushed_signals.extend(pushed)
                    self._pushed_signals = self._pushed_signals[-100:]
            except Exception:
                _log.exception("notifier notify failed (earnings)")
        self._enqueue_weixin(signals)

    def _enqueue_weixin(self, signals: list[Any]) -> None:
        queue = self._weixin_queue
        if queue is None:
            return
        if queue.full():
            with contextlib.suppress(asyncio.QueueEmpty):
                queue.get_nowait()
        queue.put_nowait(list(signals))

    async def _run_weixin_worker(self) -> None:
        queue = self._weixin_queue
        sender = self.weixin_sender
        if queue is None or sender is None:
            return
        while True:
            signals = await queue.get()
            if signals is None:
                return
            try:
                await asyncio.to_thread(sender, signals)
            except Exception:
                _log.exception("Weixin notification delivery failed")

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
