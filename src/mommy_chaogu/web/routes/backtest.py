"""/api/stocks/{code}/backtest 路由：个股一键回测。

完全离线：BacktestEngine 只在 market.db 缓存（资金流 + 日 K + 报价市值）
上回放 flow_in_spike 信号，不拉网络。hold_days 缺省时取服务端用户偏好
（/api/preferences）的持有周期派生值（short→3 / swing→5 / long→20）。
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from mommy_chaogu.backtest.engine import BacktestEngine
from mommy_chaogu.preferences import default_hold_days
from mommy_chaogu.watchlist import WatchlistStore
from mommy_chaogu.web.deps import get_backtest_engine, get_watchlist_store
from mommy_chaogu.web.schemas import StockBacktestOut

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/stocks", tags=["backtest"])

# 回测窗口：近一年
_WINDOW_DAYS = 365

_NO_SIGNAL_MESSAGE = "区间内未触发信号或缓存数据不足"


@router.get("/{code}/backtest", response_model=StockBacktestOut)
def get_stock_backtest(
    code: Annotated[str, Path(pattern=r"^\d{6}$")],
    engine: Annotated[BacktestEngine, Depends(get_backtest_engine)],
    store: Annotated[WatchlistStore, Depends(get_watchlist_store)],
    hold_days: Annotated[int | None, Query(ge=1, le=60)] = None,
) -> StockBacktestOut:
    """对单只股票回放 flow_in_spike 信号规则，返回汇总统计。

    hold_days 缺省时读服务端用户偏好的持有周期派生默认持有天数。
    无信号 / 缓存数据不足时统计字段为 null，message 给出中文提示。
    """
    if hold_days is None:
        try:
            prefs = store.get_user_preferences()
        except Exception as exc:
            _log.warning("读取用户偏好失败，回测使用默认持有天数: %s", exc)
            prefs = {}
        days = default_hold_days(str(prefs.get("holding_period", "swing")))
    else:
        days = hold_days

    end = date.today()
    start = end - timedelta(days=_WINDOW_DAYS)

    try:
        result = engine.run([code], start.isoformat(), end.isoformat(), hold_days=days)
    except Exception as exc:
        _log.exception("个股回测失败: code=%s", code)
        raise HTTPException(status_code=500, detail="回测计算失败，请稍后重试") from exc

    if result.total_signals > 0:
        return StockBacktestOut(
            code=code,
            hold_days=days,
            start_date=start,
            end_date=end,
            total_signals=result.total_signals,
            win_rate=round(result.win_rate, 4),
            avg_return_pct=result.avg_return_pct,
            max_drawdown_pct=result.max_drawdown_pct,
            sharpe_ratio=result.sharpe_ratio,
            message=None,
        )
    return StockBacktestOut(
        code=code,
        hold_days=days,
        start_date=start,
        end_date=end,
        total_signals=0,
        win_rate=None,
        avg_return_pct=None,
        max_drawdown_pct=None,
        sharpe_ratio=None,
        message=_NO_SIGNAL_MESSAGE,
    )
