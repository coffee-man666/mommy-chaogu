/**
 * 工具结果载荷解析（纯函数）：mommy MCP 工具的 JSON 结果形状 → 卡片视图模型。
 *
 * 形状与 Python 侧 agent/tools/{quote,flows,bars,memory,holdings}.py 的
 * `_json(...)` 序列化一一对应（单一契约面）；解析失败一律返回 null——
 * 卡片渲染 null = 回落宿主通用工具行，不炸对话流。
 */

/** 工具调用块的最小面（宿主 ToolCallOwnerProps['block'] 的结构子集）。 */
export interface ToolCallBlock {
  kind?: string
  argsRaw?: string
  call?: { argsRaw?: string } | undefined
  content?: unknown[]
  isError?: boolean
}

/** 从 owner.block 读 (argsRaw, resultText)。 */
export function readCall(block: ToolCallBlock): {
  argsRaw: string
  resultText: string | null
  isError: boolean
} {
  if (block.kind === 'tool-result') {
    const text = (block.content ?? [])
      .map(part => (typeof part === 'object' && part !== null && 'text' in part ? String((part as { text?: unknown }).text ?? '') : ''))
      .join('')
    return { argsRaw: block.call?.argsRaw ?? '', resultText: text, isError: block.isError === true }
  }
  return { argsRaw: block.argsRaw ?? '', resultText: null, isError: false }
}

function parseJson(text: string): unknown {
  try {
    return JSON.parse(text) as unknown
  } catch {
    return null
  }
}

export interface QuoteView {
  code: string
  name: string
  price: number
  changePct: number | null
  change: number | null
  open: number | null
  high: number | null
  low: number | null
  prevClose: number | null
  volume: number | null
  turnover: number | null
  turnoverRate: number | null
  volumeRatio: number | null
  pe: number | null
  totalMarketCap: number | null
  circulatingMarketCap: number | null
  timestamp: string | null
}

const num = (value: unknown): number | null => {
  // mommy 工具有两种数值形态：JSON number（quote/bars）与字符串（analysis 域
  // 的 Decimal 序列化）——统一收有限数值，其余 null。
  if (typeof value === 'number') return Number.isFinite(value) ? value : null
  if (typeof value === 'string' && value.trim() !== '') {
    const parsed = Number(value)
    return Number.isFinite(parsed) ? parsed : null
  }
  return null
}
const str = (value: unknown): string | null => (typeof value === 'string' ? value : null)

function toQuoteView(raw: unknown): QuoteView | null {
  if (typeof raw !== 'object' || raw === null) return null
  const r = raw as Record<string, unknown>
  const price = num(r.price)
  if (price === null || typeof r.code !== 'string') return null
  return {
    code: r.code,
    name: typeof r.name === 'string' ? r.name : r.code,
    price,
    changePct: num(r.change_pct),
    change: num(r.change),
    open: num(r.open),
    high: num(r.high),
    low: num(r.low),
    prevClose: num(r.prev_close),
    volume: num(r.volume),
    turnover: num(r.turnover),
    turnoverRate: num(r.turnover_rate),
    volumeRatio: num(r.volume_ratio),
    pe: num(r.pe),
    totalMarketCap: num(r.total_market_cap),
    circulatingMarketCap: num(r.circulating_market_cap),
    timestamp: str(r.timestamp),
  }
}

/** 外部（如 /mommy/api 桥）拿到的原始报价字典 → 视图模型（字段缺失容错为 null）。 */
export function coerceQuote(raw: unknown): QuoteView | null {
  return toQuoteView(raw)
}

/** get_quote：单只报价或 {error}。 */
export function parseQuote(resultText: string): QuoteView | null {
  const data = parseJson(resultText)
  if (typeof data === 'object' && data !== null && 'error' in data) return null
  return toQuoteView(data)
}

/** get_quotes：报价数组。 */
export function parseQuotes(resultText: string): QuoteView[] {
  const data = parseJson(resultText)
  if (!Array.isArray(data)) return []
  return data.map(toQuoteView).filter((q): q is QuoteView => q !== null)
}

