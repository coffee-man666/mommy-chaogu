"""Efinance 数据源实现（基于东方财富）。

注意 efinance 是非官方 SDK，字段命名/返回结构不稳定：
- 单股 get_realtime_quotes(code) 经常坏 → 优先用全市场 + 过滤
- DataFrame 列名是中文，映射到英文 dataclass 字段
- Decimal 转换时统一 str() 走一遍，避免 float 精度漂移
"""

from __future__ import annotations

import contextlib
import warnings
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

import efinance as ef
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
    OrderBookLevel,
    Quote,
    QuoteType,
    Tick,
)

warnings.filterwarnings("ignore")


# ---------- 内部工具 ----------


def _to_dec(v: Any) -> Decimal | None:
    """安全转 Decimal，失败返回 None。"""
    if v is None or (isinstance(v, float) and pd.isna(v)):
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


def _detect_market(code: str) -> MarketType:
    """根据股票代码头推断市场。"""
    if code.startswith(("60", "68", "9")):  # 60xxx沪A主板, 688科创板, 9xx北交所
        if code.startswith("9"):
            return MarketType.BJ
        return MarketType.SH
    if code.startswith(("00", "30")):  # 00/30 深A
        return MarketType.SZ
    if code.startswith(("51", "15", "16", "18")):  # 场内基金/债券
        return MarketType.SH
    if code.startswith(("11", "12", "13", "14")):  # 深A基金/债券
        return MarketType.SZ
    return MarketType.UNKNOWN


def _detect_quote_type(code: str) -> QuoteType:
    """根据代码推断品种类型。"""
    if code.startswith(("51", "15", "16", "18", "11", "12", "13", "14")):
        return QuoteType.FUND
    return QuoteType.STOCK


# klt 参数映射（efinance 的 klt 编码）
_KLT_MAP: dict[BarInterval, int] = {
    BarInterval.M1: 1,
    BarInterval.M5: 5,
    BarInterval.M15: 15,
    BarInterval.M30: 30,
    BarInterval.M60: 60,
    BarInterval.D1: 101,
    BarInterval.W1: 102,
    BarInterval.M: 103,
}

# fqt 参数映射
_FQT_MAP: dict[AdjustmentType, int] = {
    AdjustmentType.NONE: 0,
    AdjustmentType.FORWARD: 1,
    AdjustmentType.BACKWARD: 2,
}


# ---------- Adapter 实现 ----------


