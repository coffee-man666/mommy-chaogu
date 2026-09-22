"""回测工具域：把确定性回放引擎暴露给外部 Agent。

`run_backtest` 包装 ``backtest/engine.py`` 的 flow_in_spike 信号回放（主力
净流入占比 > 5bp → 买入持有 N 天，含往返交易成本）。诚实边界（产品原则
#6）：结果受本地缓存数据覆盖限制，流通市值取报价缓存存在前视近似——工具
描述与返回体都把 caveats 前置，属**探索性评估**而非严格意义的真实回测。

纯确定性计算、只读公共行情缓存，与 market-only 边界一致（加入
``MARKET_ONLY_BASE_TOOLS``）。
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from mommy_chaogu.agent.tools.base import ToolContext, ToolDef, ToolHandler, _clamp_int, _json
from mommy_chaogu.backtest.engine import BacktestEngine
from mommy_chaogu.codes import A_SHARE_CODE_PATTERN

#: 回测样本明细的返回上限（完整明细体积大，抽样给 agent 看趋势即可）
MAX_SIGNAL_SAMPLES = 20

DEFS: list[ToolDef] = [
    ToolDef(
        name="run_backtest",
        description=(
            "回放 flow_in_spike 信号规则：每日主力净流入÷流通市值 > 5bp 视为买入"
            "信号，持有 N 天后按净收益（扣往返成本）统计胜率/平均收益/回撤/夏普。"
            "属探索性评估而非严格回测：只读本地缓存的历史资金流与 K 线（数据不足时"
            "返回 message 提示先回填），流通市值取当前报价缓存存在前视近似——"
            "返回体的 caveats 必须向用户展示。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "codes": {
                    "type": "array",
                    "items": {"type": "string", "pattern": A_SHARE_CODE_PATTERN},
                    "description": "股票代码列表，最多 50 只",
                },
                "start_date": {
                    "type": "string",
                    "pattern": "^\\d{4}-\\d{2}-\\d{2}$",
                    "description": "起始日期 YYYY-MM-DD",
                },
                "end_date": {
                    "type": "string",
                    "pattern": "^\\d{4}-\\d{2}-\\d{2}$",
                    "description": "结束日期 YYYY-MM-DD",
                },
                "hold_days": {
                    "type": "integer",
                    "description": "持有天数（默认 3，1-60）",
                    "default": 3,
                    "minimum": 1,
                    "maximum": 60,
                },
                "include_costs": {
                    "type": "boolean",
                    "description": "是否扣减往返交易成本（默认 true；false 为毛收益口径）",
                    "default": True,
                },
            },
            "required": ["codes", "start_date", "end_date"],
        },
    ),
]


def _handle_run_backtest(ctx: ToolContext, args: dict[str, Any]) -> str:
    db_path = ctx.resolved_market_db
    if db_path is None:
        return _json({"error": "行情缓存未配置（market_db is None），无法回测"})

    raw_codes = args.get("codes", [])
    if isinstance(raw_codes, str):
        raw_codes = [raw_codes]
    if not isinstance(raw_codes, list) or not raw_codes:
        return _json({"error": "codes 必须是非空股票代码列表"})
    codes = [str(code) for code in raw_codes if str(code).isdigit()][:50]
    if not codes:
        return _json({"error": "没有有效的 A 股代码"})

    start_date = str(args.get("start_date", ""))
    end_date = str(args.get("end_date", ""))
    if len(start_date) != 10 or len(end_date) != 10:
        return _json({"error": "start_date / end_date 必须是 YYYY-MM-DD"})

    hold_days = _clamp_int(args.get("hold_days", 3), 3, 1, 60)
    include_costs = args.get("include_costs") is not False

    engine = BacktestEngine(db_path)
    result = engine.run(
        codes,
        start_date,
        end_date,
        hold_days=hold_days,
        costs=_default_costs() if include_costs else None,
    )
    payload = asdict(result)
    payload["signals"] = payload.pop("signals_detail", [])[:MAX_SIGNAL_SAMPLES]
    payload["signal_samples"] = len(payload["signals"])
    payload["hold_days"] = hold_days
    return _json(payload)


def _default_costs() -> Any:
    """默认成本模型（延迟 import 保持工具域零启动成本）。"""
    from mommy_chaogu.backtest.costs import DEFAULT_COSTS

    return DEFAULT_COSTS


HANDLERS: dict[str, ToolHandler] = {
    "run_backtest": _handle_run_backtest,
}
