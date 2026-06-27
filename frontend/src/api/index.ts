// 行情 API
import { apiGet } from './client'
import type { Quote, Snapshot, Bar, OrderBook } from './types'

export function getSnapshot(): Promise<Snapshot> {
  return apiGet('/api/quotes')
}

export function getQuote(code: string): Promise<Quote> {
  return apiGet(`/api/quotes/${code}`)
}

export function getBars(
  code: string,
  interval = '1d',
  limit = 120,
  adjustment = 'forward'
): Promise<Bar[]> {
  return apiGet(`/api/quotes/${code}/bars?interval=${interval}&limit=${limit}&adjustment=${adjustment}`)
}

export function getOrderBook(code: string): Promise<OrderBook> {
  return apiGet(`/api/quotes/${code}/orderbook`)
}

export function getTodayMoneyFlow(code: string): Promise<any[]> {
  return apiGet(`/api/quotes/${code}/money_flow/today`)
}

// 格式化辅助
export function fmtMoney(s: string | null | undefined, unit: 'yuan' | 'wan' | 'yi' = 'yuan'): string {
  if (!s) return '-'
  const n = Number(s)
  if (isNaN(n)) return s
  if (unit === 'yi') return `${(n / 1e8).toFixed(2)}亿`
  if (unit === 'wan') return `${(n / 1e4).toFixed(2)}万`
  return n.toFixed(2)
}

export function fmtPrice(s: string): string {
  const n = Number(s)
  if (isNaN(n)) return s
  return n.toFixed(2)
}

export function fmtPct(s: string): string {
  const n = Number(s)
  if (isNaN(n)) return s
  return `${n >= 0 ? '+' : ''}${n.toFixed(2)}%`
}

export function fmtAge(seconds: number): string {
  if (seconds < 60) return `${seconds}秒前`
  if (seconds < 3600) return `${Math.floor(seconds / 60)}分钟前`
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}小时前`
  return `${Math.floor(seconds / 86400)}天前`
}

export function changeColor(changePct: string): string {
  const n = Number(changePct)
  if (isNaN(n)) return '#666'
  if (n > 0) return '#c83e3e'  // A 股红涨
  if (n < 0) return '#2d8e3d'  // 绿跌
  return '#666'
}
