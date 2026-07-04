"""LLM 驱动的回测：用 market.db 里的真实历史数据喂给 LLM 做预测。

与 ``backtest_evolution.py``（规则引擎）的区别：
- 数据源：**离线**读 ``data/market.db`` 的 klines + flows 表，不联网拉数据
- 预测引擎：LLM（OpenAI 兼容接口，默认 deepseek），单轮 JSON 输出
- 额外追踪：**token 用量 + 估算成本**，衡量 LLM 回测的性价比

流程：
1. 从 market.db 读 K 线 + 资金流 → 2. 滑动窗口构造上下文喂 LLM
→ 3. 解析 JSON 预测 → 4. T+N 验证 → 5. 输出命中率 + token 报告

用法::
    uv run python scripts/backtest_llm.py
    uv run python scripts/backtest_llm.py --limit 5 --stocks 688981,002129
    uv run python scripts/backtest_llm.py --dry-run          # 不调 LLM，只打印上下文
    uv run python scripts/backtest_llm.py --horizon 3 --days 10

需要环境变量 ``DEEPSEEK_API_KEY``（或对应 provider 的 key）。
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mommy_chaogu.db_paths import MARKET_DB

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s %(message)s")
_log = logging.getLogger("backtest_llm")

# ============================================================
# 默认股票池（与 backtest_evolution.py 一致，便于横向对比；
# 命令行 --stocks 可覆盖）
# ============================================================

DEFAULT_STOCKS = [
    "688981",  # 中芯国际
    "002129",  # TCL中环
    "002475",  # 立讯精密
    "002594",  # 比亚迪
    "300750",  # 宁德时代
    "600519",  # 贵州茅台
    "000858",  # 五粮液
    "002747",  # 埃斯顿
    "300007",  # 汉威科技
    "603662",  # 柯力传感
]

# provider → (input ¥/1M tokens, output ¥/1M tokens)。
# 仅用于粗略成本估算，不代表实时报价。
_PRICING_CNY_PER_MTOKEN: dict[str, tuple[float, float]] = {
    "deepseek-chat": (1.0, 2.0),
    "deepseek-coder": (1.0, 2.0),
    "gpt-4o-mini": (1.0, 4.0),
    "gpt-4o": (18.0, 70.0),
    "moonshot-v1-8k": (12.0, 12.0),
    "glm-4.7": (2.0, 2.0),
}


# ============================================================
# token 用量追踪
# ============================================================


@dataclass
class TokenUsage:
    """累计 token 用量 + 估算成本。"""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    n_calls: int = 0
    n_errors: int = 0
    # 按 LLM 输出的 direction 计数（诊断用）
    by_direction: dict[str, int] = field(default_factory=dict)

    def add(self, usage: Any, model: str) -> None:
        """从 OpenAI response.usage 累加一次调用。"""
        if usage is None:
            return
        self.prompt_tokens += getattr(usage, "prompt_tokens", 0) or 0
        self.completion_tokens += getattr(usage, "completion_tokens", 0) or 0
        self.total_tokens += getattr(usage, "total_tokens", 0) or 0
        self.n_calls += 1

    @property
    def estimated_cost_cny(self) -> float:
        """按 model 估算人民币成本（元）。未知 model 按 deepseek-chat 兜底。"""
        rates = _PRICING_CNY_PER_MTOKEN.get(
            _current_model, _PRICING_CNY_PER_MTOKEN["deepseek-chat"]
        )
        return (
            self.prompt_tokens / 1_000_000 * rates[0]
            + self.completion_tokens / 1_000_000 * rates[1]
        )

    def summary(self) -> str:
        return (
            f"  调用 {self.n_calls} 次（失败 {self.n_errors}）\n"
            f"  prompt={self.prompt_tokens:,}  completion={self.completion_tokens:,}  "
            f"total={self.total_tokens:,} tokens\n"
            f"  估算成本 ≈ ¥{self.estimated_cost_cny:.4f}（model={_current_model}）"
        )


# 全局 model 记录（cost 估算用）
_current_model: str = "deepseek-chat"


# ============================================================
# 数据读取（market.db）
# ============================================================


def load_klines(conn: sqlite3.Connection, code: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT date, open, close, high, low, volume FROM klines WHERE code=? ORDER BY date",
        (code,),
    ).fetchall()
    return [
        {
            "date": r[0],
            "open": r[1],
            "close": r[2],
            "high": r[3],
            "low": r[4],
            "volume": r[5],
        }
        for r in rows
    ]


def load_flows(conn: sqlite3.Connection, code: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT date, main_net, ratio FROM flows WHERE code=? ORDER BY date",
        (code,),
    ).fetchall()
    return [{"date": r[0], "main_net": r[1], "ratio": r[2]} for r in rows]


# ============================================================
# 上下文构造 + LLM 预测
# ============================================================


_PREDICT_SYSTEM = (
    "你是 A 股短线分析助手。基于给定的历史 K 线和资金流数据，"
    "判断该股未来 5 个交易日的方向。只返回 JSON，不要任何额外文字。"
)

_PREDICT_USER_TMPL = """\
股票：{code} {name}
基准日：{date}（收盘价 {close:.2f}）