export interface IndexView {
  code: string
  name: string
  price: number
  changePct: number
}

/** get_market_indexes：大盘指数数组。 */
export function parseIndexes(resultText: string): IndexView[] {
  const data = parseJson(resultText)
  if (!Array.isArray(data)) return []
  const views: IndexView[] = []
  for (const item of data) {
    if (typeof item !== 'object' || item === null) continue
    const r = item as Record<string, unknown>
    const price = num(r.price)
    const changePct = num(r.change_pct)
    if (typeof r.code !== 'string' || price === null || changePct === null) continue
    views.push({ code: r.code, name: typeof r.name === 'string' ? r.name : r.code, price, changePct })
  }
  return views
}

export interface FlowView {
  code: string
  name: string
  timestamp: string | null
  mainNet: number
  superLargeNet: number | null
  largeNet: number | null
  mediumNet: number | null
  smallNet: number | null
  mainNetRatio: number | null
}

function toFlowView(raw: unknown): FlowView | null {
  if (typeof raw !== 'object' || raw === null) return null
  const r = raw as Record<string, unknown>
  const mainNet = num(r.main_net)
  if (typeof r.code !== 'string' || mainNet === null) return null
  return {
    code: r.code,
    name: typeof r.name === 'string' ? r.name : r.code,
    timestamp: str(r.timestamp),
    mainNet,
    superLargeNet: num(r.super_large_net),
    largeNet: num(r.large_net),
    mediumNet: num(r.medium_net),
    smallNet: num(r.small_net),
    mainNetRatio: num(r.main_net_ratio),
  }
}

/** get_money_flow_today：单只流对象或批量 {results: {code: 流}}。 */
export function parseFlows(resultText: string): FlowView[] {
  const data = parseJson(resultText)
  if (typeof data !== 'object' || data === null) return []
  const r = data as Record<string, unknown>
  if (Array.isArray(r.results) || typeof r.results === 'object') {
    const results = r.results
    if (typeof results === 'object' && results !== null && !Array.isArray(results)) {
      return Object.values(results)
        .map(toFlowView)
        .filter((f): f is FlowView => f !== null)
    }
  }
  const single = toFlowView(data)
  return single !== null ? [single] : []
}

export interface BarView {
  timestamp: string
  open: number
  high: number
  low: number
  close: number
  volume: number
  changePct: number | null
  /** include_ma 时服务端附加的均线值（键形如 "5"→ma_5；null=窗口未满）。 */
  ma: Record<string, number | null>
}

/** get_bars：K 线数组（新→旧或旧→新都收，展示前统一倒序成新在前）。 */
export function parseBars(resultText: string): { code: string; name: string; bars: BarView[] } | null {
  const data = parseJson(resultText)
  if (!Array.isArray(data) || data.length === 0) return null
  let code = ''
  let name = ''
  const bars: BarView[] = []
  for (const item of data) {
    if (typeof item !== 'object' || item === null) continue
    const r = item as Record<string, unknown>
    const close = num(r.close)
    const open = num(r.open)
    const timestamp = str(r.timestamp)
    if (close === null || open === null || timestamp === null) continue
    if (typeof r.code === 'string') code = r.code
    if (typeof r.name === 'string') name = r.name
    const ma: Record<string, number | null> = {}
    for (const [key, value] of Object.entries(r)) {
      if (key.startsWith('ma_')) ma[key.slice(3)] = num(value)
    }
    bars.push({
      timestamp,
      open,
      high: num(r.high) ?? close,
      low: num(r.low) ?? close,
      close,
      volume: num(r.volume) ?? 0,
      changePct: num(r.change_pct),
      ma,
    })
  }
  if (bars.length === 0) return null
  return { code, name, bars }
}

export interface PredictionView {
  id: string | null
  code: string | null
  name: string | null
  prediction: string | null
  direction: string | null
  status: string | null
  score: number | null
  createdAt: string | null
  verifiedAt: string | null
}

