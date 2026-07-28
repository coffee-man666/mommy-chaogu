import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { ApiError, authRequired } from '../api/client'
import { usePortfolioStore } from './portfolio'

const summaryFixture = {
  total_market_value: '1000',
  total_cost: '900',
  total_unrealized_pnl: '100',
  total_unrealized_pnl_pct: '11.11',
  n_positions: 1,
  positions: [
    {
      id: 1,
      code: '600519',
      name: '贵州茅台',
      shares: 100,
      avg_cost: '9',
      current_price: '10',
      market_value: '1000',
      unrealized_pnl: '100',
      unrealized_pnl_pct: '11.11',
    },
  ],
}

function mockSummaryOnce() {
  vi.mocked(fetch).mockResolvedValueOnce(
    new Response(JSON.stringify(summaryFixture), { status: 200 }),
  )
}

describe('portfolio store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    sessionStorage.clear()
    authRequired.value = false
    vi.stubGlobal('fetch', vi.fn())
  })

  it('populates summary + positions on success and clears error', async () => {
    const store = usePortfolioStore()
    mockSummaryOnce()
    await store.fetchSummary()
    expect(store.error).toBeNull()
    expect(store.summary?.n_positions).toBe(1)
    expect(store.positions).toHaveLength(1)
  })

  it('keeps old data on failure and records ApiError（不再清空假装"没有持仓"）', async () => {
    const store = usePortfolioStore()
    mockSummaryOnce()
    await store.fetchSummary()

    vi.mocked(fetch).mockResolvedValueOnce(new Response('boom', { status: 500 }))
    await store.fetchSummary()

    expect(store.error).toBeInstanceOf(ApiError)
    expect(store.error?.status).toBe(500)
    expect(store.error?.friendly).toBe('服务暂时不可用')
    // 旧数据还在
    expect(store.summary?.n_positions).toBe(1)
    expect(store.positions).toHaveLength(1)
  })

  it('keeps old data on network failure and clears error after recovery', async () => {
    const store = usePortfolioStore()
    mockSummaryOnce()
    await store.fetchSummary()

    vi.mocked(fetch).mockRejectedValueOnce(new TypeError('Failed to fetch'))
    await store.fetchSummary()
    expect(store.error?.friendly).toBe('网络连接失败')
    expect(store.positions).toHaveLength(1)

    mockSummaryOnce()
    await store.fetchSummary()
    expect(store.error).toBeNull()
  })
})
