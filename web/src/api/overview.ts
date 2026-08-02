// Overview 聚合 API — 今日一屏总览
// 一次请求返回 5 个区块，各自独立标记 ok/stale/unavailable

import { apiGet } from './client'

export type BlockStatusType = 'ok' | 'stale' | 'unavailable'

export interface BlockStatus {
  status: BlockStatusType
  as_of: string | null
  message: string | null
}

export interface OverviewIndex {
  name: string
  price: string
  change_pct: string
}

export interface OverviewIndexesBlock {
  indexes: OverviewIndex[]
  block: BlockStatus
}

export interface OverviewWatchlistItem {
  code: string
  name: string
  price: string
  change_pct: string
  group: string
  data_age_seconds: number
}

export interface OverviewWatchlistBlock {
  total: number
  n_up: number
  n_down: number
  n_flat: number
  items: OverviewWatchlistItem[]
  block: BlockStatus
}

export interface OverviewPortfolioAlert {
  code: string
  name: string | null
  unrealized_pnl_pct: string | null
  market_value: string | null
  shares: number
}

export interface OverviewPortfolioBlock {
  n_positions: number
  total_unrealized_pnl: string | null
  total_unrealized_pnl_pct: string | null
  alerts: OverviewPortfolioAlert[]
  block: BlockStatus
}

export interface OverviewThemeSummary {
  id: string
  source_id: string
  kind: 'theme' | 'custom'
  name: string
  description: string
  total_stocks: number
  reason: string
  priority_reason: string | null
  change_pct: string | null
  leader: { code: string; name: string; change_pct: string } | null
  laggard: { code: string; name: string; change_pct: string } | null
  anomaly: string | null
  as_of: string | null
  status: BlockStatusType
  message: string | null
}

export interface OverviewThemesBlock {
  items: OverviewThemeSummary[]
  ordering_note: string | null
  block: BlockStatus
}

export interface OverviewSignalSummary {
  n_recent: number
  n_warning: number
  n_critical: number
  latest_title: string | null
  latest_severity: 'info' | 'warning' | 'critical' | null
}

export interface OverviewSignalsBlock {
  summary: OverviewSignalSummary | null
  block: BlockStatus
}

export interface OverviewResponse {
  indexes: OverviewIndexesBlock
  watchlist: OverviewWatchlistBlock
  portfolio: OverviewPortfolioBlock
  themes: OverviewThemesBlock
  signals: OverviewSignalsBlock
}

export function getOverview(): Promise<OverviewResponse> {
  return apiGet<OverviewResponse>('/api/overview')
}
