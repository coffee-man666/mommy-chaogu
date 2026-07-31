"""Tushare 数据源实现（基于 tushare.pro API）。

为什么用 Tushare 作为补充数据源：
- 财务数据/历史 K 线/资金流/分红送股 — **业内最全最准**
- 云服务（阿里云），**海外 IP 直连稳定**，对境外用户友好
- 接口稳定，文档详细，字段命名规范
- 适合作为 K 线/财务/资金流场景的**主源**，实时报价仍由东财/腾讯负责

Tushare 的特点（与 efinance/腾讯区别）：
- **EOD 数据为主**（盘后），不是实时行情
- 代码格式：`600519.SH`（带 . 和后缀），与项目内部 `600519` 不同，需要转换
- 需要 token（环境变量 `TUSHARE_TOKEN`），未配置时所有方法返回 None
- 每次调用消耗积分，免费档每日 5000 次，中级档不限次
- 走 HTTPS JSON API，不依赖任何爬虫

使用：
    adapter = TushareAdapter()  # 自动从环境变量 TUSHARE_TOKEN 读 token
    quote = adapter.get_quote("600519")  # 返回 None（Tushare 不提供实时）
    bars = adapter.get_bars("600519")    # 返回日 K 线（最准的源）
    flows = adapter.get_history_money_flow("600519", days=30)  # 历史资金流
"""

from __future__ import annotations

import logging
import os
import warnings
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

import pandas as pd

from mommy_chaogu.market_data.types import (
    AdjustmentType,
    Bar,
    BarInterval,
    Board,
    MarketType,
    Money,
    MoneyFlow,
    OrderBook,
    Quote,
    QuoteType,
    Tick,
)

warnings.filterwarnings("ignore")

_log = logging.getLogger(__name__)


# ---------- 内部工具 ----------


def _to_dec(v: Any) -> Decimal | None:
    """安全转 Decimal，失败返回 None。"""
    if v is None:
        return None
    if isinstance(v, float) and pd.isna(v):
        return None
    try:
        return Decimal(str(v))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _to_int(v: Any) -> int:
    """安全转 int。"""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return 0
    try:
        return int(float(v))
    except (ValueError, TypeError):
        return 0


def _to_money(v: Any) -> Money:
    """转 Money（默认 CNY）。"""
    amt = _to_dec(v) or Decimal("0")
    return Money(amt, "CNY")


# Tushare 市场后缀 → 项目 MarketType
_TS_EXCHANGE_MAP: dict[str, MarketType] = {
    "SH": MarketType.SH,
    "SZ": MarketType.SZ,
    "BJ": MarketType.BJ,
}

# MarketType → Tushare 后缀
_MARKET_TO_TS_SUFFIX: dict[MarketType, str] = {
    MarketType.SH: "SH",
    MarketType.SZ: "SZ",
    MarketType.BJ: "BJ",
}


def _detect_market_from_code(code: str) -> MarketType:
    """根据 6 位股票代码头推断市场。已抽取到 market_data.utils.detect_market 统一维护。"""
    from mommy_chaogu.market_data.utils import detect_market

    return detect_market(code)


def _detect_quote_type(code: str) -> QuoteType:
    if code.startswith(("51", "15", "16", "18", "11", "12", "13", "14")):
        return QuoteType.FUND
    return QuoteType.STOCK


def to_tushare_code(code: str, market: MarketType | None = None) -> str:
    """项目内部代码 `600519` → Tushare 格式 `600519.SH`。

    如果已包含 `.XX` 后缀则原样返回。
    """
    if "." in code:
        return code
    if market is None:
        market = _detect_market_from_code(code)
    suffix = _MARKET_TO_TS_SUFFIX.get(market, "SH")
    return f"{code}.{suffix}"


def from_tushare_code(ts_code: str) -> tuple[str, MarketType]:
    """Tushare 格式 `600519.SH` → (项目内部代码 `600519`, 市场)。"""
    if "." in ts_code:
        code, suffix = ts_code.split(".", 1)
        market = _TS_EXCHANGE_MAP.get(suffix.upper(), _detect_market_from_code(code))
    else:
        code = ts_code
        market = _detect_market_from_code(code)
    return code, market


# ---------- 复权工具函数 ----------


