// 个股回测 API — 预测命中率策略的历史表现
import { apiGet } from './client'

/** 单只股票的回测结果（对应后端 GET /api/stocks/{code}/backtest）。 */
export interface BacktestResult {
  code: string
  hold_days: number
  start_date: string
  end_date: string
  total_signals: number
  /** 胜率 0..1 小数；无信号时为 null */
  win_rate: number | null
  avg_return_pct: number | null
  max_drawdown_pct: number | null
  sharpe_ratio: number | null
  /** total_signals == 0 时的中文提示（原样展示）；否则 null */
  message: string | null
}

/**
 * 获取指定股票的回测结果。
 * holdDays 不传时省略该参数，由服务端按用户偏好取默认持有天数。
 */
export function getStockBacktest(code: string, holdDays?: number): Promise<BacktestResult> {
  const query = holdDays === undefined ? '' : `?hold_days=${holdDays}`
  return apiGet<BacktestResult>(`/api/stocks/${encodeURIComponent(code)}/backtest${query}`)
}
