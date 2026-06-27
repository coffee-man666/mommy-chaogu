// 信号 API
import { apiGet } from './client'
import type { Signal } from './types'

export function recentSignals(): Promise<Signal[]> {
  return apiGet('/api/signals/recent')
}

export function signalHistory(limit = 50, ruleId?: string): Promise<Signal[]> {
  const params = new URLSearchParams({ limit: String(limit) })
  if (ruleId) params.set('rule_id', ruleId)
  return apiGet(`/api/signals/history?${params}`)
}
