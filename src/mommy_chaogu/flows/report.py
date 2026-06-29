"""资金流收盘日报（markdown）。

输出路径：data/flows_report_YYYY-MM-DD.md
内容：
- 池子概况：N 只，按主位置分组
- 板块汇总：上游/中游/下游/末端 各自的 ratio 合计
- TOP 10 流入 / TOP 10 流出（按 ratio，非绝对值）
- 「矛盾股」清单：今日 ratio > 0 但 30d 累计 ratio < 0
- 信号触发统计（从 signals.log 读）

设计原则：
- 全 ratio-based，避免大票小票偏差
- 横向对比（板块 / 子分类）
- 纵向对比（今日 vs 30d）
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from mommy_chaogu.flows.pool import PoolSource, SemiconPool
from mommy_chaogu.flows.service import FlowService

DEFAULT_FLOWS_REPORT_DIR = Path("data/")


def _fmt_bp(d: Decimal) -> str:
    """ratio 转 bp 显示。"""
    bp = float(d) * 10000
    sign = "+" if bp > 0 else ""
    return f"{sign}{bp:.1f}bp"


def _fmt_yi(d: Decimal) -> str:
    yi = float(d) / 1e8
    sign = "+" if yi > 0 else ""
    return f"{sign}{yi:.2f}亿"


def _fmt_pct(n: int, total: int) -> str:
    if total == 0:
        return "0%"
    return f"{n / total * 100:.0f}%"


class FlowReport:
    """收盘日报生成器。"""

    def __init__(self, service: FlowService) -> None:
        self.service = service

    def generate(
        self,
        pool: PoolSource,
        *,
        day: date | None = None,
        history_days: int = 30,
        output: Path,
        market_caps: dict[str, tuple[str, Decimal]] | None = None,
    ) -> Path:
        """生成 markdown 报告，输出到 `output`，返回路径。"""
        day = day or date.today()
        if market_caps is None:
            market_caps = self.service.get_market_caps(pool.codes())

        # 1. 收集数据
        today_rows: list[dict[str, Any]] = []  # {code, name, main_net, ratio, chain_position, subcategory}
        history_agg: dict[str, Decimal] = {}    # code -> 30d 累计 main_net
        no_data: list[str] = []

        # 拉板块 / 子分类信息（仅 semicon 池有）
        chain_info: dict[str, tuple[str, str]] = {}  # code -> (chain_position, subcategory)
        if isinstance(pool, SemiconPool):
            from mommy_chaogu.semicon import SemiconStore
            store = SemiconStore(pool._db_path)
            for s in store.list_all():
                chain_info[s.code] = (s.chain_position, s.subcategory)

        for code in pool.codes():
            mcap_tuple = market_caps.get(code)
            if mcap_tuple is None:
                no_data.append(code)
                continue
            name = mcap_tuple[0]
            float_mcap = mcap_tuple[1]

            # 当日
            today_raw = self.service.store.get_today_money_flow(code)
            if today_raw:
                from mommy_chaogu.flows.service import _money_flow_from_dict
                last = _money_flow_from_dict(today_raw[-1])
                main_net = last.main_net.amount
                ratio = main_net / float_mcap if float_mcap else Decimal("0")
                cp_tup = chain_info.get(code, ("?", "?"))
                chain_position_val: str = cp_tup[0]
                subcategory_val: str = cp_tup[1]
                today_rows.append({
                    "code": code, "name": name,
                    "main_net": main_net, "float_mcap": float_mcap,
                    "ratio": ratio,
                    "chain_position": chain_position_val,
                    "subcategory": subcategory_val,
                })

            # 历史 30d 累计
            hist_raw = self.service.store.get_money_flow_history(code)
            if hist_raw:
                from mommy_chaogu.flows.service import _money_flow_from_dict
                agg = Decimal("0")
                for d in hist_raw:
                    flows = d.get("flows", [])
                    if not flows:
                        continue
                    last_of_day = _money_flow_from_dict(flows[-1])
                    agg += last_of_day.main_net.amount
                history_agg[code] = agg

        # 2. 计算板块 / 子分类 ratio 合计
        chain_totals: dict[str, dict[str, Any]] = defaultdict(
            lambda: {"n": 0, "main_net": Decimal("0"), "float_mcap": Decimal("0")}
        )
        for r in today_rows:
            cp: str = r["chain_position"]
            chain_totals[cp]["n"] += 1
            chain_totals[cp]["main_net"] += r["main_net"]
            chain_totals[cp]["float_mcap"] += r["float_mcap"]
        for _cp, v in chain_totals.items():
            if v["float_mcap"]:
                v["ratio"] = v["main_net"] / v["float_mcap"]
            else:
                v["ratio"] = Decimal("0")

        # 3. 排序
        today_in = sorted(today_rows, key=lambda r: r["ratio"], reverse=True)[:10]
        today_out = sorted(today_rows, key=lambda r: r["ratio"])[:10]

        # 4. 「矛盾股」：今日 ratio > 0 但 30d ratio < 0
        contradictions: list[dict[str, Any]] = []
        for r in today_rows:
            if r["ratio"] > 0:
                hist_mc = history_agg.get(r["code"], Decimal("0"))
                if hist_mc != 0 and r["float_mcap"] > 0:
                    hist_ratio = hist_mc / r["float_mcap"]
                    if hist_ratio < 0:
                        contradictions.append({
                            **r,
                            "hist_main_net": hist_mc,
                            "hist_ratio": hist_ratio,
                        })
        contradictions.sort(key=lambda r: r["ratio"] - r["hist_ratio"], reverse=True)

        # 5. 写 markdown
        lines: list[str] = []
        lines.append(f"# 资金流收盘日报 · {day} · {pool.name}")
        lines.append("")
        lines.append(f"**池子**：{pool.describe()}")
        lines.append("")
        lines.append(
            f"**覆盖**：{len(today_rows)}/{pool.codes().__len__()} 只拉到了当日数据"
        )
        if no_data:
            lines.append(f"**无数据**：{len(no_data)} 只（{no_data[:5]}{'...' if len(no_data) > 5 else ''}）")
        lines.append("")
        _today_sum = sum(r['main_net'] for r in today_rows) if today_rows else Decimal("0")
        total_main_today: Decimal = _today_sum if isinstance(_today_sum, Decimal) else Decimal("0")
        _hist_sum = sum(history_agg.values()) if history_agg else Decimal("0")
        total_main_hist: Decimal = _hist_sum if isinstance(_hist_sum, Decimal) else Decimal("0")
        lines.append(f"**当日主力净合计**：{_fmt_yi(total_main_today)}")
        lines.append(
            f"**30d 累计主力净合计**：{_fmt_yi(total_main_hist)}"
        )
        lines.append("")

        # 板块汇总
        lines.append("## 📊 板块汇总（按 ratio）")
        lines.append("")
        lines.append("| 板块 | 股票数 | 当日主力净 | 流通市值 | **ratio** |")
        lines.append("|---|---|---|---|---|")
        for _cp in sorted(chain_totals.keys()):
            v = chain_totals[_cp]
            lines.append(
                f"| {_cp} | {v['n']} | {_fmt_yi(v['main_net'])} | "
                f"{_fmt_yi(v['float_mcap'])} | **{_fmt_bp(v['ratio'])}** |"
            )
        lines.append("")

        # TOP 流入
        lines.append("## 🟢 当日净流入 TOP 10（按 ratio）")
        lines.append("")
        if today_in:
            lines.append("| 排名 | 代码 | 名称 | 子分类 | 主力净 | 流通市值 | **ratio** |")
            lines.append("|---|---|---|---|---|---|---|")
            for i, r in enumerate(today_in[:10], 1):
                lines.append(
                    f"| {i} | {r['code']} | {r['name'][:10]} | {r['subcategory']} | "
                    f"{_fmt_yi(r['main_net'])} | {_fmt_yi(r['float_mcap'])} | **{_fmt_bp(r['ratio'])}** |"
                )
        else:
            lines.append("（无数据）")
        lines.append("")

        # TOP 流出
        lines.append("## 🔴 当日净流出 TOP 10（按 ratio）")
        lines.append("")
        if today_out:
            lines.append("| 排名 | 代码 | 名称 | 子分类 | 主力净 | 流通市值 | **ratio** |")
            lines.append("|---|---|---|---|---|---|---|")
            for i, r in enumerate(today_out[:10], 1):
                lines.append(
                    f"| {i} | {r['code']} | {r['name'][:10]} | {r['subcategory']} | "
                    f"{_fmt_yi(r['main_net'])} | {_fmt_yi(r['float_mcap'])} | **{_fmt_bp(r['ratio'])}** |"
                )
        else:
            lines.append("（无数据）")
        lines.append("")

        # 矛盾股
        lines.append("## ⚠️ 矛盾股：今日流入 vs 30d 流出")
        lines.append("")
        if contradictions:
            lines.append("| 代码 | 名称 | 当日 ratio | 30d 累计 ratio | 当日主力净 | 30d 累计主力净 |")
            lines.append("|---|---|---|---|---|---|")
            for r in contradictions[:15]:
                lines.append(
                    f"| {r['code']} | {r['name'][:10]} | **{_fmt_bp(r['ratio'])}** | "
                    f"{_fmt_bp(r['hist_ratio'])} | {_fmt_yi(r['main_net'])} | "
                    f"{_fmt_yi(r['hist_main_net'])} |"
                )
        else:
            lines.append("（无矛盾股）")
        lines.append("")

        # 页脚
        lines.append("---")
        lines.append("")
        lines.append(
            f"*生成时间：{datetime.now():%Y-%m-%d %H:%M:%S}  ·  "
            f"全 ratio-based（流通市值分母），避免大票小票偏差*"
        )

        # 6. 写盘
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text("\n".join(lines), encoding="utf-8")
        return output

