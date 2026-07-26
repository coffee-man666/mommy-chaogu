"""AKShare 数据源实现（开源、无 token）。

定位（详见 docs/ADR/akshare-integration）：
- 与 efinance **共享东财后端**（push2his.eastmoney.com），所以不是 efinance
  的故障兜底（东财挂的时候 akshare 也挂），而是**字段补全源**：
  - ``stock_zh_a_spot_em`` 一次性给 PE/PB/总市值/流通市值/换手率/量比，efinance
    单股接口这些字段经常缺
  - 实时报价的字段权威性比 efinance 单股接口高
- fallback 链里放在 efinance + tencent **之后**，只在前面都失败/字段缺失时补位。

为什么 akshare 不是第一选择：
- 依赖体积大（~100MB，拉 decoractor / xlrd / minio 等一堆东西）
- 接口函数多（~3000 个），版本飘移时字段会变，列名是中文
- ``stock_zh_a_hist`` 是 KeyError 重灾区（akfamily/akshare 一堆 issue）

第一步实现范围（最小可用）：
- ``list_market_quotes`` / ``get_quote`` / ``get_quotes``：走 ``stock_zh_a_spot_em``
- ``get_bars``：日/周/月走 ``stock_zh_a_hist``，分钟走 ``stock_zh_a_hist_min_em``
- ``health_check``：单股基本信息接口（``stock_individual_info_em``）

其余方法返回 None/[] 让 fallback 接管（资金流 / 板块 / 盘口 / tick）。
"""

from __future__ import annotations

import logging
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

_log = logging.getLogger(__name__)


# ---------- 内部工具（与 efinance/tencent adapter 同约定）----------


def _to_dec(v: Any) -> Decimal | None:
    """安全转 Decimal，失败/NaN 返回 None。"""
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


def _detect_market(code: str) -> MarketType:
    """根据 6 位代码头推断市场（与 efinance_adapter 一致）。"""
    if code.startswith(("60", "68")):
        return MarketType.SH
    if code.startswith("9"):
        return MarketType.BJ
    if code.startswith(("00", "30")):
        return MarketType.SZ
    if code.startswith(("51", "15", "16", "18")):
        return MarketType.SH
    if code.startswith(("11", "12", "13", "14")):
        return MarketType.SZ
    if code.startswith(("4", "8")):
        return MarketType.BJ
    return MarketType.UNKNOWN


def _detect_quote_type(code: str) -> QuoteType:
    if code.startswith(("51", "15", "16", "18", "11", "12", "13", "14")):
        return QuoteType.FUND
    return QuoteType.STOCK


# 复权方式 → akshare adjust 参数
_ADJ_MAP: dict[AdjustmentType, str] = {
    AdjustmentType.NONE: "",
    AdjustmentType.FORWARD: "qfq",
    AdjustmentType.BACKWARD: "hfq",
}

# K 线周期 → akshare period（日/周/月）
_PERIOD_DWM: dict[BarInterval, str] = {
    BarInterval.D1: "daily",
    BarInterval.W1: "weekly",
    BarInterval.M: "monthly",
}

# K 线周期 → akshare 分钟 period（字符串）
_PERIOD_MIN: dict[BarInterval, str] = {
    BarInterval.M1: "1",
    BarInterval.M5: "5",
    BarInterval.M15: "15",
    BarInterval.M30: "30",
    BarInterval.M60: "60",
}


def _safe_akshare() -> Any:
    """延迟 import akshare（避免冷启动 / 未装时整个包加载失败）。

    失败抛 ImportError，调用方在 try/except 里转成空返回。
    """
    import akshare as ak

    return ak


# ---------- Adapter 实现 ----------