def apply_adjustment(
    bars: list[Bar],
    adj_factors: pd.DataFrame,
    mode: AdjustmentType = AdjustmentType.FORWARD,
) -> list[Bar]:
    """对 K 线列表应用前/后复权。

    输入：未复权 K 线 + 复权因子表（Tushare adj_factor 接口返回的格式）
    输出：调整后的 K 线（新 Bar 实例，原列表不被修改）

    参数:
        bars: 待调整的 K 线列表（不复权原始价）
        adj_factors: 复权因子表，必须包含两列：
            - trade_date (str YYYYMMDD 或 datetime.date)
            - adj_factor (float / Decimal)
        mode: AdjustmentType.FORWARD（前复权）或 BACKWARD（后复权）

    算法:
        前复权 adj_price = raw_price * (latest_factor / current_factor)
            → 调整后**最新价 = 原始最新价**（价格历史保持连续，历史价更低）
            → 回测看历史业绩最常用
        后复权 adj_price = raw_price * (earliest_factor / current_factor)
            → 调整后**最早价 = 原始最早价**（最新价更高）
            → 看完整历史涨幅用

    使用场景:
        - **实盘/盘中数据：不需要调用**（实时价就是实际价）
        - **回测/历史可视化**：调用前复权，价格连续，复利计算正确
        - **对比长期涨幅**：调用后复权，能看到从 IPO 起的真实回报

    示例:
        from tushare import pro_api
        from mommy_chaogu.market_data.tushare_adapter import apply_adjustment
        from mommy_chaogu.market_data.types import AdjustmentType

        pro = pro_api('token')
        # 1. 拉不复权 K 线
        bars = adapter.get_bars("600519", AdjustmentType.NONE)
        # 2. 拉复权因子
        factors = pro.adj_factor(ts_code="600519.SH", start_date="20200101", end_date="20241231")
        # 3. 应用前复权
        bars_adj = apply_adjustment(bars, factors, AdjustmentType.FORWARD)
    """
    if mode == AdjustmentType.NONE or not bars:
        return bars
    if adj_factors is None or adj_factors.empty:
        return bars

    # 构造 {date_str: factor} 查找表
    factor_map: dict[str, Decimal] = {}
    for _, row in adj_factors.iterrows():
        trade_date = row.get("trade_date")
        if trade_date is None:
            continue
        # trade_date 可能是 str / Timestamp / date，统一转 YYYYMMDD
        if isinstance(trade_date, str):
            date_str = trade_date.replace("-", "")[:8]
        else:
            try:
                date_str = pd.Timestamp(trade_date).strftime("%Y%m%d")
            except (ValueError, TypeError):
                continue
        factor_val = _to_dec(row.get("adj_factor"))
        if factor_val is not None and factor_val > 0:
            factor_map[date_str] = factor_val

    if not factor_map:
        return bars

    # 找基准因子：来自 bars 列表中最早/最晚一根 bar 的日期对应的因子
    # Tushare 的 adj_factor 约定是"越早越大、越晚越小"（除权除息让因子下降），
    # 所以不能用 max/min，要按日期取。
    sorted_bars = sorted(bars, key=lambda b: b.timestamp)
    latest_bar_date_str = sorted_bars[-1].timestamp.strftime("%Y%m%d")
    earliest_bar_date_str = sorted_bars[0].timestamp.strftime("%Y%m%d")

    if mode == AdjustmentType.FORWARD:
        # 前复权：基准 = bars 中最新一根的因子（让最新价不变）
        latest_factor = factor_map.get(latest_bar_date_str)
        if latest_factor is None or latest_factor == 0:
            return bars
    else:  # BACKWARD
        # 后复权：基准 = bars 中最早一根的因子（让最早价不变）
        earliest_factor = factor_map.get(earliest_bar_date_str)
        if earliest_factor is None or earliest_factor == 0:
            return bars

    adjusted: list[Bar] = []
    for bar in bars:
        # 提取 bar 的日期 key
        bar_date_str = bar.timestamp.strftime("%Y%m%d")
        cur_factor = factor_map.get(bar_date_str)
        if cur_factor is None or cur_factor == 0:
            # 找不到因子（可能日期超出范围或没数据），跳过调整
            adjusted.append(bar)
            continue

        # 计算复权系数
        if mode == AdjustmentType.FORWARD:
            ratio = latest_factor / cur_factor  # type: ignore[operator]
        else:
            ratio = earliest_factor / cur_factor  # type: ignore[operator]

        # 应用到 OHLC（不复权价 * ratio = 复权价）
        new_open = (bar.open * ratio) if bar.open else bar.open
        new_high = (bar.high * ratio) if bar.high else bar.high
        new_low = (bar.low * ratio) if bar.low else bar.low
        new_close = (bar.close * ratio) if bar.close else bar.close
        # 注意：成交量和成交额不复权（除权除息不影响量）
        # turnover_rate / change_pct / amplitude 不复权（已是相对值）

        adjusted.append(
            Bar(
                code=bar.code,
                name=bar.name,
                interval=bar.interval,
                adjustment=mode,
                timestamp=bar.timestamp,
                open=new_open,
                high=new_high,
                low=new_low,
                close=new_close,
                volume=bar.volume,
                turnover=bar.turnover,
                change_pct=bar.change_pct,
                turnover_rate=bar.turnover_rate,
                amplitude=bar.amplitude,
            )
        )

    return adjusted