/** get_prediction_history：预测记录数组。 */
export function parsePredictions(resultText: string): PredictionView[] {
  const data = parseJson(resultText)
  if (!Array.isArray(data)) return []
  const views: PredictionView[] = []
  for (const item of data) {
    if (typeof item !== 'object' || item === null) continue
    const r = item as Record<string, unknown>
    views.push({
      id: str(r.id),
      code: str(r.code),
      name: str(r.name),
      prediction: str(r.prediction),
      direction: str(r.direction),
      status: str(r.status),
      score: num(r.score),
      createdAt: str(r.created_at),
      verifiedAt: str(r.verified_at),
    })
  }
  return views
}

/** manage_watchlist 写回执：args 读动作，result 判 ok / denied / error。 */
export type WatchlistOpState = 'ok' | 'denied' | 'error'

export interface WatchlistOpView {
  action: string
  code: string
  group: string | null
  state: WatchlistOpState
  message: string | null
}

export function parseWatchlistOp(argsRaw: string, resultText: string | null, isError: boolean): WatchlistOpView | null {
  const args = parseJson(argsRaw)
  if (typeof args !== 'object' || args === null) return null
  const a = args as Record<string, unknown>
  if (typeof a.code !== 'string') return null
  const action = typeof a.action === 'string' ? a.action : ''
  let state: WatchlistOpState = 'ok'
  let message: string | null = null
  if (resultText !== null) {
    const result = parseJson(resultText)
    if (typeof result === 'object' && result !== null && 'error' in result) {
      const error = (result as Record<string, unknown>).error
      const text = typeof error === 'string' ? error : String(error)
      // 拒绝时 mommy 的固定文案（agent/service.py DENIAL_RESULT_MESSAGE）；
      // 其余 error（含 isError 块）按失败渲染
      state = text.includes('用户拒绝') ? 'denied' : 'error'
      message = text
    } else if (isError) {
      state = 'error'
    }
  }
  return {
    action,
    code: a.code,
    group: typeof a.group === 'string' ? a.group : null,
    state,
    message,
  }
}

/** check_kline_signal：命中列表（数值字段为字符串形态，需强制转换）。 */
export interface KlineSignalHit {
  code: string
  name: string
  signal: string
  fast: number | null
  slow: number | null
  close: number | null
  volumeRatio: number | null
  changePct: number | null
}

export function parseKlineSignal(resultText: string): KlineSignalHit[] {
  const data = parseJson(resultText)
  if (typeof data !== 'object' || data === null) return []
  const results = (data as Record<string, unknown>).results
  if (!Array.isArray(results)) return []
  const hits: KlineSignalHit[] = []
  for (const item of results) {
    if (typeof item !== 'object' || item === null) continue
    const r = item as Record<string, unknown>
    if (typeof r.code !== 'string') continue
    hits.push({
      code: r.code,
      name: typeof r.name === 'string' ? r.name : r.code,
      signal: typeof r.signal === 'string' ? r.signal : '',
      fast: num(r.fast),
      slow: num(r.slow),
      close: num(r.close),
      volumeRatio: num(r.volume_ratio),
      changePct: num(r.change_pct),
    })
  }
  return hits
}

/** run_backtest：回放汇总（探索性评估，caveats 必须随卡展示）。 */
export interface BacktestView {
  totalSignals: number
  winningSignals: number
  losingSignals: number
  winRate: number
  avgReturnPct: number
  avgGrossReturnPct: number
  maxDrawdownPct: number
  sharpeRatio: number
  holdDays: number | null
  costModel: string
  caveats: string[]
  message: string
}

export function parseBacktest(resultText: string): BacktestView | null {
  const data = parseJson(resultText)
  if (typeof data !== 'object' || data === null) return null
  const r = data as Record<string, unknown>
  if (!('total_signals' in r)) return null
  return {
    totalSignals: num(r.total_signals) ?? 0,
    winningSignals: num(r.winning_signals) ?? 0,
    losingSignals: num(r.losing_signals) ?? 0,
    winRate: num(r.win_rate) ?? 0,
    avgReturnPct: num(r.avg_return_pct) ?? 0,
    avgGrossReturnPct: num(r.avg_gross_return_pct) ?? 0,
    maxDrawdownPct: num(r.max_drawdown_pct) ?? 0,
    sharpeRatio: num(r.sharpe_ratio) ?? 0,
    holdDays: num(r.hold_days),
    costModel: str(r.cost_model) ?? '',
    caveats: Array.isArray(r.caveats) ? r.caveats.filter((c): c is string => typeof c === 'string') : [],
    message: str(r.message) ?? '',
  }
}