class EfinanceAdapter:
    """基于东方财富的行情数据源。"""

    name = "efinance"

    # ---------- 内部：行/Series → Quote ----------

    def _row_to_quote(self, row: pd.Series) -> Quote:
        """将单行（从 get_latest_quote 或 get_realtime_quotes）转成 Quote。"""

        # 兼容两种列名：中文大写 vs "代码/名称"等
        def g(*keys: str) -> Any:
            for k in keys:
                if k in row:
                    return row[k]
            return None

        code = str(g("股票代码", "代码") or "")
        name = str(g("股票名称", "名称") or "")
        ts_str = str(g("更新时间", "时间") or "")
        # 时间解析：优先完整时间戳，否则只有 HH:MM:SS 时拼当日
        try:
            ts = pd.to_datetime(ts_str).to_pydatetime()
            if ts.tzinfo is None:
                ts = ts.replace()  # naive
        except Exception:
            ts = datetime.now()

        market_str = str(g("市场类型") or "")
        # efinance 市场类型如 "沪A" / "深A" / "京A"
        if "沪" in market_str:
            market = MarketType.SH
        elif "深" in market_str:
            market = MarketType.SZ
        elif "京" in market_str:
            market = MarketType.BJ
        else:
            market = _detect_market(code)

        return Quote(
            code=code,
            name=name,
            market=market,
            quote_type=_detect_quote_type(code),
            price=_to_dec(g("最新价")) or Decimal("0"),
            open=_to_dec(g("今开")) or Decimal("0"),
            high=_to_dec(g("最高")) or Decimal("0"),
            low=_to_dec(g("最低")) or Decimal("0"),
            prev_close=_to_dec(g("昨日收盘")) or Decimal("0"),
            change=_to_dec(g("涨跌额")) or Decimal("0"),
            change_pct=_to_dec(g("涨跌幅")) or Decimal("0"),
            volume=_to_int(g("成交量")),
            turnover=_to_money(g("成交额")),
            turnover_rate=_to_dec(g("换手率")),
            volume_ratio=_to_dec(g("量比")),
            pe_dynamic=_to_dec(g("动态市盈率")),
            total_market_cap=_to_money(g("总市值")) if g("总市值") is not None else None,
            circulating_market_cap=_to_money(g("流通市值")) if g("流通市值") is not None else None,
            timestamp=ts,
            quote_id=str(g("行情ID") or "") or None,
            extra={"market_type_raw": market_str} if market_str else {},
        )

    # ---------- 实时报价 ----------

    def get_quote(self, code: str) -> Quote | None:
        """单股实时。efinance 的 get_realtime_quotes(code) 经常坏，用 get_latest_quote 兜底。

        东财 push2.eastmoney.com 冷启动可能超时，本方法带 2 次重试。
        """
        import time as _time

        df = None
        last_err: Exception | None = None
        for attempt in range(3):
            try:
                df = ef.stock.get_latest_quote(code)
                if df is not None and not df.empty:
                    break
            except Exception as e:
                last_err = e
                _time.sleep(0.5 * (attempt + 1))
        if df is None or df.empty:
            if last_err is not None:
                import logging

                logging.getLogger(__name__).warning(
                    "get_quote(%s) failed after 3 retries: %s",
                    code,
                    last_err,
                )
            return None
        try:
            return self._row_to_quote(df.iloc[0])
        except Exception as e:
            import logging

            logging.getLogger(__name__).warning("_row_to_quote(%s) failed: %s", code, e)
            return None

    def get_quotes(self, codes: list[str]) -> list[Quote]:
        """批量：循环单股，失败的跳过。

        东财接口冷启动可能超时，本方法会先预热一次 get_realtime_quotes()
        （全市场快照走同个东财 endpoint）能提高后续成功率。
        """
        # 预热：调一次全市场走东财接口（失败也没关系）
        with contextlib.suppress(Exception):
            ef.stock.get_realtime_quotes()

        out: list[Quote] = []
        seen: set[str] = set()
        for code in dict.fromkeys(codes):  # 去重保持顺序
            if code in seen:
                continue
            q = self.get_quote(code)
            if q is not None:
                out.append(q)
                seen.add(code)
        return out

    def list_market_quotes(self) -> list[Quote]:
        """全市场实时快照（~5000+ 条）。"""
        try:
            df = ef.stock.get_realtime_quotes()
        except Exception:
            return []
        if df is None or df.empty:
            return []
        out: list[Quote] = []
        for _, row in df.iterrows():
            try:
                out.append(self._row_to_quote(row))
            except Exception:
                continue
        return out

    # ---------- 盘口 ----------

    def get_order_book(self, code: str) -> OrderBook | None:
        """5 档盘口。来自 get_quote_snapshot（Series, 37 项）。

        efinance 字段命名约定：`买i价`/`买i数量`/`卖i价`/`卖i数量` (i=1..5)。
        """
        try:
            ser = ef.stock.get_quote_snapshot(code)
        except Exception:
            return None
        if ser is None or len(ser) == 0:
            return None

        bids: list[OrderBookLevel] = []
        asks: list[OrderBookLevel] = []
        for i in range(1, 6):
            bp = ser.get(f"买{i}价")
            bv = ser.get(f"买{i}数量")
            ap = ser.get(f"卖{i}价")
            av = ser.get(f"卖{i}数量")
            # 跳过 NaN / 0 价（无效档位）
            bp_dec = _to_dec(bp) if bp is not None and not pd.isna(bp) else None
            ap_dec = _to_dec(ap) if ap is not None and not pd.isna(ap) else None
            if bp_dec is not None and bp_dec > 0:
                bids.append(OrderBookLevel(price=bp_dec, volume=_to_int(bv)))
            if ap_dec is not None and ap_dec > 0:
                asks.append(OrderBookLevel(price=ap_dec, volume=_to_int(av)))

        ts_raw = ser.get("时间", "")
        try:
            ts = pd.to_datetime(str(ts_raw)).to_pydatetime()
        except Exception:
            ts = datetime.now()

        return OrderBook(
            code=str(ser.get("代码", code)),
            name=str(ser.get("名称", "")),
            timestamp=ts,
            bids=tuple(bids),
            asks=tuple(asks),
            last_price=_to_dec(ser.get("最新价")),
            last_volume=_to_int(ser.get("成交量")),
        )

    # ---------- K 线 ----------

    def get_bars(
        self,
        code: str,
        interval: BarInterval = BarInterval.D1,
        adjustment: AdjustmentType = AdjustmentType.FORWARD,
        start: date | None = None,
        end: date | None = None,
        limit: int | None = None,
    ) -> list[Bar]:
        """拉取 K 线。

        注意事项：
        1. efinance 默认 beg=19000101 / end=20500101 请求 150 年全量数据，
           东财接口 push2his.eastmoney.com 经常断连。本方法根据 interval
           自动收缩范围，limit=1000 时只取最近 ~4 年日线。
        2. 失败重试 2 次（带退避）。
        """
        import time as _time

        # 推断东财接口需要的 beg/end（YYYYMMDD）
        beg, end_ymd = self._resolve_kline_range(interval, start, end, limit)

        df = None
        for attempt in range(3):
            try:
                df = ef.stock.get_quote_history(
                    code,
                    klt=_KLT_MAP.get(interval, 101),
                    fqt=_FQT_MAP.get(adjustment, 1),
                    beg=beg,
                    end=end_ymd,
                )
                if df is not None and not df.empty:
                    break
            except Exception:
                _time.sleep(0.5 * (attempt + 1))
        if df is None or df.empty:
            return []

        bars: list[Bar] = []
        for _, row in df.iterrows():
            try:
                ts = pd.to_datetime(row.get("日期")).to_pydatetime()
            except Exception:
                continue
            # 应用调用方的 start/end 二次过滤
            if start and ts.date() < start:
                continue
            if end and ts.date() > end:
                continue

            name = str(row.get("股票名称", ""))
            bars.append(
                Bar(
                    code=code,
                    name=name,
                    interval=interval,
                    adjustment=adjustment,
                    timestamp=ts,
                    open=_to_dec(row.get("开盘")) or Decimal("0"),
                    high=_to_dec(row.get("最高")) or Decimal("0"),
                    low=_to_dec(row.get("最低")) or Decimal("0"),
                    close=_to_dec(row.get("收盘")) or Decimal("0"),
                    volume=_to_int(row.get("成交量")),
                    turnover=_to_money(row.get("成交额")),
                    change_pct=_to_dec(row.get("涨跌幅")),
                    turnover_rate=_to_dec(row.get("换手率")),
                    amplitude=_to_dec(row.get("振幅")),
                )
            )

        bars.sort(key=lambda b: b.timestamp)
        if limit is not None:
            bars = bars[-limit:]
        return bars

    @staticmethod
    def _resolve_kline_range(
        interval: BarInterval,
        start: date | None,
        end: date | None,
        limit: int | None,
    ) -> tuple[str, str]:
        """根据 interval + limit 推断东财 beg/end（YYYYMMDD）。"""
        today = date.today()
        end_d = end or today
        if start is not None:
            start_d = start
        else:
            # 没指定 start 时，根据 limit 推一个保守的起点
            if interval == BarInterval.D1:
                # 日线 ~ 250 交易日/年
                years = max(1, (limit or 500) // 250 + 1)
                start_d = end_d - timedelta(days=int(years * 366))
            elif interval == BarInterval.W1:
                weeks = max(52, (limit or 200) + 4)
                start_d = end_d - timedelta(weeks=weeks)
            elif interval == BarInterval.M:
                months = max(24, (limit or 60) + 2)
                start_d = end_d - timedelta(days=int(months * 31))
            elif interval in (
                BarInterval.M1,
                BarInterval.M5,
                BarInterval.M15,
                BarInterval.M30,
                BarInterval.M60,
            ):
                # 分钟线 ~ 240 根/天
                days = max(5, (limit or 240) // 240 + 5)
                start_d = end_d - timedelta(days=days)
            else:
                start_d = end_d - timedelta(days=365)
        return start_d.strftime("%Y%m%d"), end_d.strftime("%Y%m%d")

    # ---------- Tick ----------

    def get_ticks(self, code: str, limit: int | None = None) -> list[Tick]:
        """当日成交明细。

        注意：efinance 的 get_deal_detail 走 push2.eastmoney.com，
        默认 max_count=1,000,000 会导致东财接口超时。
        本方法用合理的 max_count（默认 5000，覆盖一整天分钟级成交），
        失败返回空列表而不是抛异常。
        """
        import time as _time

        # limit 转为 max_count（多取一些保证 limit 够用）
        max_count = 5000 if limit is None else min(limit * 4, 5000)
        df = None
        for attempt in range(2):
            try:
                df = ef.stock.get_deal_detail(code, max_count=max_count)
                if df is not None and not df.empty:
                    break
            except Exception:
                _time.sleep(0.5 * (attempt + 1))
        if df is None or df.empty:
            return []

        ticks: list[Tick] = []
        for _, row in df.iterrows():
            ts_raw = str(row.get("时间", ""))
            try:
                ts = pd.to_datetime(ts_raw).to_pydatetime()
            except Exception:
                continue
            ticks.append(
                Tick(
                    code=code,
                    name=str(row.get("股票名称", "")),
                    timestamp=ts,
                    price=_to_dec(row.get("成交价")) or Decimal("0"),
                    volume=_to_int(row.get("成交量")),
                    prev_close=_to_dec(row.get("昨收")) or Decimal("0"),
                    trade_count=_to_int(row.get("单数")) or None,
                )
            )
        if limit is not None:
            ticks = ticks[:limit]
        return ticks

    # ---------- 资金流 ----------

    def _bill_rows_to_flow(self, df: pd.DataFrame, code: str) -> list[MoneyFlow]:
        if df is None or df.empty:
            return []
        flows: list[MoneyFlow] = []
        for _, row in df.iterrows():
            ts_raw = str(row.get("时间", row.get("日期", "")))
            try:
                ts = pd.to_datetime(ts_raw).to_pydatetime()
            except Exception:
                continue
            flows.append(
                MoneyFlow(
                    code=code,
                    name=str(row.get("股票名称", "")),
                    timestamp=ts,
                    main_net=_to_money(row.get("主力净流入")),
                    small_net=_to_money(row.get("小单净流入")),
                    medium_net=_to_money(row.get("中单净流入")),
                    large_net=_to_money(row.get("大单净流入")),
                    super_large_net=_to_money(row.get("超大单净流入")),
                    main_net_ratio=_to_dec(row.get("主力净流入占比")),
                )
            )
        return flows

    def get_today_money_flow(self, code: str) -> list[MoneyFlow]:
        try:
            df = ef.stock.get_today_bill(code)
        except Exception:
            return []
        return self._bill_rows_to_flow(df, code)

    def get_history_money_flow(self, code: str, days: int = 30) -> list[MoneyFlow]:
        try:
            df = ef.stock.get_history_bill(code)
        except Exception:
            return []
        flows = self._bill_rows_to_flow(df, code)
        # 只取最近 N 天
        cutoff = datetime.now() - timedelta(days=days)
        return [f for f in flows if f.timestamp >= cutoff]

    # ---------- 板块 ----------

    def get_belonging_boards(self, code: str) -> list[Board]:
        try:
            df = ef.stock.get_belong_board(code)
        except Exception:
            return []
        if df is None or df.empty:
            return []
        boards: list[Board] = []
        seen: set[str] = set()
        for _, row in df.iterrows():
            bcode = str(row.get("板块代码", ""))
            if not bcode or bcode in seen:
                continue
            seen.add(bcode)
            boards.append(
                Board(
                    code=bcode,
                    name=str(row.get("板块名称", "")),
                    change_pct=_to_dec(row.get("板块涨幅")),
                )
            )
        return boards

    # ---------- 健康检查 ----------

    def health_check(self) -> bool:
        """拉一次全市场快照，能拿到数据就算 OK。"""
        try:
            df = ef.stock.get_realtime_quotes()
            return df is not None and not df.empty
        except Exception:
            return False