过去 {n} 个交易日数据（ oldest → latest ）：
{table}

请输出 JSON，严格遵循：
{{
  "direction": "bullish | bearish | neutral",
  "confidence": 0.0-1.0,
  "rationale": "一句话理由（<=40 字，引用上面看到的具体数字）"
}}

判断要点：
- 主力资金流 ratio（bp）方向与连续性：>5bp 偏多，<-5bp 偏空，10bp 以上是强信号
- 量价配合：放量上涨 / 缩量上涨 / 放量下跌
- 近期趋势：连续阳线还是阴线，有无破位
- 没有明确信号时给 neutral，不要硬猜
"""


def build_context_from_rows(
    klines: list[dict[str, Any]],
    flows: dict[str, dict[str, Any]],
    date: str,
    window: int,
) -> str | None:
    """构造截止 date 的过去 window 天数据表（含 volume）。"""
    dates = [k["date"] for k in klines]
    try:
        idx = dates.index(date)
    except ValueError:
        return None
    start = max(0, idx - window + 1)
    slice_klines = klines[start : idx + 1]
    if len(slice_klines) < 5:
        return None

    lines = ["date       close   chg%    vol        main_net       ratio_bp"]
    for i, k in enumerate(slice_klines):
        d = k["date"]
        close = k["close"]
        prev = slice_klines[i - 1]["close"] if i > 0 else close
        chg = (close - prev) / prev * 100 if prev else 0.0
        flow = flows.get(d)
        main_net = flow["main_net"] if flow else 0.0
        ratio_bp = flow["ratio"] if flow else 0.0
        lines.append(
            f"{d} {close:7.2f} {chg:+6.2f}  {k['volume']:10.0f} {main_net:14.0f} {ratio_bp:+8.2f}"
        )
    return "\n".join(lines)


def ask_llm(
    client: Any,
    model: str,
    system: str,
    user: str,
    usage: TokenUsage,
) -> str | None:
    """调一次 LLM，返回文本内容；失败记 error 并返回 None。"""
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.2,
            response_format={"type": "json_object"},
        )
    except Exception as e:
        _log.warning("LLM 调用失败: %s", e)
        usage.n_errors += 1
        return None

    usage.add(resp.usage, model)
    return resp.choices[0].message.content or ""


def parse_prediction(raw: str) -> dict[str, Any] | None:
    """解析 LLM 返回的 JSON 预测。"""
    if not raw:
        return None
    text = raw.strip()
    if text.startswith("```"):
        parts = text.split("\n")
        text = "\n".join(parts[1:-1]) if len(parts) > 2 else text
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        return None
    direction = str(obj.get("direction", "")).strip().lower()
    if direction not in ("bullish", "bearish", "neutral"):
        return None
    return {
        "direction": direction,
        "confidence": float(obj.get("confidence", 0.5) or 0.5),
        "rationale": str(obj.get("rationale", ""))[:200],
    }


# ============================================================
# 验证（与 backtest_evolution.py 的 verify 一致，便于横向对比）
# ============================================================


def verify(direction: str, entry: float, actual: float | None) -> tuple[str, float]:
    if actual is None:
        return ("expired", 0.0)
    change = (actual - entry) / entry * 100
    if direction == "neutral":
        # 中性：涨跌幅在 ±2% 内算 hit
        return ("hit", 1.0) if abs(change) <= 2 else ("missed", 0.0)
    if direction == "bullish":
        if change > 2:
            return ("hit", 1.0 if change > 5 else 0.7)
        if change > 0:
            return ("hit", 0.7)
        if change > -2:
            return ("missed", 0.3)
        return ("missed", 0.0)
    # bearish
    if change < -2:
        return ("hit", 1.0 if change < -5 else 0.7)
    if change < 0:
        return ("hit", 0.7)
    if change < 2:
        return ("missed", 0.3)
    return ("missed", 0.0)


# ============================================================
# 主流程
# ============================================================


def run(args: argparse.Namespace) -> int:
    global _current_model
    _current_model = args.model

    market_db = Path(args.market_db)
    if not market_db.exists():
        print(f"❌ 找不到 market.db: {market_db}", file=sys.stderr)
        return 2

    conn = sqlite3.connect(str(market_db))

    # 解析 provider / model
    provider = args.provider or os.environ.get("AGENT_PROVIDER", "deepseek")
    if provider == "deepseek":
        base_url = "https://api.deepseek.com"
        default_model = "deepseek-chat"
        env_key = "DEEPSEEK_API_KEY"
    elif provider == "openai":
        base_url = None
        default_model = "gpt-4o-mini"
        env_key = "OPENAI_API_KEY"
    elif provider == "kimi":
        base_url = "https://api.moonshot.cn/v1"
        default_model = "moonshot-v1-8k"
        env_key = "MOONSHOT_API_KEY"
    elif provider == "zai":
        base_url = "https://api.z.ai/api/coding/paas/v4"
        default_model = "glm-4.7"
        env_key = "ZAI_API_KEY"
    else:
        base_url = None
        default_model = "deepseek-chat"
        env_key = "DEEPSEEK_API_KEY"

    model = args.model or default_model
    _current_model = model

    # dry-run 不需要 key
    client = None
    if not args.dry_run:
        api_key = os.environ.get(env_key, "")
        if not api_key:
            print(
                f"❌ 未找到 API key。请设置环境变量 {env_key}（provider={provider}）。",
                file=sys.stderr,
            )
            return 2
        from openai import OpenAI

        client_kwargs: dict[str, Any] = {"api_key": api_key}
        if base_url:
            client_kwargs["base_url"] = base_url
        client = OpenAI(**client_kwargs)

    # 选股：取 market.db 里同时有 klines + flows 的股票
    codes_k = {r[0] for r in conn.execute("SELECT DISTINCT code FROM klines")}
    codes_f = {r[0] for r in conn.execute("SELECT DISTINCT code FROM flows")}
    available = sorted(codes_k & codes_f)

    wanted = set(args.stocks.split(",")) if args.stocks else set(DEFAULT_STOCKS)
    universe = [c for c in available if c in wanted]
    if not universe:
        # 用户给的代码都不在 db 里，退回到所有可用股票
        universe = available
    if args.limit and len(universe) > args.limit:
        universe = universe[: args.limit]

    # 加载序列
    print("=" * 70)
    print("  🤖 LLM 回测（离线数据 from market.db）")
    print(f"  provider={provider}  model={model}")
    print(f"  股票池 {len(universe)} 只  上下文窗口 {args.days} 天  horizon={args.horizon}")
    if args.dry_run:
        print("  ⚠️  --dry-run：不调用 LLM，只打印第一条上下文样例")
    print("=" * 70)

    series_by_code: dict[
        str, tuple[list[dict[str, Any]], dict[str, dict[str, Any]], list[str]]
    ] = {}
    names: dict[str, str] = {}
    all_dates: set[str] = set()
    for code in universe:
        klines = load_klines(conn, code)
        flows_list = load_flows(conn, code)
        flows = {f["date"]: f for f in flows_list}
        if len(klines) < args.days + args.horizon + 2:
            print(f"  ⏭️  {code} 数据不足（{len(klines)} 天），跳过")
            continue
        dates = [k["date"] for k in klines]
        series_by_code[code] = (klines, flows, dates)
        names[code] = code
        all_dates |= set(dates)
        print(f"  ✅ {code}  K线 {len(klines)} 天  资金流 {len(flows_list)} 天")

    conn.close()

    if not series_by_code:
        print("\n❌ 没有符合条件的股票，退出。", file=sys.stderr)
        return 1

    trading_dates = sorted(all_dates)
    # 留最后 horizon 天做验证
    backtest_dates = trading_dates[: len(trading_dates) - args.horizon]
    print(f"\n  回测日 {len(backtest_dates)} 天：{backtest_dates[0]} → {backtest_dates[-1]}")

    usage = TokenUsage()
    predictions: list[dict[str, Any]] = []

    # dry-run: 只打印第一条上下文样例就退出
    if args.dry_run:
        code0 = next(iter(series_by_code))
        klines0, flows0, dates0 = series_by_code[code0]
        # 优先挑一个有资金流的日期，更能体现上下文质量
        sample_date = next((d for d in dates0[args.days :] if d in flows0), dates0[args.days])
        ctx = build_context_from_rows(klines0, flows0, sample_date, args.days)
        print("\n── dry-run 上下文样例 ──")
        print(f"股票 {code0}  基准日 {sample_date}")
        print(ctx or "(无)")
        print("── end ──\n")
        return 0

    # 准备 PredictionTracker（独立 db，不污染 agent.db）
    from mommy_chaogu.agent.prediction_tracker import PredictionTracker

    db_path = Path(args.db)
    if db_path.exists():
        db_path.unlink()
    tracker = PredictionTracker(db_path)

    print("\n🔄 生成预测中...\n")

    for date in backtest_dates:
        for code, (klines, flows, dates) in series_by_code.items():
            if date not in dates:
                continue
            close = next((k["close"] for k in klines if k["date"] == date), None)
            if close is None:
                continue
            ctx = build_context_from_rows(klines, flows, date, args.days)
            if ctx is None:
                continue

            user_msg = _PREDICT_USER_TMPL.format(
                code=code, name=names[code], date=date, close=close, n=args.days, table=ctx
            )
            raw = ask_llm(client, model, _PREDICT_SYSTEM, user_msg, usage)
            if raw is None:
                continue
            pred = parse_prediction(raw)
            if pred is None:
                _log.warning("无法解析预测: %s", raw[:120])
                continue

            usage.by_direction[pred["direction"]] = usage.by_direction.get(pred["direction"], 0) + 1

            pid = tracker.create(
                code=code,
                name=names[code],
                prediction=pred["rationale"],
                direction=pred["direction"],
                timeframe=f"{args.horizon}d",
                entry_price=close,
                rationale=pred["rationale"],
            )
            predictions.append(
                {
                    "pid": pid,
                    "code": code,
                    "name": names[code],
                    "date": date,
                    "direction": pred["direction"],
                    "confidence": pred["confidence"],
                    "rationale": pred["rationale"],
                    "entry": close,
                }
            )

            if args.verbose:
                print(
                    f"  {date} {code} {pred['direction']:7s} "
                    f"conf={pred['confidence']:.2f}  {pred['rationale'][:40]}"
                )

        # 节流：每个回测日之间小睡，避免触发 provider 限流
        time.sleep(0.1)

    print(f"\n  生成 {len(predictions)} 条预测")

    # ============================================================
    # 验证
    # ============================================================
    print(f"\n✅ T+{args.horizon} 验证\n")

    for rec in predictions:
        klines, _flows, dates = series_by_code[rec["code"]]
        closes = {k["date"]: k["close"] for k in klines}
        try:
            idx = dates.index(rec["date"])
            future_idx = idx + args.horizon
            actual = closes[dates[future_idx]] if future_idx < len(dates) else None
        except (ValueError, IndexError):
            actual = None

        status, score = verify(rec["direction"], rec["entry"], actual)
        tracker.update_status(
            rec["pid"],
            status=status,
            actual_price=actual,
            accuracy_score=score,
        )
        rec["status"] = status
        rec["score"] = score
        rec["actual"] = actual

    # ============================================================
    # 报告
    # ============================================================
    print("=" * 70)
    print("  📊 LLM 回测报告")
    print(f"  {backtest_dates[0]} → {backtest_dates[-1]}")
    print("=" * 70)

    judged = [p for p in predictions if p["status"] in ("hit", "missed")]
    hits = [p for p in judged if p["status"] == "hit"]
    expired = [p for p in predictions if p["status"] == "expired"]
    hit_rate = len(hits) / len(judged) if judged else 0.0

    print("\n📈 命中率")
    print(f"  总预测: {len(predictions)}")
    print(f"  ✅ 命中: {len(hits)}  ❌ 失误: {len(judged) - len(hits)}  ⏰ 过期: {len(expired)}")
    print(f"  命中率: {hit_rate:.0%}" + (f"（排除 {len(expired)} 条过期）" if expired else ""))

    # 分方向
    print("\n📊 分方向")
    for d in ("bullish", "bearish", "neutral"):
        sub = [p for p in judged if p["direction"] == d]
        if sub:
            h = sum(1 for p in sub if p["status"] == "hit")
            print(f"  {d:8s}: {h}/{len(sub)} ({h / len(sub):.0%})")

    # 置信度分组
    print("\n📊 分置信度")
    for lo, hi, label in [
        (0.0, 0.4, "低 (<0.4)"),
        (0.4, 0.7, "中 (0.4-0.7)"),
        (0.7, 1.01, "高 (>=0.7)"),
    ]:
        sub = [p for p in judged if lo <= p["confidence"] < hi]
        if sub:
            h = sum(1 for p in sub if p["status"] == "hit")
            print(f"  {label:14s}: {h}/{len(sub)} ({h / len(sub):.0%})")

    # token 用量
    print("\n💰 token 用量")
    print(usage.summary())
    if usage.by_direction:
        dist = ", ".join(f"{k}={v}" for k, v in sorted(usage.by_direction.items()))
        print(f"  方向分布: {dist}")

    # 与规则引擎对比（如果有进化回测的 db）
    print("\n🆚 对比参考（规则引擎 backtest_evolution.py 基线：53% 命中率）")
    print(f"  LLM: {hit_rate:.0%}  vs  规则: 53%")

    # 样例
    print("\n📝 预测样例（前 5 条）")
    for p in predictions[:5]:
        chg = ""
        if p["actual"]:
            chg = f" ({(p['actual'] - p['entry']) / p['entry'] * 100:+.1f}%)"
        emoji = "✅" if p["status"] == "hit" else "❌" if p["status"] == "missed" else "⏰"
        print(
            f"  {emoji} {p['date']} {p['code']} {p['direction']:7s} conf={p['confidence']:.2f}{chg}"
        )
        print(f"      {p['rationale'][:60]}")

    print(f"\n{'=' * 70}")
    print("  ✅ LLM 回测完成")
    print(f"  {len(predictions)} 条预测 → {len(hits)} 命中 → 命中率 {hit_rate:.0%}")
    print(usage.summary())
    print(f"  预测已写入 {db_path}")
    print("=" * 70)
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="LLM 驱动的回测（离线读 market.db，调 LLM 做预测）")
    p.add_argument("--market-db", default=str(MARKET_DB), help="market.db 路径")
    p.add_argument("--db", default="data/llm_backtest.db", help="回测预测输出 db")
    p.add_argument("--stocks", default="", help="逗号分隔的股票代码（默认用内置池）")
    p.add_argument("--limit", type=int, default=0, help="限制股票数量（0=不限）")
    p.add_argument("--days", type=int, default=10, help="上下文窗口天数（默认 10）")
    p.add_argument("--horizon", type=int, default=5, help="验证 horizon 天数（默认 5）")
    p.add_argument("--model", default="deepseek-chat", help="LLM 模型名")
    p.add_argument("--provider", default=None, help="provider: deepseek/openai/kimi")
    p.add_argument("--dry-run", action="store_true", help="不调 LLM，只打印上下文样例")
    p.add_argument("--verbose", action="store_true", help="打印每条预测")
    return p.parse_args(argv)


if __name__ == "__main__":
    sys.exit(run(parse_args()))