/** get_money_flow_history：与当日资金流同形状的时序列表。 */
export function parseFlowHistory(resultText: string): FlowView[] {
  const data = parseJson(resultText)
  if (!Array.isArray(data)) return []
  return data.map(toFlowView).filter((f): f is FlowView => f !== null)
}

/** screen_inflow_stocks：主力净流入达标筛选（数值字段为字符串形态）。 */
export interface ScreenInflowRow {
  code: string
  name: string
  mainNet: number | null
  ratioBp: number | null
}

export function parseScreenInflow(resultText: string): { rows: ScreenInflowRow[]; total: number } {
  const data = parseJson(resultText)
  if (typeof data !== 'object' || data === null) return { rows: [], total: 0 }
  const r = data as Record<string, unknown>
  if (!Array.isArray(r.results)) return { rows: [], total: 0 }
  const rows: ScreenInflowRow[] = []
  for (const item of r.results) {
    if (typeof item !== 'object' || item === null) continue
    const row = item as Record<string, unknown>
    if (typeof row.code !== 'string') continue
    rows.push({
      code: row.code,
      name: typeof row.name === 'string' ? row.name : row.code,
      mainNet: num(row.main_net),
      ratioBp: num(row.ratio_bp),
    })
  }
  return { rows, total: num(r.total) ?? rows.length }
}

/** search_similar_events：语义/关键词检索的历史事件。 */
export interface SimilarEventView {
  id: string | null
  summary: string
  timestamp: string | null
  score: number | null
  scope: string | null
}

export function parseSimilarEvents(resultText: string): SimilarEventView[] {
  const data = parseJson(resultText)
  if (!Array.isArray(data)) return []
  const views: SimilarEventView[] = []
  for (const item of data) {
    if (typeof item !== 'object' || item === null) continue
    const r = item as Record<string, unknown>
    views.push({
      id: str(r.id),
      summary: str(r.summary) ?? '',
      timestamp: str(r.timestamp),
      score: num(r.score),
      scope: str(r.scope),
    })
  }
  return views.filter(v => v.summary !== '')
}

/** record_research_conclusion：写入回执三态。 */
export type RecordConclusionState = 'saved' | 'skipped' | 'confirmation_required'

export interface RecordConclusionView {
  state: RecordConclusionState
  message: string
}

export function parseRecordConclusion(resultText: string): RecordConclusionView | null {
  const data = parseJson(resultText)
  if (typeof data !== 'object' || data === null) return null
  const r = data as Record<string, unknown>
  if (!('saved' in r)) return null
  const state: RecordConclusionState = r.saved === true
    ? 'saved'
    : r.confirmation_required === true
      ? 'confirmation_required'
      : 'skipped'
  return { state, message: str(r.message) ?? '' }
}

/** 数值格式化：万/亿中文单位。 */
export function fmtAmountCN(value: number | null): string {  if (value === null) return '—'
  const abs = Math.abs(value)
  if (abs >= 1e12) return `${(value / 1e12).toFixed(2)}万亿`
  if (abs >= 1e8) return `${(value / 1e8).toFixed(2)}亿`
  if (abs >= 1e4) return `${(value / 1e4).toFixed(2)}万`
  return value.toFixed(0)
}

export function fmtPct(value: number | null): string {
  if (value === null) return '—'
  const sign = value > 0 ? '+' : ''
  return `${sign}${value.toFixed(2)}%`
}

/** A 股语义色：涨红跌绿（web 项目同款语义，DSH 侧以 CSS 变量收口）。 */
export function trendOf(value: number | null): 'up' | 'down' | 'flat' {
  if (value === null || value === 0) return 'flat'
  return value > 0 ? 'up' : 'down'
}
