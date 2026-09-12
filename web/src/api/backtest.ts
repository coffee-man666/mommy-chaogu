// 个股回测 API — 预测命中率策略的历史表现
import { apiGet } from './client'

/** 单只股票的回测结果（对应后端 GET /api/stocks/{code}/backtest）。 */
export interface BacktestResult {
  code: string
  hold_days: number
  start_date: string
  end_date: string
  total_signals: number
  /** 胜率 0..1 小数；无信号时为 null（净收益口径，扣往返交易成本） */
  win_rate: number | null
  /** 净收益（扣往返交易成本） */
  avg_return_pct: number | null
  max_drawdown_pct: number | null
  sharpe_ratio: number | null
  /** 毛收益（不扣成本），对照用 */
  avg_gross_return_pct: number | null
  /** 成本模型明细（多行文本） */
  cost_model: string | null
  /** 流通市值取自哪一天的报价缓存 */
  mcap_as_of: string | null
  /** 口径警示（如市值前视近似），应展示给用户 */
  caveats: string[]
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
