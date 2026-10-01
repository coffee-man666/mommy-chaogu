"""市场环境（regime）逐日三态序列服务（L1 市场环境·路径式状态）。

在 ``backtest.regime_analysis.classify_market_regime`` 的单值截面之上，复用
``_regime_at`` 的按日期二分定位，把指数日 K 展开成近 N 个交易日的逐日
bull / bear / sideways 序列 + 状态持续天数 / 切换点摘要——回答「现在市场
什么状态？跟上周比有什么变化？」，而不再是单值截面。

诚实边界（docs/plans/trading-method-landing.md 阶段四 / §4.3-5 / §4.4）：
- 输出是「探索性状态评估」：三态判定的波动率阈值（2% / 2.5%）未在真实
  指数数据上校准（仅合成 K 线验证过），不构成择时建议；
- 数据入口是 A 股指数 K 线通路：代码经 ``rankings.resolve_index_symbol``
  按 INDEX_LIST 白名单解析，输出标注判定标的——杜绝把个股日 K 静默当
  指数（如 '000001' = 平安银行，风险 R10）；
- 指数实拉语义（东财侧对 'sh000001' 的解析）在本机网络不可达环境未验证，
  验收前须网络探针确认。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from mommy_chaogu.backtest.regime_analysis import (
    _REGIME_LABEL,
    MA_LONG,
    MA_SHORT,
    _regime_at,
)
from mommy_chaogu.market_data.adapter import MarketDataAdapter
from mommy_chaogu.market_data.rankings import resolve_index_symbol
from mommy_chaogu.market_data.types import BarInterval

# 服务层防御钳制：窗口太小退化成「今天的截面」（classify_market_regime
# 已覆盖），太大则超出指数日 K 单次可回溯深度（limit 最大 120 根）。
MIN_DAYS = 2
MAX_DAYS = 60
DEFAULT_DAYS = 20

NOTE = "探索性状态评估：三态判定的波动率阈值（2%/2.5%）未在真实指数数据上校准，不构成择时建议"

_TZ_BEIJING = ZoneInfo("Asia/Shanghai")


def _bar_trade_date(ts: datetime) -> str:
    """K 线时间戳 → 北京时区交易日字符串（与 cache/adapter._bar_trade_date 同语义）。"""
    if ts.tzinfo is None:
        # 防御：naive 视为北京墙时间
        ts = ts.replace(tzinfo=_TZ_BEIJING)
    return ts.astimezone(_TZ_BEIJING).strftime("%Y-%m-%d")


class RegimeSeriesService:
    """指数日 K → 近 N 个交易日的逐日三态序列 + 状态转移摘要。

    用法（agent 工具层接线见 agent/tools/analysis.py）::

        service = RegimeSeriesService(adapter)
        result = service.compute("sh000001", days=20)  # dict，JSON 可序列化
    """

    def __init__(self, adapter: MarketDataAdapter) -> None:
        self._adapter = adapter

    def compute(
        self,
        index_code: str = "sh000001",
        days: int = DEFAULT_DAYS,
    ) -> dict[str, Any]:
        """生成路径式市场状态序列。

        Args:
            index_code: 指数标识（代码 'sh000001' / 名称 '上证指数' / secid
                '1.000001'），按 INDEX_LIST 白名单解析，解析不到返回 error。
            days: 回看窗口（交易日），钳到 [2, 60]。

        Returns:
            dict（JSON 可序列化）：判定标的标注（subject 等）+ series（逐日
            三态）+ segments / switches（状态转移）+ current_regime 及持续
            天数 + summary + note（探索性标注）。K 线不可得时返回
            ``{"error": ..., "subject": ...}``，不产出假序列。
        """
        entry = resolve_index_symbol(index_code)
        if entry is None:
            return {
                "error": f"未知指数代码 '{index_code}'：A 股指数代码必须带市场前缀（如 sh000001）",
                "hint": "裸 6 位数字（如 '000001'）是 A 股个股代码（平安银行），不能当指数用",
            }
        secid, name, code = entry
        subject = f"{name} {code}"
        window = max(MIN_DAYS, min(days, MAX_DAYS))

        # 序列首日也需要最多 MA_LONG 根前置 K 线供 _regime_at 判定，
        # 因此拉 window + MA_LONG 根；MA_SHORT 根都不够的早期日期按
        # classify_market_regime 的退化规则判 sideways。
        bars = self._adapter.get_bars(code, interval=BarInterval.D1, limit=window + MA_LONG)
        by_date: dict[str, Any] = {}
        for bar in bars:
            by_date[_bar_trade_date(bar.timestamp)] = bar.close
        dicts = [{"date": d, "close": c} for d, c in sorted(by_date.items())]
        if not dicts:
            return {
                "error": f"{subject} 指数日 K 不可得（上游无数据或网络不可达）",
                "subject": subject,
                "index_code": code,
            }

        dates = [d["date"] for d in dicts]
        full_series = [(date, _regime_at(dicts, dates, date)) for date in dates]
        window_series = full_series[-window:]

        counts = {"bull": 0, "bear": 0, "sideways": 0}
        for _date, regime in window_series:
            counts[regime] += 1

        segments: list[dict[str, Any]] = []
        for date, regime in window_series:
            if segments and segments[-1]["regime"] == regime:
                segments[-1]["end"] = date
                segments[-1]["days"] += 1
            else:
                segments.append({"regime": regime, "start": date, "end": date, "days": 1})

        switches: list[dict[str, Any]] = []
        for i in range(1, len(window_series)):
            prev_regime = window_series[i - 1][1]
            regime = window_series[i][1]
            if regime != prev_regime:
                switches.append(
                    {
                        "date": window_series[i][0],
                        "from": prev_regime,
                        "to": regime,
                        "days_since": len(window_series) - i,  # 切换日到窗口末的交易日数
                    }
                )

        # 当前状态持续天数在整个已判定序列上数（可能早于窗口起点），
        # 受限于实际取到的 K 线根数（bars_fetched 如实披露）。
        current_regime = full_series[-1][1]
        current_run_days = 0
        current_since = full_series[-1][0]
        for date, regime in reversed(full_series):
            if regime != current_regime:
                break
            current_run_days += 1
            current_since = date

        seg_text = " → ".join(f"{seg['regime']}×{seg['days']}" for seg in segments)
        summary = (
            f"{name}：近 {len(window_series)} 个交易日 {seg_text}；"
            f"当前{_REGIME_LABEL[current_regime]}（{current_regime}）已持续 "
            f"{current_run_days} 个交易日（自 {current_since}）"
        )

        payload: dict[str, Any] = {
            "subject": subject,  # 判定标的标注：防把个股日 K 误当指数
            "index_name": name,
            "index_code": code,
            "secid": secid,
            "days": len(window_series),
            "as_of": dates[-1],
            "current_regime": current_regime,
            "current_regime_since": current_since,
            "current_run_days": current_run_days,
            "counts": counts,
            "segments": segments,
            "switches": switches,
            "series": [{"date": date, "regime": regime} for date, regime in window_series],
            "bars_fetched": len(dicts),
            "summary": summary,
            "note": NOTE,
        }
        # K 线根数不足 window + MA_LONG 时，窗口前段的判定退化（样本不足
        # 判 sideways）——如实标注，不冒充完整历史。
        if len(dicts) < window + MA_LONG:
            payload["history_short"] = True
            payload["history_short_note"] = (
                f"仅取到 {len(dicts)} 根日 K（期望 {window + MA_LONG}）："
                f"序列前段按样本不足（<{MA_SHORT} 根）退化判为 sideways"
            )
        return payload
