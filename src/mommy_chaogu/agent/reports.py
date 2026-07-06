"""Agent 驱动的收盘日报。

替代 FlowReport 的 markdown 模板拼接，
用 LLM 读取结构化数据后生成有叙事逻辑的分析报告。

数据流：
    FlowService 拉资金流排行 → 结构化数据 → agent 生成报告文本
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from mommy_chaogu.agent.episodic_memory import EpisodicMemory
from mommy_chaogu.agent.service import AgentService

_log = logging.getLogger(__name__)


class AgentReportService:
    """用 agent 生成收盘日报。

    用法：
        agent = AgentService(ctx)
        svc = AgentReportService(agent, db_path=Path("data/watchlist.db"))
        text = svc.generate_daily_report(pool_name="semicon")
        print(text)
    """

    def __init__(self, agent: AgentService, db_path: Path | None = None) -> None:
        self._agent = agent
        self._memory: EpisodicMemory | None = None
        if db_path is not None:
            self._memory = EpisodicMemory(db_path)

    def generate_daily_report(
        self,
        pool_name: str = "semicon",
        board_code: str | None = None,
        board_name: str | None = None,
    ) -> str:
        """生成收盘日报。

        两种模式：
        1. pool 模式：从 flows 缓存读资金流排行（需要先 mommy-flows pull）
        2. board 模式：直接调板块成分股 API（不需要预热缓存）

        Args:
            pool_name: flows 池名 ("semicon" / "watchlist") 或 None
            board_code: 东财板块代码（如 "BK1106"），优先使用
            board_name: 板块中文名（用于报告标题）

        Returns:
            适合微信推送的分析文本（markdown，<2000 字）
        """
        if board_code:
            data = self._collect_board_data(board_code, board_name or board_code)
        else:
            data = self._collect_pool_data(pool_name)

        if not data:
            return "（暂无数据，请先运行 mommy-flows pull 拉取资金流数据）"

        prompt = self._build_prompt(data, board_name or pool_name)
        resp = self._agent.chat(prompt)

        if resp.tool_calls:
            _log.info(
                "daily report used %d tool calls in %d rounds",
                len(resp.tool_calls),
                resp.rounds,
            )

        self._record_analysis(data, board_name, pool_name)

        return resp.text

    def _collect_board_data(self, board_code: str, board_name: str) -> dict[str, Any]:
        """从板块成分股 API 收集数据（不需要预热缓存）。"""
        from mommy_chaogu.market_data.sector_api import fetch_sector_stocks

        stocks = fetch_sector_stocks(board_code, sort_by="change_pct", limit=100)

        if not stocks:
            return {}

        n_up = sum(1 for s in stocks if s["change_pct"] > 0)
        n_down = sum(1 for s in stocks if s["change_pct"] < 0)
        avg_pct = sum(s["change_pct"] for s in stocks) / len(stocks)
        total_amt = sum(s["amount"] for s in stocks) / 1e8
        total_main = sum(s["main_net"] for s in stocks) / 1e8

        # 按主力净流入排序
        by_main = sorted(stocks, key=lambda x: x["main_net"], reverse=True)
        top_inflow = by_main[:5]
        top_outflow = by_main[-5:]

        return {
            "board_name": board_name,
            "board_code": board_code,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "total_stocks": len(stocks),
            "up_count": n_up,
            "down_count": n_down,
            "avg_change_pct": round(avg_pct, 2),
            "total_amount_yi": round(total_amt, 0),
            "total_main_net_yi": round(total_main, 2),
            "top_inflow": [
                {
                    "code": s["code"],
                    "name": s["name"],
                    "change_pct": round(s["change_pct"], 2),
                    "price": round(s["price"], 2),
                    "main_net_wan": round(s["main_net"] / 1e4, 0),
                    "turnover_rate": round(s["turnover_rate"], 1) if s["turnover_rate"] else 0,
                    "pe": round(s["pe"], 1) if s["pe"] else 0,
                }
                for s in top_inflow
            ],
            "top_outflow": [
                {
                    "code": s["code"],
                    "name": s["name"],
                    "change_pct": round(s["change_pct"], 2),
                    "price": round(s["price"], 2),
                    "main_net_wan": round(s["main_net"] / 1e4, 0),
                    "turnover_rate": round(s["turnover_rate"], 1) if s["turnover_rate"] else 0,
                }
                for s in top_outflow
            ],
            "top_gainers": [
                {
                    "code": s["code"],
                    "name": s["name"],
                    "change_pct": round(s["change_pct"], 2),
                    "price": round(s["price"], 2),
                }
                for s in sorted(stocks, key=lambda x: x["change_pct"], reverse=True)[:5]
            ],
        }

    def _collect_pool_data(self, pool_name: str) -> dict[str, Any]:
        """从 flows 缓存读取资金流排行（需要先 mommy-flows pull）。"""
        from pathlib import Path

        from mommy_chaogu.flows.pool import build_pool
        from mommy_chaogu.flows.service import FlowService

        db_path = Path("data/watchlist.db")
        semicon_db = Path("data/semicon.db")

        pool = build_pool(
            name=pool_name,
            db_path=semicon_db if pool_name == "semicon" else db_path,
        )
        service = FlowService.from_default(db_path)

        # 当日排行
        top_in = service.top_today(pool, n=10, by="main_net", direction="in")
        top_out = service.top_today(pool, n=10, by="main_net", direction="out")

        if not top_in and not top_out:
            return {}

        def _fmt(s: Any) -> dict[str, Any]:
            return {
                "code": s.code,
                "name": s.name,
                "main_net_yi": round(float(s.main_net) / 1e8, 2),
                "main_net_ratio": float(s.main_net_ratio) if s.main_net_ratio else None,
                "period": s.period,
            }

        # 30 日历史排行
        try:
            top_30d_in = service.top_history(pool, days=30, n=5, by="main_net", direction="in")
            top_30d_out = service.top_history(pool, days=30, n=5, by="main_net", direction="out")
        except Exception:
            top_30d_in = []
            top_30d_out = []

        return {
            "pool_name": pool.describe(),
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "total_stocks": len(pool.codes()),
            "top_inflow_today": [_fmt(s) for s in top_in],
            "top_outflow_today": [_fmt(s) for s in top_out],
            "top_inflow_30d": [_fmt(s) for s in top_30d_in],
            "top_outflow_30d": [_fmt(s) for s in top_30d_out],
        }

    def _build_analysis_summary(self, data: dict[str, Any], is_sector: bool) -> str:
        """从结构化数据构造 ≤200 字的关键结论摘要。"""
        if is_sector:
            name = data.get("board_name", "")
            avg = data.get("avg_change_pct", 0)
            net = data.get("total_main_net_yi", 0)
            up = data.get("up_count", 0)
            down = data.get("down_count", 0)
            return f"{name} 均涨跌{avg}%，主力净流{net}亿，涨{up}只跌{down}只"
        # pool 模式
        pool = data.get("pool_name", "")
        top_in = data.get("top_inflow_today", [])
        top_name = top_in[0]["name"] if top_in else "无"
        top_amt = top_in[0].get("main_net_yi", 0) if top_in else 0
        return f"{pool} 主力净流入榜首：{top_name}({top_amt}亿)"

    def _record_analysis(
        self,
        data: dict[str, Any],
        board_name: str | None,
        pool_name: str,
    ) -> None:
        """将关键分析写入 episodic memory（db_path 为 None 时跳过）。"""
        if self._memory is None:
            return

        is_sector = bool(board_name or data.get("board_name"))
        if is_sector:
            name = board_name or data.get("board_name", "")
            scope = f"sector:{name}"
        else:
            scope = "market"

        summary = self._build_analysis_summary(data, is_sector)
        try:
            self._memory.write(
                event_type="analysis_record",
                scope=scope,
                summary=summary[:200],
                data=data,
                source="agent_report",
                trade_date=datetime.now().strftime("%Y-%m-%d"),
            )
        except Exception:
            _log.exception("write analysis_record to episodic memory failed")

    def _build_prompt(self, data: dict[str, Any], title: str) -> str:
        """构造给 agent 的数据 prompt。注入记忆上下文（已有认知 + 近期事件）。"""
        import json

        from mommy_chaogu.agent.prompt import REPORT_PROMPT_TEMPLATE

        data_str = json.dumps(data, ensure_ascii=False, indent=2)
        base_prompt = REPORT_PROMPT_TEMPLATE.format(data=data_str)

        # 注入记忆上下文（如果 agent 有 pipeline）
        pipeline = getattr(self._agent, "_pipeline", None)
        if pipeline is not None:
            memory_prompt = pipeline.build_prompt(query=title)
            # memory_prompt 是完整的 system prompt，我们取其中的记忆段落追加到报告 prompt
            from mommy_chaogu.agent.prompt import SYSTEM_PROMPT

            memory_section = (
                memory_prompt[len(SYSTEM_PROMPT) :]
                if memory_prompt.startswith(SYSTEM_PROMPT)
                else ""
            )
            if memory_section.strip():
                base_prompt += f"\n\n--- 记忆上下文 ---{memory_section}"

        return base_prompt
