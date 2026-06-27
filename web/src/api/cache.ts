// 缓存 API
import { apiGet } from './client'
import type { CacheStats, Health } from './types'

export function cacheStats(): Promise<CacheStats> {
  return apiGet('/api/cache/stats')
}

export function health(): Promise<Health> {
  return apiGet('/api/health')
}
