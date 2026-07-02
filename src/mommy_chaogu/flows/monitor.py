"""FlowMonitor：资金流持续轮询 + ratio-based 异动检测。

单轮 tick：
1. 拉 quote（拿流通市值）
2. 拉 today_money_flow（拿主力净）
3. 构造 StockSnapshot
4. 与上一轮 ratio 对比，按 rules 评估
5. 写日志

安全机制：
- 单只失败不中断
- 连续 N 轮失败率 > 50% → 写告警日志
- 进程被杀重启时，状态可持久化到 .flow_monitor_state.json
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from mommy_chaogu.flows.pool import PoolSource
from mommy_chaogu.flows.service import FlowService
from mommy_chaogu.flows.signals import (
    FlowRule,
    FlowSignal,
    StockSnapshot,
    default_rules,
    evaluate,
)

_log = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass
class TickResult:
    """一轮 tick 的结果。"""

    iteration: int
    timestamp: datetime
    n_codes: int
    n_ok: int
    n_failed: int
    signals: list[FlowSignal]
    elapsed_seconds: float


class FlowMonitor:
    """持续轮询监控器。"""

    def __init__(
        self,
        pool: PoolSource,
        service: FlowService,
        *,
        interval_seconds: float = 300.0,
        rules: list[FlowRule] | None = None,
        state_path: Path | None = None,
        log_path: Path | None = None,
    ) -> None:
        self.pool = pool
        self.service = service
        self.interval = interval_seconds
        self.rules = rules or default_rules()
        self.state_path = state_path  # 状态持久化
        self.log_path = log_path  # 信号日志
        # 运行时状态
        self._last_ratios: dict[str, Decimal] = {}
        self._consecutive_high_failure = 0  # 连续高失败率轮数

    # ============================================================
    # 单轮
    # ============================================================

    def tick(self, iteration: int = 0) -> TickResult:
        """执行一轮。"""
        t0 = _utcnow()
        snap: list[StockSnapshot] = []
        n_ok = n_failed = 0

        # 1. 拿市值
        codes = self.pool.codes()
        mcaps = self.service.get_market_caps(codes)

        # 2. 拿 today 资金流
        for code in codes:
            try:
                flows = self.service.adapter.get_today_money_flow(code)
            except Exception as e:
                _log.warning("get_today_money_flow(%s) failed: %s", code, e)
                n_failed += 1
                continue
            if not flows:
                n_failed += 1
                continue
            # 最新一条
            last = flows[-1]
            mcap_tuple = mcaps.get(code)
            if mcap_tuple is None:
                n_failed += 1
                continue
            name = mcap_tuple[0]
            float_mcap = mcap_tuple[1]
            if float_mcap is None or float_mcap == 0:
                n_failed += 1
                continue
            snap.append(
                StockSnapshot(
                    code=code,
                    name=name,
                    main_net=last.main_net.amount,
                    float_market_cap=float_mcap,
                )
            )
            n_ok += 1

        # 3. 评估信号
        signals = evaluate(snap, self._last_ratios, self.rules)

        # 4. 更新状态
        self._last_ratios = {s.code: s.ratio for s in snap}

        # 5. 失败率统计
        total = n_ok + n_failed
        if total > 0 and n_failed / total > 0.5:
            self._consecutive_high_failure += 1
        else:
            self._consecutive_high_failure = 0

        return TickResult(
            iteration=iteration,
            timestamp=t0,
            n_codes=len(codes),
            n_ok=n_ok,
            n_failed=n_failed,
            signals=signals,
            elapsed_seconds=(_utcnow() - t0).total_seconds(),
        )

    # ============================================================
    # 主循环
    # ============================================================

    def run(
        self,
        *,
        max_iterations: int | None = None,
        max_seconds: float | None = None,
    ) -> int:
        """持续轮询。Ctrl+C 优雅退出。返回跑的轮数。"""
        self._load_state()
        iteration = 0
        start = _utcnow()
        try:
            while True:
                if max_iterations is not None and iteration >= max_iterations:
                    break
                if max_seconds is not None:
                    elapsed = (_utcnow() - start).total_seconds()
                    if elapsed >= max_seconds:
                        break

                result = self.tick(iteration=iteration)
                self._on_tick(result)
                iteration += 1

                if max_iterations is not None and iteration >= max_iterations:
                    break
                if max_seconds is not None:
                    elapsed = (_utcnow() - start).total_seconds()
                    if elapsed >= max_seconds:
                        break
                time.sleep(self.interval)
        except KeyboardInterrupt:
            print("\n[monitor] Ctrl+C received, stopping...")
        finally:
            self._save_state()
        return iteration

    # ============================================================
    # 回调 / 日志
    # ============================================================

    def _on_tick(self, result: TickResult) -> None:
        """每轮处理：写日志 + 打印。"""
        # 1. 进度行（stdout）
        ratio_pct = result.n_ok / result.n_codes * 100 if result.n_codes else 0
        n_sig = len(result.signals)
        sig_text = f"  🚨 {n_sig} 条信号" if n_sig else ""
        fail_text = (
            f"  ⚠️ 连续 {self._consecutive_high_failure} 轮高失败率"
            if self._consecutive_high_failure >= 3
            else ""
        )
        print(
            f"[{result.timestamp:%H:%M:%S}] iter={result.iteration}  "
            f"{result.n_ok}/{result.n_codes} ({ratio_pct:.0f}%)  "
            f"⏱ {result.elapsed_seconds:.1f}s{sig_text}{fail_text}"
        )
        for s in result.signals:
            print(f"   {s.format()}")

        # 2. 信号日志
        if self.log_path and result.signals:
            self._write_signals_log(result.signals, result.timestamp)

    def _write_signals_log(self, signals: list[FlowSignal], ts: datetime) -> None:
        assert self.log_path is not None
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as f:
            for s in signals:
                f.write(f"[{ts:%Y-%m-%d %H:%M:%S}] {s.format()}\n")

    # ============================================================
    # 状态持久化
    # ============================================================

    def _load_state(self) -> None:
        if self.state_path is None or not self.state_path.exists():
            return
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
            self._last_ratios = {k: Decimal(v) for k, v in data.get("last_ratios", {}).items()}
        except Exception as e:
            _log.warning("load state failed: %s", e)

    def _save_state(self) -> None:
        if self.state_path is None:
            return
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "last_ratios": {k: str(v) for k, v in self._last_ratios.items()},
                "saved_at": _utcnow().isoformat(),
            }
            self.state_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception as e:
            _log.warning("save state failed: %s", e)
