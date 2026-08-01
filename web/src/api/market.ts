// 市场排行 API
import { apiGet } from './client'
import type {
  IndexQuote,
  SectorQuote,
  RankingQuote,
  StockDecisionContext,
  StockSearchResult,
} from './types'

export function getIndexes(): Promise<IndexQuote[]> {
  return apiGet('/api/market/indexes')
}

export function getSectors(limit = 30): Promise<SectorQuote[]> {
  return apiGet(`/api/market/sectors?limit=${limit}`)
}

export function getGainers(limit = 20): Promise<RankingQuote[]> {
  return apiGet(`/api/market/gainers?limit=${limit}`)
}

export function getLosers(limit = 20): Promise<RankingQuote[]> {
  return apiGet(`/api/market/losers?limit=${limit}`)
}

export function searchStocks(query: string, limit = 10): Promise<StockSearchResult[]> {
  const params = new URLSearchParams({ q: query, limit: String(limit) })
  return apiGet(`/api/stocks/search?${params}`)
}

export function getStockDecisionContext(code: string): Promise<StockDecisionContext> {
  return apiGet(`/api/stocks/${encodeURIComponent(code)}/decision-context`)
}
