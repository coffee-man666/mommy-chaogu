import { beforeEach, describe, expect, it, vi } from 'vitest'

import { getStockBacktest } from './backtest'

describe('backtest API client', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
  })

  it('fetches backtest without hold_days when not provided', async () => {
    const mockResult = {
      code: '600519',
      hold_days: 5,
      start_date: '2025-08-02',
      end_date: '2026-08-01',
      total_signals: 12,
      win_rate: 0.583,
      avg_return_pct: 1.24,
      max_drawdown_pct: -3.5,
      sharpe_ratio: 0.42,
      message: null,
    }
    vi.mocked(fetch).mockResolvedValueOnce(
      new Response(JSON.stringify(mockResult), { status: 200 }),
    )

    const result = await getStockBacktest('600519')
    expect(result).toEqual(mockResult)
    expect(fetch).toHaveBeenCalledWith(
      '/api/stocks/600519/backtest',
      expect.objectContaining({ headers: expect.any(Object) }),
    )
  })

  it('appends hold_days when provided', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      new Response(JSON.stringify({ code: '600519', hold_days: 10 }), { status: 200 }),
    )

    await getStockBacktest('600519', 10)
    expect(fetch).toHaveBeenCalledWith(
      '/api/stocks/600519/backtest?hold_days=10',
      expect.any(Object),
    )
  })

  it('surfaces non-200 responses as errors', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(new Response('boom', { status: 500 }))
    await expect(getStockBacktest('600519')).rejects.toMatchObject({
      status: 500,
      friendly: '服务暂时不可用',
    })
  })
})
