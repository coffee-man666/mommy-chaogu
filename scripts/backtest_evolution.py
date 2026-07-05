"""30 天回测式进化测试：用真实历史数据模拟 agent 预测 → 验证 → 进化闭环。

数据源：
- 腾讯日 K 线（web.ifzq.gtimg.cn）— 24 天 OHLCV
- 东财历史资金流（efinance adapter）— 21 天主力净流入 + ratio
- 东财公告（np-anotice-stock.eastmoney.com）

流程：
1. 拉数据 → 2. 滑动窗口生成预测 → 3. T+5 验证 → 4. 知识提炼 → 5. 输出报告

用法：
    uv run python scripts/backtest_evolution.py
    uv run python scripts/backtest_evolution.py --db /tmp/backtest.db  # 指定 db
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import requests
from backtest_stats import compute_buyhold_baseline, format_hit_rate

from mommy_chaogu.backtest.scoring import score_direction
from mommy_chaogu.db_paths import AGENT_DB

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s %(message)s")
_log = logging.getLogger(__name__)

# ============================================================
# 股票池
# ============================================================

STOCKS = [
    ("603662", "柯力传感", "sh"),
    ("688981", "中芯国际", "sh"),
    ("002129", "TCL中环", "sz"),
    ("300750", "宁德时代", "sz"),
    ("002594", "比亚迪", "sz"),
    ("002475", "立讯精密", "sz"),
    ("600519", "贵州茅台", "sh"),
    ("000858", "五粮液", "sz"),
    ("002747", "埃斯顿", "sz"),
    ("300007", "汉威科技", "sz"),
]

# ============================================================
# 数据拉取
# ============================================================


def fetch_tencent_daily(code: str, market: str) -> list[dict[str, Any]]:
    """拉腾讯日 K 线。

    Returns:
        [{date: "2026-06-04", open, close, high, low, volume}, ...]
    """
    tcode = f"{market}{code}"
    url = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
    params = {"param": f"{tcode},day,2026-06-01,2026-07-10,30,qfq"}

    try:
        r = requests.get(url, params=params, timeout=15)
        data = r.json()
        stock_data = data.get("data", {}).get(tcode, {})
        rows = stock_data.get("day", stock_data.get("qfqday", []))

        result = []
        for row in rows:
            result.append(
                {
                    "date": row[0],
                    "open": float(row[1]),
                    "close": float(row[2]),
                    "high": float(row[3]),
                    "low": float(row[4]),
                    "volume": float(row[5]) if len(row) > 5 else 0,
                }
            )
        return result
    except Exception as e:
        print(f"  ⚠️  腾讯 K线 {code} 失败: {e}")
        return []


def fetch_efinance_history(code: str) -> list[dict[str, Any]]:
    """拉东财历史资金流。

    Returns:
        [{date: "2026-06-04", main_net: float, ratio: float}, ...]
    """
    try:
        from mommy_chaogu.market_data.efinance_adapter import EfinanceAdapter

        adapter = EfinanceAdapter()
        flows = adapter.get_history_money_flow(code)
        if not flows:
            return []

        result = []
        for f in flows:
            date_str = f.timestamp.strftime("%Y-%m-%d") if f.timestamp else ""
            main_net = float(f.main_net.amount) if f.main_net else 0.0
            ratio = float(f.main_net_ratio) if f.main_net_ratio else 0.0
            result.append({"date": date_str, "main_net": main_net, "ratio": ratio})

        return result
    except Exception as e:
        print(f"  ⚠️  东财资金流 {code} 失败: {e}")
        return []


def fetch_announcements(code: str) -> list[dict[str, str]]:
    """拉东财公告。"""
    url = "https://np-anotice-stock.eastmoney.com/api/security/ann"
    params = {
        "sr": "-1",
        "page_size": 5,
        "page_index": 1,
        "ann_type": "A",
        "stock_list": code,
        "f_node": 0,
        "s_node": 0,
    }

    try:
        r = requests.get(url, params=params, timeout=10)
        if r.status_code != 200:
            return []
        data = r.json()
        items = data.get("data", {}).get("list", [])
        return [
            {"title": item.get("title", ""), "date": item.get("notice_date", "")[:10]}
            for item in items
        ]
    except Exception:
        return []


# ============================================================
# 数据组织
# ============================================================


class StockData:
    """单只股票的历史数据。"""

    def __init__(self, code: str, name: str) -> None:
        self.code = code
        self.name = name
        self.klines: list[dict[str, Any]] = []  # 按 date 排序
        self.flows: list[dict[str, Any]] = []
        self.date_set: set[str] = set()

        # 索引
        self._close_by_date: dict[str, float] = {}
        self._flow_by_date: dict[str, dict[str, Any]] = {}
        self._prev_close_by_date: dict[str, float] = {}

    def build(self) -> None:
        """构建索引。"""
        self.klines.sort(key=lambda x: x["date"])
        self.flows.sort(key=lambda x: x["date"])
        self.date_set = {k["date"] for k in self.klines}

        for k in self.klines:
            self._close_by_date[k["date"]] = k["close"]

        # 前一日收盘价
        for i, k in enumerate(self.klines):
            if i > 0:
                self._prev_close_by_date[k["date"]] = self.klines[i - 1]["close"]

        for f in self.flows:
            self._flow_by_date[f["date"]] = f

    def get_close(self, date: str) -> float | None:
        return self._close_by_date.get(date)

    def get_prev_close(self, date: str) -> float | None:
        return self._prev_close_by_date.get(date)

    def get_flow(self, date: str) -> dict[str, Any] | None:
        return self._flow_by_date.get(date)

    def get_trading_dates(self) -> list[str]:
        return sorted(self.date_set)

    def get_future_close(self, date: str, days_ahead: int) -> float | None:
        """获取 date 后第 N 个交易日的收盘价。"""
        dates = self.get_trading_dates()
        try:
            idx = dates.index(date)
            future_idx = idx + days_ahead
            if future_idx < len(dates):
                return self._close_by_date[dates[future_idx]]
        except (ValueError, IndexError):
            pass
        return None


# ============================================================
# 规则引擎
# ============================================================


def generate_predictions(
    date: str,
    stock: StockData,
) -> list[dict[str, Any]]:
    """基于资金流 + 价格生成预测。"""
    preds: list[dict[str, Any]] = []

    flow = stock.get_flow(date)
    close = stock.get_close(date)
    prev_close = stock.get_prev_close(date)

    if not flow or not close or not prev_close or prev_close == 0:
        return preds

    ratio_bp = flow["ratio"]
    price_change = (close - prev_close) / prev_close * 100

    # 规则 1：主力大幅流入 + 涨 → bullish
    if ratio_bp > 5 and price_change > 0:
        preds.append(
            {
                "direction": "bullish",
                "entry_price": close,
                "rationale": f"主力 ratio {ratio_bp:+.1f}bp + 涨 {price_change:+.1f}%",
                "strength": "normal",
                "rule": "flow_in_price_up",
            }
        )

    # 规则 2：主力大幅流出 + 跌 → bearish
    elif ratio_bp < -5 and price_change < 0:
        preds.append(
            {
                "direction": "bearish",
                "entry_price": close,
                "rationale": f"主力 ratio {ratio_bp:+.1f}bp + 跌 {price_change:+.1f}%",
                "strength": "normal",
                "rule": "flow_out_price_down",
            }
        )

    # 规则 3：极端流入（>10bp）
    if ratio_bp > 10:
        preds.append(
            {
                "direction": "bullish",
                "entry_price": close,
                "rationale": f"极端流入 ratio {ratio_bp:+.1f}bp",
                "strength": "strong",
                "rule": "extreme_inflow",
            }
        )

    # 规则 4：极端流出（< -10bp）
    if ratio_bp < -10:
        preds.append(
            {
                "direction": "bearish",
                "entry_price": close,
                "rationale": f"极端流出 ratio {ratio_bp:+.1f}bp",
                "strength": "strong",
                "rule": "extreme_outflow",
            }
        )

    return preds


# ============================================================
# 验证
# ============================================================


def verify_prediction(
    direction: str,
    entry_price: float,
    actual_price: float | None,
) -> tuple[str, float]:
    """验证单条预测。返回 (status, score)。

    评分委托给统一模块 ``mommy_chaogu.backtest.scoring.score_direction``，
    保证与 ``backtest_llm.py`` 等 4 条回测路径口径一致。
    """
    if actual_price is None:
        return ("expired", 0.0)

    change = (actual_price - entry_price) / entry_price * 100
    return score_direction(direction, change)


# ============================================================
# 主流程
# ============================================================


def run_backtest(db_path: str = str(AGENT_DB)) -> None:
    db = Path(db_path)
    if db.exists():
        db.unlink()

    # 延迟导入（确保用新 db）
    from mommy_chaogu.agent.episodic_memory import EpisodicMemory
    from mommy_chaogu.agent.prediction_tracker import PredictionTracker
    from mommy_chaogu.agent.prompt import SYSTEM_PROMPT
    from mommy_chaogu.agent.prompt_builder import build_system_prompt
    from mommy_chaogu.agent.semantic_memory import SemanticMemory

    episodic = EpisodicMemory(db)
    tracker = PredictionTracker(db)
    semantic = SemanticMemory(db)

    print("=" * 70)
    print("  📊 30 天回测式进化测试")
    print("  数据区间：2026-06-04 → 2026-07-03")
    print("=" * 70)

    # ============================================================
    # Step 1: 数据采集
    # ============================================================
    print("\n📦 Step 1: 数据采集\n")

    all_stocks: dict[str, StockData] = {}
    all_dates: set[str] = set()

    for code, name, market in STOCKS:
        stock = StockData(code, name)

        # K 线
        klines = fetch_tencent_daily(code, market)
        stock.klines = klines
        for k in klines:
            all_dates.add(k["date"])

        # 资金流
        flows = fetch_efinance_history(code)
        stock.flows = flows

        stock.build()
        all_stocks[code] = stock

        print(f"  {code} {name:8s}  K线 {len(klines)} 天  资金流 {len(flows)} 天")

        time.sleep(0.3)  # 避免太快被 ban

    trading_dates = sorted(all_dates)
    print(f"\n  总交易日: {len(trading_dates)}")
    print(f"  范围: {trading_dates[0]} → {trading_dates[-1]}")

    # 拉公告（写入 episodic）
    print("\n📨 拉公告...")
    ann_count = 0
    for code, name, _ in STOCKS:
        anns = fetch_announcements(code)
        for a in anns:
            if a["date"] >= "2026-06-01":
                episodic.write(
                    event_type="event",
                    scope=f"stock:{code}",
                    code=code,
                    name=name,
                    summary=f"公告：{a['title'][:50]}",
                    data={"title": a["title"], "date": a["date"]},
                    source="eastmoney",
                    confidence=0.9,
                    trade_date=a["date"],
                )
                ann_count += 1
        time.sleep(0.2)
    print(f"  写入 {ann_count} 条公告事件")

    # ============================================================
    # Step 2: 滑动窗口生成预测
    # ============================================================
    print("\n🔄 Step 2: 生成预测（滑动窗口 5d）\n")

    # 回测窗口：留最后 5 天做验证
    backtest_end_idx = len(trading_dates) - 5
    backtest_dates = trading_dates[:backtest_end_idx]

    pred_records: list[dict[str, Any]] = []

    for date in backtest_dates:
        for code, name, _ in STOCKS:
            stock = all_stocks[code]
            preds = generate_predictions(date, stock)

            for pred in preds:
                # 写 episodic
                event_id = episodic.write(
                    event_type="analysis_record",
                    scope=f"stock:{code}",
                    code=code,
                    name=name,
                    summary=f"{date} {pred['rationale']}",
                    data={
                        "rule": pred["rule"],
                        "strength": pred["strength"],
                        "direction": pred["direction"],
                        "entry_price": pred["entry_price"],
                    },
                    source="backtest",
                    confidence=0.7 if pred["strength"] == "strong" else 0.5,
                    trade_date=date,
                )

                # 写 prediction
                pid = tracker.create(
                    code=code,
                    name=name,
                    prediction=f"{pred['rationale']} → {pred['direction']}",
                    direction=pred["direction"],
                    timeframe="5d",
                    entry_price=pred["entry_price"],
                    rationale=pred["rationale"],
                )

                pred_records.append(
                    {
                        "pid": pid,
                        "event_id": event_id,
                        "code": code,
                        "name": name,
                        "date": date,
                        "direction": pred["direction"],
                        "entry_price": pred["entry_price"],
                        "strength": pred["strength"],
                        "rule": pred["rule"],
                        "rationale": pred["rationale"],
                    }
                )

    print(f"  生成 {len(pred_records)} 条预测（{len(backtest_dates)} 天 × 10 只股票）")

    # ============================================================
    # Step 3: 验证
    # ============================================================
    print("\n✅ Step 3: T+5 验证\n")

    for rec in pred_records:
        stock = all_stocks[rec["code"]]
        future_close = stock.get_future_close(rec["date"], 5)

        status, score = verify_prediction(rec["direction"], rec["entry_price"], future_close)

        tracker.update_status(
            rec["pid"],
            status=status,
            actual_price=future_close,
            accuracy_score=score,
        )

        # 写验证事件
        change_str = ""
        if future_close:
            change = (future_close - rec["entry_price"]) / rec["entry_price"] * 100
            change_str = f"({change:+.1f}%)"

        emoji = "✅" if status == "hit" else "❌" if status == "missed" else "⏰"
        episodic.write(
            event_type="analysis_record",
            scope=f"stock:{rec['code']}",
            code=rec["code"],
            name=rec["name"],
            summary=f"验证：{rec['rationale'][:30]} → {emoji} {status.upper()} {change_str} score={score:.1f}",
            data={
                "prediction_id": rec["pid"],
                "status": status,
                "score": score,
                "entry": rec["entry_price"],
                "actual": future_close,
            },
            source="backtest_verify",
            confidence=score,
            prediction_id=rec["pid"],
        )

    # ============================================================
    # Step 4: 报告
    # ============================================================
    print("=" * 70)
    print("  📊 30 天回测进化报告")
    print(f"  {trading_dates[0]} → {trading_dates[-1]}")
    print("=" * 70)

    stats = tracker.stats()
    total = stats["total"]
    hits = stats["hit"]
    missed = stats["missed"]
    expired = stats["expired"]
    hit_rate = stats["hit_rate"]

    print("\n📈 总体表现")
    print(f"  总预测: {total}")
    print(f"  ✅ 命中: {hits}  ❌ 失误: {missed}  ⏰ 过期: {expired}")
    verifiable = hits + missed
    print(
        "  命中率: " + format_hit_rate(hits, verifiable)
        + (f"（排除 {expired} 条过期）" if expired else "")
    )

    # 等权买入持有基准：同一组股票、同一时间窗口，多头持有的方向命中率
    all_preds = tracker.all(limit=200)
    baseline = compute_buyhold_baseline(all_preds)
    if baseline["total"]:
        b_rate = baseline["rate"]
        alpha = hit_rate - b_rate
        alpha_sign = "+" if alpha >= 0 else ""
        print(f"  📊 Buy-and-hold 基准: {b_rate:.0%}")
        print(f"  Alpha (策略-基准): {alpha_sign}{alpha:.0%}")

    bullish = [p for p in all_preds if p["direction"] == "bullish"]
    bearish = [p for p in all_preds if p["direction"] == "bearish"]
    bull_hits = sum(1 for p in bullish if p["status"] == "hit")
    bear_hits = sum(1 for p in bearish if p["status"] == "hit")
    bull_verifiable = sum(1 for p in bullish if p["status"] in ("hit", "missed"))
    bear_verifiable = sum(1 for p in bearish if p["status"] in ("hit", "missed"))

    print("\n📊 分方向命中率")
    if bull_verifiable:
        print(f"  Bullish: {format_hit_rate(bull_hits, bull_verifiable)}")
    else:
        print("  Bullish: 0 条可验证")
    if bear_verifiable:
        print(f"  Bearish: {format_hit_rate(bear_hits, bear_verifiable)}")
    else:
        print("  Bearish: 0 条可验证")

    # 分信号强度
    # 用 pred_records 分强度
    strong_codes = {r["pid"] for r in pred_records if r["strength"] == "strong"}
    normal_codes = {r["pid"] for r in pred_records if r["strength"] == "normal"}

    strong_all = [p for p in all_preds if p["id"] in strong_codes]
    normal_all = [p for p in all_preds if p["id"] in normal_codes]
    strong_hits = sum(1 for p in strong_all if p["status"] == "hit")
    normal_hits = sum(1 for p in normal_all if p["status"] == "hit")
    strong_verifiable = sum(1 for p in strong_all if p["status"] in ("hit", "missed"))
    normal_verifiable = sum(1 for p in normal_all if p["status"] in ("hit", "missed"))

    print("\n📊 分信号强度")
    if normal_verifiable:
        print(f"  普通信号 (5-10bp): {format_hit_rate(normal_hits, normal_verifiable)}")
    if strong_verifiable:
        print(f"  强信号 (10bp+):    {format_hit_rate(strong_hits, strong_verifiable)}")

    # 分个股
    print("\n📊 分个股命中率")
    by_code: dict[str, list] = defaultdict(list)
    for p in all_preds:
        by_code[f"{p['code']} {p.get('name', '')}"].append(p)

    for label, preds in sorted(by_code.items()):
        verifiable = [p for p in preds if p["status"] in ("hit", "missed")]
        hits = sum(1 for p in verifiable if p["status"] == "hit")
        rate = hits / len(verifiable) if verifiable else 0
        emoji = (
            "🏆"
            if rate >= 0.7 and len(verifiable) >= 2
            else "💀"
            if rate <= 0.3 and len(verifiable) >= 2
            else "  "
        )
        if verifiable:
            print(f"  {emoji} {label:20s} {hits}/{len(verifiable)} {format_hit_rate(hits, len(verifiable))}")

    # 最准 / 最差
    verified = [
        p
        for p in all_preds
        if p["status"] in ("hit", "missed") and p.get("accuracy_score") is not None
    ]
    verified.sort(key=lambda p: p["accuracy_score"], reverse=True)

    print("\n🏆 最准的 3 条预测")
    for p in verified[:3]:
        change = ""
        if p.get("actual_price") and p.get("entry_price"):
            ch = (p["actual_price"] - p["entry_price"]) / p["entry_price"] * 100
            change = f" ({ch:+.1f}%)"
        print(
            f"  ✅ {p['code']} {p.get('name', ''):8s} {p['direction']:8s} score={p['accuracy_score']:.1f}{change}"
        )
        print(f"      {p.get('prediction', '')[:50]}")

    print("\n💀 最差的 3 条预测")
    for p in verified[-3:]:
        change = ""
        if p.get("actual_price") and p.get("entry_price"):
            ch = (p["actual_price"] - p["entry_price"]) / p["entry_price"] * 100
            change = f" ({ch:+.1f}%)"
        print(
            f"  ❌ {p['code']} {p.get('name', ''):8s} {p['direction']:8s} score={p['accuracy_score']:.1f}{change}"
        )
        print(f"      {p.get('prediction', '')[:50]}")

    # ============================================================
    # Step 5: 知识提炼
    # ============================================================
    print("\n🧠 知识提炼\n")

    # 规律 1：方向命中率
    patterns: list[str] = []
    if bull_verifiable and bear_verifiable:
        bull_rate = bull_hits / bull_verifiable
        bear_rate = bear_hits / bear_verifiable
        if bull_rate > bear_rate:
            patterns.append(
                f"看涨预测（主力流入+涨价）命中率 {bull_rate:.0%}，"
                f"高于看跌预测 {bear_rate:.0%}。市场偏多头。"
            )
        else:
            patterns.append(
                f"看跌预测（主力流出+跌价）命中率 {bear_rate:.0%}，"
                f"高于看涨预测 {bull_rate:.0%}。趋势延续性强。"
            )

    # 规律 2：信号强度
    if strong_verifiable and normal_verifiable:
        strong_rate = strong_hits / strong_verifiable
        normal_rate = normal_hits / normal_verifiable
        if strong_rate > normal_rate:
            patterns.append(
                f"极端信号（ratio >10bp）命中率 {strong_rate:.0%}，"
                f"高于普通信号（5-10bp）{normal_rate:.0%}。大信号更可信。"
            )
        else:
            patterns.append(
                f"普通信号（5-10bp）命中率 {normal_rate:.0%}，"
                f"与极端信号 {strong_rate:.0%} 差异不大。"
            )

    # 规律 3：个股差异
    stock_rates = []
    for label, preds in by_code.items():
        verifiable = [p for p in preds if p["status"] in ("hit", "missed")]
        if len(verifiable) >= 2:
            hits_n = sum(1 for p in verifiable if p["status"] == "hit")
            stock_rates.append((label, hits_n / len(verifiable), len(verifiable)))

    stock_rates.sort(key=lambda x: x[1])
    if stock_rates:
        worst_stock = stock_rates[0]
        best_stock = stock_rates[-1]
        patterns.append(
            f"个股差异：{best_stock[0]} 命中率最高（{best_stock[1]:.0%}），"
            f"{worst_stock[0]} 最低（{worst_stock[1]:.0%}）。"
            f"资金流信号在不同股票上的有效性差异大。"
        )

    for i, p in enumerate(patterns):
        print(f"  规律 {i + 1}: {p}")

    # 写入语义知识
    if patterns:
        semantic.upsert(
            knowledge_type="pattern_observed",
            scope="market",
            content=" | ".join(patterns),
            confidence=hit_rate,
        )

    # 写个股认知
    for label, rate, n in stock_rates:
        if n >= 2:
            code_part = label.split()[0]
            semantic.upsert(
                knowledge_type="stock_insight",
                scope=f"stock:{code_part}",
                content=f"30天回测：资金流信号命中率 {rate:.0%}（{n} 条验证）",
                confidence=rate,
            )

    # 写市场状态
    semantic.upsert(
        knowledge_type="market_regime",
        scope="market",
        content=f"2026年6月市场：总命中率 {hit_rate:.0%}，"
        f"{'多头占优' if bull_verifiable and bull_hits / bull_verifiable > 0.5 else '空头或震荡占优'}",
        confidence=0.6,
    )

    print(f"\n  写入 {len(semantic.get_active())} 条知识")

    # ============================================================
    # Step 6: 进化后的 prompt
    # ============================================================
    print("\n📝 进化后的 system prompt 片段\n")

    prompt = build_system_prompt(episodic=episodic, tracker=tracker, semantic=semantic)
    print(
        f"  原始: {len(SYSTEM_PROMPT)} 字 → 进化后: {len(prompt)} 字 (+{len(prompt) - len(SYSTEM_PROMPT)})"
    )

    # 只显示注入部分
    if "## 已有认知" in prompt:
        start = prompt.find("## 已有认知")
        end = prompt.find("\n\n## 近期事件")
        if end == -1:
            end = start + 500
        print()
        print(prompt[start:end].strip())

    if "## 最近判断回顾" in prompt:
        start = prompt.find("## 最近判断回顾")
        print()
        print(prompt[start : start + 400].strip())

    # ============================================================
    # 总结
    # ============================================================
    print(f"\n{'=' * 70}")
    print("  ✅ 回测进化测试完成")
    print(f"  {total} 条预测 → {hits} 命中 → 命中率 {hit_rate:.0%}")
    print(f"  {len(semantic.get_active())} 条知识提炼")
    print(f"  prompt 从 {len(SYSTEM_PROMPT)} 字进化到 {len(prompt)} 字")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    db = str(AGENT_DB)
    run_backtest(db)
