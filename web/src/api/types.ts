// API 类型定义（对应后端 Pydantic schemas）

export interface Quote {
  code: string
  name: string
  market: string
  price: string  // Decimal → string
  change: string
  change_pct: string
  volume: number
  turnover: string
  open: string
  high: string
  low: string
  prev_close: string
  pe: string | null
  pb: string | null
  turnover_rate: string | null
  volume_ratio: string | null
  main_net_inflow: string | null
  timestamp: string
  fetched_at: string
  data_age_seconds: number
}

export interface Snapshot {
  timestamp: string
  quotes: Quote[]
  total_main_net: string
  n_codes: number
  n_up: number
  n_down: number
  n_flat: number
}

export interface Bar {
  timestamp: string
  open: string
  high: string
  low: string
  close: string
  volume: number
  turnover: string
}

export interface OrderBookLevel {
  price: string
  volume: number
}

export interface OrderBook {
  code: string
  timestamp: string
  bids: OrderBookLevel[]
  asks: OrderBookLevel[]
}

export interface WatchlistStock {
  code: string
  name: string
  group: string
  note: string
  added_at: string
}

export interface WatchlistGroup {
  name: string
  description: string
  n_stocks: number
}

export interface Signal {
  timestamp: string
  code: string
  name: string
  rule_id: string
  severity: 'info' | 'warning' | 'critical'
  title: string
  detail: string
  trigger_value: string | null
  threshold_value: string | null
}

export interface CacheStats {
  hits: number
  fetches: number
  fetch_ok: number
  fetch_fail: number
  miss: number
  hit_rate: number
  freshness: Array<{
    code: string
    name: string
    fetched_at: string
    quote_ts: string
    age_seconds: number
  }>
}

export interface Health {
  ok: boolean
  adapter_name: string
  uptime_seconds: number
  last_snapshot_at: string | null
}

// ---------- Portfolio ----------

export interface PositionDetail {
  id: number
  code: string
  name: string | null
  avg_cost: string
  shares: number
  current_price: string | null
  market_value: string | null
  total_cost: string
  unrealized_pnl: string | null
  unrealized_pnl_pct: string | null
  buy_date: string | null
  note: string
  created_at: string
  updated_at: string
}

export interface PortfolioSummary {
  positions: PositionDetail[]
  total_cost: string
  total_market_value: string | null
  total_unrealized_pnl: string | null
  total_unrealized_pnl_pct: string | null
  n_positions: number
}

export interface Position {
  id: number
  code: string
  name: string | null
  buy_price: string
  shares: number
  buy_date: string | null
  note: string
  created_at: string
  updated_at: string
}

export interface Adjustment {
  id: number
  position_id: number
  action: 'buy' | 'sell' | 'dividend'
  price: string
  shares: number
  timestamp: string
  note: string
}

// ---------- Market Ranking ----------

export interface IndexQuote {
  code: string
  name: string
  price: string
  change_pct: string
  prev_close: string
}

export interface SectorQuote {
  code: string
  name: string
  change_pct: string
  price: string
}

export interface RankingQuote {
  code: string
  name: string
  price: string
  change_pct: string
  change: string
  volume: number
  turnover: string
  market: string
}

// ---------- Money Flow ----------

export interface MoneyFlowItem {
  timestamp: string
  date?: string
  main_net: string
  super_net: string | null
  big_net: string | null
  medium_net: string | null
  small_net: string | null
  main_ratio: string | null
}

export interface MoneyFlowCumulative {
  main_net: string
  super_net: string
  big_net: string
  medium_net: string
  small_net: string
}

export interface MoneyFlowResponse {
  items: MoneyFlowItem[]
  cumulative: MoneyFlowCumulative
  days?: number
}

// ---------- Prediction Tracking ----------

export type PredictionStatus = 'pending' | 'hit' | 'missed' | 'expired' | 'unverifiable'

/** 单条 agent 预测记录（对应后端 predictions 表行，字段名与 DB 列一致）。 */
export interface Prediction {
  id: number
  created_at: string
  code: string
  name: string | null
  /** 预测文本，如「看涨」「看跌」。 */
  prediction: string
  /** 方向标识：up / down / neutral（由 LLM 抽取，可能为其他值）。 */
  direction: string
  rationale: string | null
  target_price: number | null
  entry_price: number | null
  /** 后端 DB 列名为 stop_loss（非 stop_price）。 */
  stop_loss: number | null
  change_pct_at_creation: number | null
  timeframe: string
  verify_after: string
  status: PredictionStatus
  verified_at: string | null
  actual_price: number | null
  actual_change_pct: number | null
  accuracy_score: number | null
  verify_attempts: number | null
  verify_log: string | null
  data_coverage_at_creation: string | null
  data_coverage_at_verify: string | null
  source_event_id: number | null
  insight_event_id: number | null
}

/** 预测统计（命中率分布）。hit_rate 为 0..1 的小数。 */
export interface PredictionStats {
  total: number
  pending: number
  hit: number
  missed: number
  expired: number
  unverifiable: number
  hit_rate: number
}