class AkShareAdapter:
    """基于 AKShare 的行情数据源（东财 + 新浪等多源后端，无 token）。

    强项：实时全市场快照字段全（PE/PB/市值/换手率/量比）、日/周/月/分钟 K 线、
          历史资金流（~100 天，含主力/超大/大/中/小单净额 + 占比）。
    弱项：逐笔/盘口（akshare 无稳定接口）、板块成分反查（要遍历全市场太重，
          efinance.get_belong_board 单股直查已足够）。
    """

    name = "akshare"

    # ---------- 内部：spot 行 → Quote ----------

    def _spot_row_to_quote(self, row: pd.Series) -> Quote | None:
        """``stock_zh_a_spot_em`` 的一行 → Quote。

        列名是中文，akshare 版本飘移时可能 KeyError，统一在调用方 try/except。
        """
        code = str(row.get("代码", "")).strip()
        if not code:
            return None

        name = str(row.get("名称", ""))
        market = _detect_market(code)
        quote_type = _detect_quote_type(code)

        return Quote(
            code=code,
            name=name,
            market=market,
            quote_type=quote_type,
            price=_to_dec(row.get("最新价")) or Decimal("0"),
            open=_to_dec(row.get("今开")) or Decimal("0"),
            high=_to_dec(row.get("最高")) or Decimal("0"),
            low=_to_dec(row.get("最低")) or Decimal("0"),
            prev_close=_to_dec(row.get("昨收")) or Decimal("0"),
            change=_to_dec(row.get("涨跌额")) or Decimal("0"),
            change_pct=_to_dec(row.get("涨跌幅")) or Decimal("0"),
            volume=_to_int(row.get("成交量")),
            turnover=_to_money(row.get("成交额")),
            turnover_rate=_to_dec(row.get("换手率")),
            volume_ratio=_to_dec(row.get("量比")),
            pe_dynamic=_to_dec(row.get("市盈率-动态")),
            total_market_cap=_to_money(row.get("总市值"))
            if _to_dec(row.get("总市值")) is not None
            else None,
            circulating_market_cap=_to_money(row.get("流通市值"))
            if _to_dec(row.get("流通市值")) is not None
            else None,
            timestamp=datetime.now(),
            extra={"source": "akshare_spot_em"},
        )

    def _fetch_spot_df(self) -> pd.DataFrame | None:
        """拉全市场 spot，失败返回 None。"""
        try:
            ak = _safe_akshare()
            df = ak.stock_zh_a_spot_em()
        except Exception as e:
            _log.debug("akshare stock_zh_a_spot_em failed: %s", e)
            return None
        if df is None or df.empty:
            return None
        return df

    # ---------- 实时报价 ----------

    def get_quote(self, code: str) -> Quote | None:
        """单股：从全市场 spot 过滤一条。

        akshare 没有干净的单股实时接口（``stock_individual_info_em`` 是静态基本信息，
        不是实时报价），所以单股也走全市场。配合 CachedMarketDataAdapter 层，
        多次单股调用会被缓存复用同一次全市场拉取。
        """
        df = self._fetch_spot_df()
        if df is None:
            return None
        try:
            row = df[df["代码"] == code]
        except KeyError:
            return None
        if row.empty:
            return None
        try:
            return self._spot_row_to_quote(row.iloc[0])
        except Exception as e:
            _log.debug("akshare get_quote(%s) row mapping failed: %s", code, e)
            return None

    def get_quotes(self, codes: list[str]) -> list[Quote]:
        """批量：一次全市场 + 过滤。比循环单股快。"""
        df = self._fetch_spot_df()
        if df is None:
            return []
        try:
            code_set = set(dict.fromkeys(codes))  # 去重保持顺序
            mask = df["代码"].isin(code_set)
            subset = df[mask]
        except KeyError:
            return []

        out: list[Quote] = []
        seen: set[str] = set()
        for _, row in subset.iterrows():
            try:
                q = self._spot_row_to_quote(row)
            except Exception:
                continue
            if q is not None and q.code not in seen:
                out.append(q)
                seen.add(q.code)
        return out

    def list_market_quotes(self) -> list[Quote]:
        """全市场实时快照（~5000 条）。akshare 最强项。"""
        df = self._fetch_spot_df()
        if df is None:
            return []
        out: list[Quote] = []
        for _, row in df.iterrows():
            try:
                q = self._spot_row_to_quote(row)
            except Exception:
                continue
            if q is not None:
                out.append(q)
        return out

    # ---------- 盘口（第一步不实现）----------

    def get_order_book(self, code: str) -> OrderBook | None:
        """akshare 没有干净的 5 档盘口接口，留给 efinance/tencent。"""
        return None

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
        """拉 K 线。

        - 日/周/月：``stock_zh_a_hist(symbol, period, start_date, end_date, adjust)``
        - 分钟：``stock_zh_a_hist_min_em(symbol, start_date, end_date, period, adjust)``
          注意 akshare 分钟线只能返回近期数据（1 分钟只有当日，其余近几个交易日）。

        复权直接通过 akshare 的 ``adjust`` 参数处理（qfq/hfq/""），无需手动算因子。
        """
        try:
            ak = _safe_akshare()
        except ImportError as e:
            _log.debug("akshare not installed: %s", e)
            return []

        today = date.today()
        end_d = end or today
        start_d = self._default_start(interval, end_d, limit) if start is None else start

        adj_param = _ADJ_MAP.get(adjustment, "")
        start_str = start_d.strftime("%Y%m%d")
        end_str = end_d.strftime("%Y%m%d")

        try:
            if interval in _PERIOD_DWM:
                df = ak.stock_zh_a_hist(
                    symbol=code,
                    period=_PERIOD_DWM[interval],
                    start_date=start_str,
                    end_date=end_str,
                    adjust=adj_param,
                )
            elif interval in _PERIOD_MIN:
                # 分钟接口的 start_date/end_date 是 "YYYY-MM-DD HH:MM:SS"
                df = ak.stock_zh_a_hist_min_em(
                    symbol=code,
                    start_date=start_d.strftime("%Y-%m-%d 09:30:00"),
                    end_date=end_d.strftime("%Y-%m-%d 15:00:00"),
                    period=_PERIOD_MIN[interval],
                    adjust=adj_param,
                )
            else:
                return []
        except Exception as e:
            _log.debug("akshare get_bars(%s, %s) failed: %s", code, interval, e)
            return []

        if df is None or df.empty:
            return []

        bars: list[Bar] = []
        for _, row in df.iterrows():
            ts = self._parse_row_timestamp(row, interval)
            if ts is None:
                continue
            # 二次过滤（合并时可能超出范围）
            if start and ts.date() < start:
                continue
            if end and ts.date() > end:
                continue

            bars.append(
                Bar(
                    code=code,
                    name="",  # stock_zh_a_hist 不带名称
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
    def _default_start(
        interval: BarInterval, end_d: date, limit: int | None
    ) -> date:
        """没指定 start 时，根据 interval + limit 推一个保守起点。"""
        if interval == BarInterval.D1:
            years = max(1, (limit or 500) // 250 + 1)
            return end_d - timedelta(days=int(years * 366))
        if interval == BarInterval.W1:
            weeks = max(52, (limit or 200) + 4)
            return end_d - timedelta(weeks=weeks)
        if interval == BarInterval.M:
            months = max(24, (limit or 60) + 2)
            return end_d - timedelta(days=int(months * 31))
        # 分钟线 akshare 只能返回近期
        return end_d - timedelta(days=5)

    @staticmethod
    def _parse_row_timestamp(row: pd.Series, interval: BarInterval) -> datetime | None:
        """从行里解析时间戳。日/周/月是 ``日期`` (YYYY-MM-DD)，分钟是 ``时间``。"""
        raw = row.get("时间", "") if interval in _PERIOD_MIN else row.get("日期", "")
        if raw is None or raw == "":
            return None
        try:
            ts: datetime = pd.to_datetime(str(raw)).to_pydatetime()
        except Exception:
            return None
        return ts

    # ---------- Tick（第一步不实现）----------

    def get_ticks(self, code: str, limit: int | None = None) -> list[Tick]:
        """akshare 没有逐笔成交的稳定接口（只有分钟 bar），返回空。"""
        return []

    # ---------- 资金流 ----------

    @staticmethod
    def _fund_flow_market_suffix(code: str) -> str:
        """``stock_individual_fund_flow`` 要 market 参数（sh/sz/bj）。

        接口源码 market_map: sh=1, sz=0, bj=0。未知代码默认 sh（不会报错，
        只是拿不到数据，调用方 try/except 兜住）。
        """
        m = _detect_market(code)
        if m == MarketType.SZ:
            return "sz"
        if m == MarketType.BJ:
            return "bj"
        return "sh"

    def _fetch_fund_flow_df(self, code: str) -> pd.DataFrame | None:
        """拉个股资金流（近期，~100 天）。失败返回 None。

        字段（来自 akshare 源码 stock_fund_em.py:52-68）：
            日期(date) / 收盘价 / 涨跌幅 / 主力净流入-净额 / 主力净流入-净占比 /
            超大单净流入-净额 / 超大单净流入-净占比 / 大单… / 中单… / 小单…
        """
        try:
            ak = _safe_akshare()
            df = ak.stock_individual_fund_flow(
                stock=code, market=self._fund_flow_market_suffix(code)
            )
        except Exception as e:
            _log.debug("akshare stock_individual_fund_flow(%s) failed: %s", code, e)
            return None
        if df is None or df.empty:
            return None
        return df

    def _fund_flow_df_to_flows(self, df: pd.DataFrame, code: str) -> list[MoneyFlow]:
        """fund_flow DataFrame → list[MoneyFlow]。"""
        flows: list[MoneyFlow] = []
        for _, row in df.iterrows():
            # 日期列 akshare 已经 to_datetime().dt.date 过，是 date 对象
            d_raw = row.get("日期")
            if isinstance(d_raw, date) and not isinstance(d_raw, datetime):
                ts = datetime.combine(d_raw, datetime.min.time())
            else:
                try:
                    ts = pd.to_datetime(str(d_raw)).to_pydatetime()
                except Exception:
                    continue
            flows.append(
                MoneyFlow(
                    code=code,
                    name="",  # 接口不返回名称
                    timestamp=ts,
                    main_net=_to_money(row.get("主力净流入-净额")),
                    small_net=_to_money(row.get("小单净流入-净额")),
                    medium_net=_to_money(row.get("中单净流入-净额")),
                    large_net=_to_money(row.get("大单净流入-净额")),
                    super_large_net=_to_money(row.get("超大单净流入-净额")),
                    main_net_ratio=_to_dec(row.get("主力净流入-净占比")),
                )
            )
        return flows

    def get_today_money_flow(self, code: str) -> list[MoneyFlow]:
        """当日资金流：取接口返回的最新一行（盘后更新）。

        akshare 的 ``stock_individual_fund_flow`` 走东财 klines 端点，返回的是
        **升序**（最早在前，源码 stock_fund_em.py 不重新排序），所以不能用
        ``iloc[0]``。这里显式取 ``日期`` 最大那行，不依赖输入顺序，防止上游
        字段/排序漂移导致取到 ~100 天前的旧行。
        """
        df = self._fetch_fund_flow_df(code)
        if df is None:
            return []
        try:
            latest = df.sort_values("日期", ascending=False).iloc[0:1]
        except Exception:
            return []
        return self._fund_flow_df_to_flows(latest, code)

    def get_history_money_flow(self, code: str, days: int = 30) -> list[MoneyFlow]:
        """历史资金流：akshare 一次给 ~100 天，客户端按 days 截断。"""
        df = self._fetch_fund_flow_df(code)
        if df is None:
            return []
        flows = self._fund_flow_df_to_flows(df, code)
        cutoff = datetime.now() - timedelta(days=days)
        return [f for f in flows if f.timestamp >= cutoff]

    # ---------- 板块 ----------

    def get_belonging_boards(self, code: str) -> list[Board]:
        """返回空，留给 efinance。

        akshare 没有"单股 → 所属板块"的直接接口，只能遍历所有板块成分股反查
        （~200 次 HTTP），太重。efinance.get_belong_board 是单股直接接口（1 次
        HTTP），已在 fallback 链里兜底，akshare 在这里没有增量价值。
        """
        return []

    # ---------- 健康检查 ----------

    def health_check(self) -> bool:
        """轻量健康检查：单股基本信息接口（1 次 HTTP），不拉全市场 spot。

        用 ``stock_individual_info_em(symbol="600519")`` 探测——单股静态信息，
        比 ``stock_zh_a_spot_em``（全市场 5000+ 行、1-3 秒）快得多，适合启动 /
        心跳场景。
        """
        try:
            ak = _safe_akshare()
            df = ak.stock_individual_info_em(symbol="600519")
        except Exception as e:
            _log.debug("akshare health_check failed: %s", e)
            return False
        return df is not None and not df.empty
