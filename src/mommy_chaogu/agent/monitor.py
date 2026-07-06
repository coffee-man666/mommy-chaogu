"""AgentMonitor：LLM 驱动的盘中异动扫描。

设计：
- 低频（3-5 分钟一轮），不像 BackgroundService 那样 5s 轮询
- 先收集数据，一次性塞给 LLM（不是让 LLM 自己调工具，省 token）
- LLM 返回 JSON：有 alert 就推，没 alert 就跳过
- 复用现有 SignalNotifier 去重 + 推送管道

与现有系统的关系：
- BackgroundService（5s 快轮询 + 7 条硬规则）：继续跑，负责实时行情 + 涨停跌停硬告警
- AgentMonitor（3min 慢扫描）：额外一层，负责"语境感知的智能判断"
- 两者互不干扰，可以共存
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from mommy_chaogu.agent.episodic_memory import EpisodicMemory
from mommy_chaogu.agent.scan_prompt import SCAN_PROMPT_TEMPLATE
from mommy_chaogu.agent.service import AgentService
from mommy_chaogu.market_data.adapter import MarketDataAdapter
from mommy_chaogu.push import SignalNotifier
from mommy_chaogu.signals.types import Signal, SignalSeverity
from mommy_chaogu.watchlist.store import WatchlistStore

_log = logging.getLogger(__name__)


# ---------- 数据结构 ----------


@dataclass
class AgentAlert:
    """agent 判断出的一条告警。"""

    code: str
    name: str
    severity: str  # "warning" / "critical"
    message: str


@dataclass
class AgentScanResult:
    """一轮扫描的结果。"""

    timestamp: datetime
    n_stocks: int
    alerts: list[AgentAlert] = field(default_factory=list)
    summary: str = ""
    elapsed_seconds: float = 0.0
    pushed: list[str] = field(default_factory=list)  # 成功推送的 code 列表


# ---------- AgentMonitor ----------


class AgentMonitor:
    """LLM 驱动的盘中扫描器。

    用法：
        monitor = AgentMonitor(agent, adapter, watchlist, notifier)
        result = monitor.scan_once()  # 单次扫描
        monitor.run(max_seconds=19800)  # 持续运行
    """

    def __init__(
        self,
        agent: AgentService,
        adapter: MarketDataAdapter,
        watchlist_store: WatchlistStore,
        notifier: SignalNotifier | None = None,
        interval_seconds: float = 180.0,
        db_path: Path | None = None,
    ) -> None:
        self.agent = agent
        self.adapter = adapter
        self.watchlist = watchlist_store
        self.notifier = notifier
        self.interval = interval_seconds
        self._memory: EpisodicMemory | None = None
        if db_path is not None:
            self._memory = EpisodicMemory(db_path)

    # ============================================================
    # 数据收集
    # ============================================================

    def _collect_data(self) -> dict[str, Any]:
        """拉自选股数据，构造给 LLM 的结构化 payload。"""
        codes = self.watchlist.get_all_codes()
        if not codes:
            return {"timestamp": _now_str(), "stock_count": 0, "stocks": []}

        quotes = self.adapter.get_quotes(codes)

        stocks: list[dict[str, Any]] = []
        for q in quotes:
            flow = self._get_latest_flow(q.code)
            float_mcap = q.circulating_market_cap.amount if q.circulating_market_cap else None
            main_net_amount = flow.main_net.amount if flow else None
            bp = _calc_bp(main_net_amount, float_mcap)

            stocks.append(
                {
                    "code": q.code,
                    "name": q.name,
                    "price": float(q.price),
                    "change_pct": float(q.change_pct),
                    "volume_ratio": float(q.volume_ratio) if q.volume_ratio else 0,
                    "turnover_rate": float(q.turnover_rate) if q.turnover_rate else 0,
                    "main_net_wan": (
                        float(main_net_amount) / 1e4 if main_net_amount is not None else 0
                    ),
                    "circulating_market_cap_yi": (
                        float(float_mcap) / 1e8 if float_mcap is not None else 0
                    ),
                    "main_net_bp": bp,
                }
            )

        return {
            "timestamp": _now_str(),
            "stock_count": len(stocks),
            "stocks": stocks,
        }

    def _get_latest_flow(self, code: str) -> Any:
        """拉单只股票当日最新资金流，失败返回 None。"""
        try:
            flows = self.adapter.get_today_money_flow(code)
            if flows:
                return flows[-1]
        except Exception as e:
            _log.debug("get_today_money_flow(%s) failed: %s", code, e)
        return None

    # ============================================================
    # 单轮扫描
    # ============================================================

    def scan_once(self) -> AgentScanResult:
        """单轮扫描：收集数据 → LLM 判断 → 返回结果。"""
        t0 = datetime.now(UTC)

        # 1. 收集数据
        data = self._collect_data()
        if data["stock_count"] == 0:
            return AgentScanResult(
                timestamp=t0,
                n_stocks=0,
                summary="自选股为空，跳过扫描",
            )

        # 2. 构造 prompt
        data_str = json.dumps(data, ensure_ascii=False, indent=2)
        prompt = SCAN_PROMPT_TEMPLATE.format(data=data_str)

        # 3. LLM 判断（用 JSON mode）
        alerts, summary = self._ask_agent(prompt)

        # 4. 推送
        stocks_by_code = {s["code"]: s for s in data.get("stocks", [])}
        pushed = self._push_alerts(alerts, stocks_by_code=stocks_by_code)

        elapsed = (datetime.now(UTC) - t0).total_seconds()
        return AgentScanResult(
            timestamp=t0,
            n_stocks=data["stock_count"],
            alerts=alerts,
            summary=summary,
            elapsed_seconds=elapsed,
            pushed=pushed,
        )

    def _ask_agent(self, prompt: str) -> tuple[list[AgentAlert], str]:
        """调 LLM，解析 JSON 返回。注入记忆上下文。"""
        # 注入记忆（如果 agent 有 pipeline）
        pipeline = getattr(self.agent, "_pipeline", None)
        if pipeline is not None:
            memory_prompt = pipeline.build_prompt(query="盘中异动扫描")
            from mommy_chaogu.agent.prompt import SYSTEM_PROMPT

            memory_section = (
                memory_prompt[len(SYSTEM_PROMPT) :]
                if memory_prompt.startswith(SYSTEM_PROMPT)
                else ""
            )
            system_content = "你是一个 A 股盘中异动扫描器。只返回 JSON。" + memory_section
        else:
            system_content = "你是一个 A 股盘中异动扫描器。只返回 JSON。"

        try:
            resp = self.agent._client.chat.completions.create(
                model=self.agent._model,
                messages=[
                    {"role": "system", "content": system_content},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                response_format={"type": "json_object"},
            )
            text = resp.choices[0].message.content or ""
            return self._parse_scan_response(text)
        except Exception as e:
            _log.exception("agent scan failed: %s", e)
            return [], f"扫描失败: {e}"

    def _parse_scan_response(self, text: str) -> tuple[list[AgentAlert], str]:
        """解析 LLM 返回的 JSON。"""
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            _log.warning("agent returned non-JSON: %s", text[:200])
            return [], "LLM 返回格式异常"

        alerts: list[AgentAlert] = []
        for a in data.get("alerts", []):
            code = str(a.get("code", ""))
            name = str(a.get("name", ""))
            severity = str(a.get("severity", "warning"))
            message = str(a.get("message", ""))
            if code:
                alerts.append(
                    AgentAlert(
                        code=code,
                        name=name,
                        severity=severity if severity in ("warning", "critical") else "warning",
                        message=message,
                    )
                )

        summary = str(data.get("summary", ""))
        return alerts, summary

    # ============================================================
    # 推送
    # ============================================================

    def _push_alerts(
        self,
        alerts: list[AgentAlert],
        stocks_by_code: dict[str, dict[str, Any]] | None = None,
    ) -> list[str]:
        """构造 Signal 走现有 notifier 推送。返回成功推送的 code 列表。

        若 ``self._memory`` 不为 None，同时把每条告警写入 episodic memory。
        """
        if not alerts:
            return []

        pushed: list[str] = []
        for a in alerts:
            # 写入 episodic memory（db_path 为 None 时跳过）
            if self._memory is not None:
                stock = (stocks_by_code or {}).get(a.code, {})
                self._record_signal_event(a, stock)

            if not self.notifier:
                continue

            signal = Signal(
                timestamp=datetime.now(),
                code=a.code,
                name=a.name,
                rule_id="agent_scan",
                severity=SignalSeverity(a.severity),
                title=a.message[:60],
                detail=a.message,
                metrics={},
                trigger_value=Decimal("0"),
                threshold_value=Decimal("0"),
            )
            try:
                if self.notifier.notify_one(signal):
                    pushed.append(a.code)
                    _log.info("agent alert pushed: %s %s", a.code, a.name)
            except Exception:
                _log.exception("push alert failed: %s %s", a.code, a.name)
        return pushed

    def _record_signal_event(
        self,
        alert: AgentAlert,
        stock: dict[str, Any],
    ) -> None:
        """将单条告警写入 episodic memory。"""
        data = {
            "severity": alert.severity,
            "message": alert.message,
            "price": stock.get("price"),
            "change_pct": stock.get("change_pct"),
            "main_net_wan": stock.get("main_net_wan"),
            "volume_ratio": stock.get("volume_ratio"),
        }
        try:
            self._memory.write(
                event_type="signal_event",
                scope=f"stock:{alert.code}",
                code=alert.code,
                name=alert.name,
                summary=alert.message[:200],
                data=data,
                source="agent_monitor",
                tags=[alert.severity],
                trade_date=datetime.now().strftime("%Y-%m-%d"),
            )
        except Exception:
            _log.exception("write signal_event to episodic memory failed")

    # ============================================================
    # 持续循环（CLI 用）
    # ============================================================

    def run(self, max_seconds: float | None = None) -> int:
        """持续扫描循环。Ctrl+C 退出。返回跑的轮数。"""
        iteration = 0
        start = datetime.now(UTC)
        try:
            while True:
                if max_seconds is not None:
                    elapsed = (datetime.now(UTC) - start).total_seconds()
                    if elapsed >= max_seconds:
                        break

                result = self.scan_once()
                self._print_result(result, iteration)
                iteration += 1

                if max_seconds is not None:
                    elapsed = (datetime.now(UTC) - start).total_seconds()
                    if elapsed >= max_seconds:
                        break

                time.sleep(self.interval)
        except KeyboardInterrupt:
            print("\n[agent-monitor] Ctrl+C received, stopping...")
        return iteration

    async def run_async(self, stop_event: asyncio.Event) -> None:
        """asyncio 循环（Web 后台用）。"""
        while not stop_event.is_set():
            try:
                result = await asyncio.to_thread(self.scan_once)
                _log.info(
                    "agent scan: %d stocks, %d alerts, %.1fs",
                    result.n_stocks,
                    len(result.alerts),
                    result.elapsed_seconds,
                )
            except Exception:
                _log.exception("agent scan_once failed")

            with __import__("contextlib").suppress(TimeoutError):
                await asyncio.wait_for(
                    stop_event.wait(),
                    timeout=self.interval,
                )

    def _print_result(self, result: AgentScanResult, iteration: int) -> None:
        """CLI 输出。"""
        ts = result.timestamp.strftime("%H:%M:%S")
        n_alerts = len(result.alerts)
        alert_text = f"  🚨 {n_alerts} 条告警" if n_alerts else ""
        pushed_text = f"  ✅ 推送 {len(result.pushed)}" if result.pushed else ""
        print(
            f"[{ts}] scan #{iteration}  "
            f"{result.n_stocks} 只  "
            f"⏱ {result.elapsed_seconds:.1f}s{alert_text}{pushed_text}"
        )
        if result.summary:
            print(f"   📝 {result.summary}")
        for a in result.alerts:
            emoji = "🔴" if a.severity == "critical" else "⚠️ "
            pushed_tag = " ✅已推" if a.code in result.pushed else ""
            print(f"   {emoji} {a.code} {a.name:<10} {a.message}{pushed_tag}")


# ---------- 辅助函数 ----------


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _calc_bp(main_net: Decimal | None, float_mcap: Decimal | None) -> float | None:
    """计算主力净流入占流通市值的 bp（万分之几）。

    bp = main_net / float_market_cap × 10000
    """
    if main_net is None or float_mcap is None or float_mcap == 0:
        return None
    try:
        return round(float(main_net) / float(float_mcap) * 10000, 2)
    except (ValueError, TypeError, ZeroDivisionError):
        return None
