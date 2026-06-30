// 持仓 API
import { apiGet, apiPost, apiDelete } from './client'
import type { PortfolioSummary, Position, Adjustment } from './types'

export function getPortfolio(): Promise<PortfolioSummary> {
  return apiGet('/api/portfolio')
}

export function listPositions(): Promise<Position[]> {
  return apiGet('/api/portfolio/positions')
}

export function addPosition(body: {
  code: string
  name?: string
  buy_price: string
  shares: number
  buy_date?: string
  note?: string
}): Promise<Position> {
  return apiPost('/api/portfolio/positions', body)
}

export function removePosition(id: number): Promise<void> {
  return apiDelete(`/api/portfolio/positions/${id}`)
}

export function listAdjustments(positionId: number): Promise<Adjustment[]> {
  return apiGet(`/api/portfolio/positions/${positionId}/adjustments`)
}

export function addAdjustment(positionId: number, body: {
  action: 'buy' | 'sell' | 'dividend'
  price: string
  shares: number
  note?: string
}): Promise<Adjustment> {
  return apiPost(`/api/portfolio/positions/${positionId}/adjustments`, body)
}