# K 线周期 → Tushare freq 参数
_FREQ_MAP: dict[BarInterval, str] = {
    BarInterval.M1: "1min",
    BarInterval.M5: "5min",
    BarInterval.M15: "15min",
    BarInterval.M30: "30min",
    BarInterval.M60: "60min",
    BarInterval.D1: "D",
    BarInterval.W1: "W",
    BarInterval.M: "M",
}

# 复权方式 → Tushare adj 参数（qfq/hfq/none）
_ADJ_MAP: dict[AdjustmentType, str] = {
    AdjustmentType.NONE: "none",
    AdjustmentType.FORWARD: "qfq",
    AdjustmentType.BACKWARD: "hfq",
}


# ---------- Adapter 实现 ----------


class TushareAdapter:
    """基于 Tushare Pro 的行情数据源。

    优势场景：K 线、财务、资金流、分红。
    弱势场景：实时报价（返回 None）、盘口（返回 None）— 这些由 efinance/腾讯兜底。
    """

    name = "tushare"

    def __init__(self, token: str | None = None) -> None:
        """token 默认从 TUSHARE_TOKEN 环境变量读；为空则所有方法返回 None。"""
        self._token = token or os.environ.get("TUSHARE_TOKEN", "")
        self._pro: Any = None
        if self._token:
            try:
                import tushare as ts

                ts.set_token(self._token)
                self._pro = ts.pro_api()
            except Exception as e:
                _log.warning("Tushare 初始化失败: %s", e)
                self._pro = None

    @property
    def is_available(self) -> bool:
        return self._pro is not None

    # ---------- 实时报价（Tushare 不提供，返回 None）----------

    def get_quote(self, code: str) -> Quote | None:
        """Tushare 是 EOD 数据，没有实时报价。

        但我们可以从 daily_basic 拼一个"最新可用"的快照（带 PE/PB/换手率等指标）。
        """
        if not self.is_available:
            return None
        try:
            ts_code = to_tushare_code(code)
            today = date.today().strftime("%Y%m%d")
            # 拿最近一个交易日的数据（往前查 30 天保证能命中）
            start = (date.today() - timedelta(days=30)).strftime("%Y%m%d")
            df = self._pro.daily_basic(
                ts_code=ts_code, start_date=start, end_date=today, limit=1
            )
            if df is None or df.empty:
                return None
            row = df.iloc[0]

            # 顺便拿一天 K 线补 open/high/low/close
            daily_df = self._pro.daily(
                ts_code=ts_code, start_date=start, end_date=today
            )
            if daily_df is None or daily_df.empty:
                return None
            daily_row = daily_df.iloc[0]

            return Quote(
                code=code,
                name="",  # Tushare 跨接口 join 比较重，这里先留空
                market=_detect_market_from_code(code),
                quote_type=_detect_quote_type(code),
                price=_to_dec(daily_row.get("close")) or Decimal("0"),
                open=_to_dec(daily_row.get("open")) or Decimal("0"),
                high=_to_dec(daily_row.get("high")) or Decimal("0"),
                low=_to_dec(daily_row.get("low")) or Decimal("0"),
                prev_close=_to_dec(daily_row.get("pre_close")) or Decimal("0"),
                change=_to_dec(daily_row.get("change")) or Decimal("0"),
                change_pct=_to_dec(daily_row.get("pct_chg")) or Decimal("0"),
                volume=_to_int(daily_row.get("vol")),
                turnover=_to_money(daily_row.get("amount")),
                turnover_rate=_to_dec(row.get("turnover_rate")),
                volume_ratio=None,
                pe_dynamic=_to_dec(row.get("pe")),
                # Tushare 市值单位是万元，需要 ×10000 转元
                # 先转 Decimal 再构造 Money（Money 不能直接 * Decimal）
                total_market_cap=(
                    Money((_to_dec(row.get("total_mv")) or Decimal("0")) * Decimal("10000"), "CNY")
                    if row.get("total_mv") is not None
                    else None
                ),
                circulating_market_cap=(
                    Money((_to_dec(row.get("circ_mv")) or Decimal("0")) * Decimal("10000"), "CNY")
                    if row.get("circ_mv") is not None
                    else None
                ),
                timestamp=datetime.now(),
                extra={"source": "tushare_eod", "trade_date": str(daily_row.get("trade_date", ""))},
            )
        except Exception as e:
            _log.debug("Tushare get_quote(%s) failed: %s", code, e)
            return None

    def get_quotes(self, codes: list[str]) -> list[Quote]:
        """批量：循环单股。失败跳过。"""
        out: list[Quote] = []
        seen: set[str] = set()
        for code in dict.fromkeys(codes):
            if code in seen:
                continue
            q = self.get_quote(code)
            if q is not None:
                out.append(q)
                seen.add(code)
        return out

    def list_market_quotes(self) -> list[Quote]:
        """全市场快照：Tushare 不适合（要拉几千次 daily_basic），返回空。

        这个场景用 efinance.list_market_quotes() 更合适。
        """
        return []

    # ---------- 盘口（Tushare 不提供）----------

    def get_order_book(self, code: str) -> OrderBook | None:
        return None

    # ---------- K 线（Tushare 强项）----------

    def get_bars(
        self,
        code: str,
        interval: BarInterval = BarInterval.D1,
        adjustment: AdjustmentType = AdjustmentType.FORWARD,
        start: date | None = None,
        end: date | None = None,
        limit: int | None = None,
    ) -> list[Bar]:
        """拉 K 线，支持前/后/不复权。

        实现：
        - 用 `tushare.pro_bar()` 顶层函数（内部会调 daily/weekly/monthly/stk_mins + adj_factor）
        - `adj='qfq'` 前复权 / `adj='hfq'` 后复权 / `adj=None` 不复权
        - 分钟线 Tushare 只支持最近 5 个交易日

        复权说明：
        - Tushare 的 `daily` 接口返回**不复权**原始价
        - `adj_factor` 是单独的复权因子接口
        - `pro_bar` 自动合并二者并计算复权价
        """
        if not self.is_available:
            return []

        ts_code = to_tushare_code(code)
        freq = _FREQ_MAP.get(interval)
        if freq is None:
            return []

        today = date.today()
        end_d = end or today
        if start is None:
            # 没指定 start 时根据 limit 推一个保守起点
            if interval == BarInterval.D1:
                years = max(1, (limit or 500) // 250 + 1)
                start_d = end_d - timedelta(days=int(years * 366))
            elif interval == BarInterval.W1:
                weeks = max(52, (limit or 200) + 4)
                start_d = end_d - timedelta(weeks=weeks)
            elif interval == BarInterval.M:
                months = max(24, (limit or 60) + 2)
                start_d = end_d - timedelta(days=int(months * 31))
            else:
                # 分钟线 Tushare 只支持最近 5 个交易日
                start_d = end_d - timedelta(days=5)
        else:
            start_d = start

        start_str = start_d.strftime("%Y%m%d")
        end_str = end_d.strftime("%Y%m%d")

        # 复权参数：None/qfq/hfq
        adj_param: str | None
        if adjustment == AdjustmentType.FORWARD:
            adj_param = "qfq"
        elif adjustment == AdjustmentType.BACKWARD:
            adj_param = "hfq"
        else:
            adj_param = None

        try:
            # 延迟 import pro_bar（避免冷启动慢）
            from tushare.pro.data_pro import pro_bar

            df = pro_bar(
                ts_code=ts_code,
                api=self._pro,
                start_date=start_str,
                end_date=end_str,
                freq=freq,
                asset="E",  # 股票
                adj=adj_param,
                factors=["tor"],  # 顺便拿换手率（turnover_rate）
            )
            if df is None or df.empty:
                return []
        except Exception as e:
            _log.debug("Tushare get_bars(%s, %s) failed: %s", code, interval, e)
            return []

        bars: list[Bar] = []
        for _, row in df.iterrows():
            trade_date = str(row.get("trade_date", ""))
            if not trade_date:
                continue
            try:
                ts = datetime.strptime(trade_date, "%Y%m%d")
            except ValueError:
                continue
            # 二次过滤（合并时可能超出范围）
            if start and ts.date() < start:
                continue
            if end and ts.date() > end:
                continue

            bars.append(
                Bar(
                    code=code,
                    name="",  # daily 接口不带 name，需要时再 join
                    interval=interval,
                    adjustment=adjustment,
                    timestamp=ts,
                    open=_to_dec(row.get("open")) or Decimal("0"),
                    high=_to_dec(row.get("high")) or Decimal("0"),
                    low=_to_dec(row.get("low")) or Decimal("0"),
                    close=_to_dec(row.get("close")) or Decimal("0"),
                    volume=_to_int(row.get("vol")),
                    turnover=_to_money(row.get("amount")),
                    change_pct=_to_dec(row.get("pct_chg")),
                    turnover_rate=None,  # daily 接口不返回
                    amplitude=None,
                )
            )

        bars.sort(key=lambda b: b.timestamp)
        if limit is not None:
            bars = bars[-limit:]
        return bars

    # ---------- Tick（Tushare 不提供分钟级逐笔）----------

    def get_ticks(self, code: str, limit: int | None = None) -> list[Tick]:
        return []

    # ---------- 资金流 ----------

    def _bill_df_to_flow(self, df: pd.DataFrame, code: str) -> list[MoneyFlow]:
        if df is None or df.empty:
            return []
        flows: list[MoneyFlow] = []
        for _, row in df.iterrows():
            trade_date = str(row.get("trade_date", ""))
            if not trade_date:
                continue
            try:
                ts = datetime.strptime(trade_date, "%Y%m%d")
            except ValueError:
                continue
            flows.append(
                MoneyFlow(
                    code=code,
                    name="",
                    timestamp=ts,
                    main_net=_to_money(row.get("net_mf_amount")),
                    small_net=_to_money(row.get("net_xl_amount")),  # 小单
                    medium_net=_to_money(row.get("net_l_amount")),  # 中单
                    large_net=_to_money(row.get("net_el_amount")),  # 大单
                    super_large_net=_to_money(row.get("net_vl_amount")),  # 超大单
                    main_net_ratio=None,  # moneyflow 接口不直接给占比
                )
            )
        return flows

    def get_today_money_flow(self, code: str) -> list[MoneyFlow]:
        """当日资金流：Tushare 是 EOD 一次给整天的，返回一个点。"""
        if not self.is_available:
            return []
        try:
            ts_code = to_tushare_code(code)
            today = date.today().strftime("%Y%m%d")
            # Tushare 不能"只看今天"，要看是否有今天的数据
            start = (date.today() - timedelta(days=7)).strftime("%Y%m%d")
            df = self._pro.moneyflow(ts_code=ts_code, start_date=start, end_date=today)
            if df is None or df.empty:
                return []
            # 取最新一条
            latest = df.iloc[0]
            trade_date = str(latest.get("trade_date", ""))
            if trade_date != today:
                # 当天数据可能还没出（盘后才更新），返回最近一天的
                pass
            return self._bill_df_to_flow(df.head(1), code)
        except Exception as e:
            _log.debug("Tushare get_today_money_flow(%s) failed: %s", code, e)
            return []

    def get_history_money_flow(self, code: str, days: int = 30) -> list[MoneyFlow]:
        """历史资金流：默认 30 天。"""
        if not self.is_available:
            return []
        try:
            ts_code = to_tushare_code(code)
            end = date.today()
            start = end - timedelta(days=days + 5)  # 多取几天避开节假日
            df = self._pro.moneyflow(
                ts_code=ts_code,
                start_date=start.strftime("%Y%m%d"),
                end_date=end.strftime("%Y%m%d"),
            )
            flows = self._bill_df_to_flow(df, code)
            cutoff = datetime.now() - timedelta(days=days)
            return [f for f in flows if f.timestamp >= cutoff]
        except Exception as e:
            _log.debug("Tushare get_history_money_flow(%s) failed: %s", code, e)
            return []

    # ---------- 复权便捷方法 ----------

    def fetch_and_adjust(
        self,
        code: str,
        interval: BarInterval = BarInterval.D1,
        mode: AdjustmentType = AdjustmentType.FORWARD,
        start: date | None = None,
        end: date | None = None,
        limit: int | None = None,
    ) -> list[Bar]:
        """一键拉取并复权：拉不复权 K 线 + 复权因子 + 应用前/后复权。

        适用场景：
        - 拉带复权的历史 K 线（pro_bar 在某些场景表现不如手动控制）
        - 调试 / 验证复权计算是否正确
        - 对**非 Tushare 数据源**（如 efinance）拉的不复权价应用复权

        实盘/盘中场景不需要调这个方法。

        实现：拉 `daily` 不复权 + 拉 `adj_factor` + 调 `apply_adjustment`。
        """
        if not self.is_available:
            return []

        # 1. 拉不复权 K 线
        bars = self.get_bars(
            code, interval, AdjustmentType.NONE, start=start, end=end, limit=limit
        )
        if not bars:
            return []

        # 2. 拉复权因子（用相同时间范围）
        ts_code = to_tushare_code(code)
        try:
            first_date = bars[0].timestamp.strftime("%Y%m%d")
            last_date = bars[-1].timestamp.strftime("%Y%m%d")
            adj_df = self._pro.adj_factor(
                ts_code=ts_code, start_date=first_date, end_date=last_date
            )
        except Exception as e:
            _log.debug("fetch_and_adjust: adj_factor failed for %s: %s", code, e)
            return bars  # 拿不到因子就返回原始

        # 3. 应用复权
        return apply_adjustment(bars, adj_df, mode)

    # ---------- 板块 ----------

    def get_belonging_boards(self, code: str) -> list[Board]:
        """Tushare 概念板块：通过 stock_basic → concept 或者 index_classify。

        用 index_classify 获取所有概念/行业指数列表，然后逐个查成分股。
        为效率，这里只查"所属"信息（用 limit_list_d 的 ts_code 反查所属概念不直接支持，
        退而求其次：用 concept 接口）。
        """
        if not self.is_available:
            return []
        # 留给 efinance.get_belong_board 兜底（Tushare concept 接口
        # 需要先拉所有概念 + 逐个查成分股，集成较重，先不强求）
        # 实测有日志需求时打开下面调试日志：
        # _log.debug("Tushare get_belonging_boards(%s) skipped: use efinance fallback", code)
        return []

    # ---------- 健康检查 ----------

    def health_check(self) -> bool:
        """拉一次交易日历（最便宜的接口），能拿到数据就算 OK。"""
        if not self.is_available:
            return False
        try:
            today = date.today().strftime("%Y%m%d")
            df = self._pro.trade_cal(exchange="SSE", start_date=today, end_date=today)
            return df is not None and not df.empty
        except Exception:
            return False

    # ---------- 财务数据（Tushare 强项）----------

    def get_financial_indicator(
        self,
        code: str,
        period: str | None = None,
        limit: int = 8,
    ) -> list[dict[str, Any]]:
        """拉取财务指标（PE/PB/ROE/资产负债率/毛利/净利 等）。

        参数:
            code: 6 位股票代码 '600519'
            period: 报告期 YYYYMMDD（如 '20240930' = 2024 Q3）；None = 最新期
            limit: 返回期数（默认 8 个季度 = 2 年）

        返回:
            list[dict]，每个 dict 是一期的财务指标，键名与 Tushare 原始字段一致
            （eps, roe, gross_profit_margin, debt_to_assets, current_ratio, ...）
            返回 [] 表示无 token / 拉取失败 / 无数据

        使用场景:
            - 选股过滤（ROE > 15%, 负债率 < 50%）
            - 回测/基本面分析
            - 长期价值跟踪
        """
        if not self.is_available:
            return []
        try:
            ts_code = to_tushare_code(code)
            kwargs: dict[str, Any] = {"ts_code": ts_code, "limit": limit}
            if period:
                kwargs["period"] = period
            df = self._pro.fina_indicator(**kwargs)
            if df is None or df.empty:
                return []
            return df.to_dict(orient="records")
        except Exception as e:
            _log.debug("Tushare get_financial_indicator(%s) failed: %s", code, e)
            return []

    def get_dividend_history(self, code: str, limit: int = 20) -> list[dict[str, Any]]:
        """拉取分红送股记录。

        参数:
            code: 6 位股票代码
            limit: 最多返回条数（默认 20 条）

        返回:
            list[dict]，字段：end_date, ann_date, div_proc, stk_div, stk_bo_rate,
            stk_co_rate, cash_div, cash_div_tax, record_date, ex_date, pay_date, ...

        使用场景:
            - 查历史分红率
            - 股息率计算
            - 回测分红再投资策略
        """
        if not self.is_available:
            return []
        try:
            ts_code = to_tushare_code(code)
            df = self._pro.dividend(ts_code=ts_code, limit=limit)
            if df is None or df.empty:
                return []
            return df.to_dict(orient="records")
        except Exception as e:
            _log.debug("Tushare get_dividend_history(%s) failed: %s", code, e)
            return []

    def get_income_statement(
        self,
        code: str,
        period: str | None = None,
        limit: int = 4,
    ) -> list[dict[str, Any]]:
        """拉取利润表（季报）。

        参数:
            code: 6 位股票代码
            period: 报告期 YYYYMMDD；None = 最新期
            limit: 返回期数

        返回:
            list[dict]，字段：total_revenue（营收）, operate_income（营业利润）,
            total_profit（利润总额）, n_income（净利润）, basic_eps（基本EPS）...
        """
        if not self.is_available:
            return []
        try:
            ts_code = to_tushare_code(code)
            kwargs: dict[str, Any] = {"ts_code": ts_code, "limit": limit}
            if period:
                kwargs["period"] = period
            df = self._pro.income(**kwargs)
            if df is None or df.empty:
                return []
            return df.to_dict(orient="records")
        except Exception as e:
            _log.debug("Tushare get_income_statement(%s) failed: %s", code, e)
            return []

    def get_balance_sheet(
        self,
        code: str,
        period: str | None = None,
        limit: int = 4,
    ) -> list[dict[str, Any]]:
        """拉取资产负债表。

        返回字段：total_assets, total_liab, total_equity, money_cap, accounts_receivable...
        """
        if not self.is_available:
            return []
        try:
            ts_code = to_tushare_code(code)
            kwargs: dict[str, Any] = {"ts_code": ts_code, "limit": limit}
            if period:
                kwargs["period"] = period
            df = self._pro.balancesheet(**kwargs)
            if df is None or df.empty:
                return []
            return df.to_dict(orient="records")
        except Exception as e:
            _log.debug("Tushare get_balance_sheet(%s) failed: %s", code, e)
            return []

    def get_cash_flow(
        self,
        code: str,
        period: str | None = None,
        limit: int = 4,
    ) -> list[dict[str, Any]]:
        """拉取现金流量表。

        返回字段：n_cashflow_act（经营现金流）, n_cashflow_inv_act（投资现金流）,
        n_cashflow_fin_act（筹资现金流）, free_cashflow...
        """
        if not self.is_available:
            return []
        try:
            ts_code = to_tushare_code(code)
            kwargs: dict[str, Any] = {"ts_code": ts_code, "limit": limit}
            if period:
                kwargs["period"] = period
            df = self._pro.cashflow(**kwargs)
            if df is None or df.empty:
                return []
            return df.to_dict(orient="records")
        except Exception as e:
            _log.debug("Tushare get_cash_flow(%s) failed: %s", code, e)
            return []

    def list_all_stocks(self, list_status: str = "L") -> list[dict[str, Any]]:
        """拉取全市场股票列表。

        参数:
            list_status: 'L' = 在市 / 'D' = 退市 / 'P' = 暂停上市

        返回:
            list[dict]，字段：ts_code, symbol, name, industry, list_date, ...

        使用场景:
            - 一次性缓存所有股票基本信息
            - 按行业过滤
            - 全市场扫描
        """
        if not self.is_available:
            return []
        try:
            df = self._pro.stock_basic(list_status=list_status)
            if df is None or df.empty:
                return []
            return df.to_dict(orient="records")
        except Exception as e:
            _log.debug("Tushare list_all_stocks failed: %s", e)
            return []
