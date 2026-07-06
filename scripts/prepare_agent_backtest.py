"""Agent 原生回测数据准备：从 market.db 抽取数据包供 coding agent 直接分析。

与 ``backtest_llm.py``（调外部 API）不同，这个脚本生成的 JSON 数据包可以直接喂给
coding agent（如 kimi-code / Cursor / Claude Code），让 agent 自身的 LLM 能力
完成分析 + 预测，不需要任何外部 API key。

流程：
1. 从 market.db 读 K 线 + 资金流，从 reference.db 读股票名称 + 子行业
2. 按回测日期抽取每只股票的前 N 天上下文
3. 输出两个 JSON：
   - agent_backtest_data.json     — 分析用的数据包（不含未来答案）
   - agent_backtest_answers.json  — T+5 收盘价（验证用，分开存放防止 look-ahead bias）

用法::

    uv run python scripts/prepare_agent_backtest.py
    uv run python scripts/prepare_agent_backtest.py --stocks 002129,002156 --dates 2026-06-04,2026-06-08
    uv run python scripts/prepare_agent_backtest.py --output-dir /tmp/my_backtest
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

# ============================================================
# 默认配置
# ============================================================

DEFAULT_STOCKS = [
    "002129",  # TCL中环（材料）
    "002156",  # 通富微电（封测）
    "002049",  # 紫光国微（FPGA）
    "300346",  # 南大光电（材料）
    "000021",  # 深科技（封测）
]

DEFAULT_DATES = [
    "2026-06-04",
    "2026-06-08",
    "2026-06-12",
    "2026-06-18",
    "2026-06-22",
]

CONTEXT_KLINE_DAYS = 10  # 每次预测看前 N 个交易日的 K 线
VERIFY_HORIZON = 5  # T+N 验证天数（交易日）


def get_stock_names(codes: list[str], ref_db: Path) -> dict[str, tuple[str, str]]:
    """从 reference.db 取股票名称 + 子行业。Returns {code: (name, subcategory)}."""
    conn = sqlite3.connect(str(ref_db))
    cur = conn.cursor()
    result: dict[str, tuple[str, str]] = {}
    for code in codes:
        cur.execute("SELECT name, subcategory FROM stocks WHERE code = ?", (code,))
        row = cur.fetchone()
        if row:
            result[code] = (row[0], row[1] or "")
        else:
            result[code] = (code, "")
    conn.close()
    return result


def get_all_trading_dates(market_db: Path) -> list[str]:
    """获取所有交易日（从 klines 表 distinct date）。"""
    conn = sqlite3.connect(str(market_db))
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT date FROM klines ORDER BY date")
    dates = [row[0] for row in cur.fetchall()]
    conn.close()
    return dates


def load_klines(market_db: Path, code: str) -> list[dict[str, Any]]:
    """加载某只股票的全部 K 线，按日期排序。"""
    conn = sqlite3.connect(str(market_db))
    cur = conn.cursor()
    cur.execute(
        "SELECT date, open, close, high, low, volume FROM klines WHERE code = ? ORDER BY date",
        (code,),
    )
    rows = cur.fetchall()
    conn.close()

    klines: list[dict[str, Any]] = []
    prev_close: float | None = None
    for date, o, c, h, low, vol in rows:
        change_pct = ((c - prev_close) / prev_close * 100) if prev_close else 0.0
        klines.append(
            {
                "date": date,
                "open": round(o, 2),
                "close": round(c, 2),
                "high": round(h, 2),
                "low": round(low, 2),
                "volume": int(vol) if vol else 0,
                "change_pct": round(change_pct, 2),
            }
        )
        prev_close = c
    return klines


def load_flows(market_db: Path, code: str) -> list[dict[str, Any]]:
    """加载某只股票的全部资金流数据，按日期排序。"""
    conn = sqlite3.connect(str(market_db))
    cur = conn.cursor()
    cur.execute(
        "SELECT date, main_net, ratio FROM flows WHERE code = ? ORDER BY date",
        (code,),
    )
    rows = cur.fetchall()
    conn.close()

    return [
        {
            "date": date,
            "main_net": round(main_net, 0) if main_net else 0,
            "ratio_bp": round(ratio, 1) if ratio else 0.0,
        }
        for date, main_net, ratio in rows
    ]


def build_context(
    code: str,
    name: str,
    subcategory: str,
    all_klines: list[dict[str, Any]],
    all_flows: list[dict[str, Any]],
    pred_date: str,
    all_dates: list[str],
) -> dict[str, Any] | None:
    """为某个 (股票, 预测日) 组合构建上下文数据包。"""

    # 找预测日在交易日列表中的位置
    if pred_date not in all_dates:
        return None
    pred_idx = all_dates.index(pred_date)

    # 前 N 个交易日的 K 线（不包含预测日本身）
    start_idx = max(0, pred_idx - CONTEXT_KLINE_DAYS)
    context_klines = [
        k for k in all_klines if start_idx <= all_dates.index(k["date"]) < pred_idx + 1
    ]
    # 包含预测日当天（agent 能看到当天收盘数据）
    context_klines = [k for k in all_klines if k["date"] <= pred_date][-CONTEXT_KLINE_DAYS:]

    # 预测日及之前的资金流
    context_flows = [f for f in all_flows if f["date"] <= pred_date]

    # T+5 收盘价（答案，不放在数据包里）
    future_idx = pred_idx + VERIFY_HORIZON
    future_close = None
    future_date = None
    if future_idx < len(all_dates):
        future_date = all_dates[future_idx]
        for k in all_klines:
            if k["date"] == future_date:
                future_close = k["close"]
                break

    entry_close = None
    for k in all_klines:
        if k["date"] == pred_date:
            entry_close = k["close"]
            break

    return {
        "code": code,
        "name": name,
        "subcategory": subcategory,
        "date": pred_date,
        "entry_price": entry_close,
        "context_klines": context_klines,
        "context_flows": context_flows,
        # answer 单独存
        "_future_date": future_date,
        "_future_close": future_close,
    }


def run(args: argparse.Namespace) -> int:
    market_db = Path(args.market_db)
    ref_db = Path(args.ref_db)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    stocks = args.stocks.split(",") if args.stocks else DEFAULT_STOCKS
    pred_dates = args.dates.split(",") if args.dates else DEFAULT_DATES

    all_dates = get_all_trading_dates(market_db)
    print(f"交易日范围：{all_dates[0]} → {all_dates[-1]}（{len(all_dates)} 天）")

    stock_info = get_stock_names(stocks, ref_db)
    print(f"选股：{', '.join(f'{c}({stock_info[c][0]})' for c in stocks)}")
    print(f"预测日期：{', '.join(pred_dates)}")
    print(
        f"每只股票 {len(pred_dates)} 个预测点 × {len(stocks)} 只 = {len(pred_dates) * len(stocks)} 条预测"
    )

    data_package: list[dict[str, Any]] = []
    answers: list[dict[str, Any]] = {}

    for code in stocks:
        name, subcategory = stock_info[code]
        all_klines = load_klines(market_db, code)
        all_flows = load_flows(market_db, code)

        if not all_klines:
            print(f"  ⚠️ {code} 无 K 线数据，跳过")
            continue

        if not all_flows:
            print(f"  ⚠️ {code} 无资金流数据，K 线可用但分析质量会降低")

        for pred_date in pred_dates:
            ctx = build_context(
                code, name, subcategory, all_klines, all_flows, pred_date, all_dates
            )
            if ctx is None:
                print(f"  ⚠️ {code} 在 {pred_date} 无数据，跳过")
                continue

            # 分离答案
            future_close = ctx.pop("_future_close")
            future_date = ctx.pop("_future_date")
            entry_price = ctx["entry_price"]

            data_package.append(ctx)
            answers[f"{code}_{pred_date}"] = {
                "code": code,
                "name": name,
                "date": pred_date,
                "entry_price": entry_price,
                "future_date": future_date,
                "future_close": future_close,
                "change_pct": (
                    round((future_close - entry_price) / entry_price * 100, 2)
                    if future_close and entry_price
                    else None
                ),
            }

            flow_summary = (
                f"{len(ctx['context_flows'])} 天资金流" if ctx["context_flows"] else "无资金流"
            )
            print(f"  ✓ {code} {name} @ {pred_date} — 入场价 {entry_price} — {flow_summary}")

    # 写文件
    data_path = output_dir / "agent_backtest_data.json"
    answers_path = output_dir / "agent_backtest_answers.json"

    with open(data_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "meta": {
                    "description": "Agent 原生回测数据包 — 不含未来答案，供 coding agent 直接分析",
                    "stocks": len(stocks),
                    "dates": len(pred_dates),
                    "total_predictions": len(data_package),
                    "context_kline_days": CONTEXT_KLINE_DAYS,
                    "verify_horizon": VERIFY_HORIZON,
                },
                "predictions_needed": data_package,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )

    with open(answers_path, "w", encoding="utf-8") as f:
        json.dump(answers, f, ensure_ascii=False, indent=2)

    print(f"\n✅ 数据包写入 {data_path}")
    print(f"✅ 答案文件写入 {answers_path}")
    print(f"   共 {len(data_package)} 条预测待分析")

    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Agent 原生回测数据准备")
    parser.add_argument("--market-db", default="data/market.db", help="market.db 路径")
    parser.add_argument("--ref-db", default="data/reference.db", help="reference.db 路径")
    parser.add_argument("--output-dir", default="/tmp", help="输出目录")
    parser.add_argument("--stocks", default="", help="逗号分隔的股票代码（默认 5 只）")
    parser.add_argument("--dates", default="", help="逗号分隔的预测日期（默认 5 个）")
    args = parser.parse_args()
    sys.exit(run(args))


if __name__ == "__main__":
    main()
