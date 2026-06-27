// 自选股 API
import { apiGet, apiPost, apiDelete } from './client'
import type { WatchlistStock, WatchlistGroup } from './types'

export function listWatchlist(): Promise<WatchlistStock[]> {
  return apiGet('/api/watchlist')
}

export function listGroups(): Promise<WatchlistGroup[]> {
  return apiGet('/api/watchlist/groups')
}

export function addGroup(name: string, description = ''): Promise<WatchlistGroup> {
  return apiPost('/api/watchlist/groups', { name, description })
}

export function removeGroup(name: string): Promise<void> {
  return apiDelete(`/api/watchlist/groups/${encodeURIComponent(name)}`)
}

export function addStock(code: string, group: string, note = ''): Promise<WatchlistStock> {
  return apiPost('/api/watchlist/stocks', { code, group, note })
}

export function removeStock(code: string, group: string): Promise<void> {
  return apiDelete(`/api/watchlist/stocks/${code}?group=${encodeURIComponent(group)}`)
}
