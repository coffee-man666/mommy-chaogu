import { beforeEach, describe, expect, it, vi } from 'vitest'

import { getPredictionStats, getPredictions } from './predictions'

describe('predictions API client', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
  })

  it('fetches predictions and unwraps the predictions array', async () => {
    const mockPredictions = [
      {
        id: 1,
        created_at: '2026-07-20T00:00:00Z',
        code: '600519',
        name: '贵州茅台',
        prediction: '看涨',
        direction: 'up',
        rationale: '资金面转好',
        target_price: 1800,
        entry_price: 1680,
        stop_loss: 1620,
        change_pct_at_creation: 1.2,
        timeframe: '5d',
        verify_after: '2026-07-25T00:00:00Z',
        status: 'pending',
        verified_at: null,
        actual_price: null,
        actual_change_pct: null,
        accuracy_score: null,
        verify_attempts: 0,
        verify_log: null,
        data_coverage_at_creation: null,
        data_coverage_at_verify: null,
        source_event_id: null,
        insight_event_id: null,
      },
    ]
    vi.mocked(fetch).mockResolvedValueOnce(
      new Response(JSON.stringify({ predictions: mockPredictions, total: 1 }), {
        status: 200,
      }),
    )

    const result = await getPredictions(20)
    expect(result).toEqual(mockPredictions)
    expect(fetch).toHaveBeenCalledWith(
      '/api/agent/predictions?limit=20',
      expect.objectContaining({ headers: expect.any(Object) }),
    )
  })

  it('respects a custom limit parameter', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      new Response(JSON.stringify({ predictions: [], total: 0 }), { status: 200 }),
    )
    await getPredictions(50)
    expect(fetch).toHaveBeenCalledWith(
      '/api/agent/predictions?limit=50',
      expect.any(Object),
    )
  })

  it('fetches prediction stats', async () => {
    const mockStats = {
      total: 10,
      pending: 4,
      hit: 4,
      missed: 1,
      expired: 1,
      unverifiable: 0,
      hit_rate: 0.8,
    }
    vi.mocked(fetch).mockResolvedValueOnce(
      new Response(JSON.stringify(mockStats), { status: 200 }),
    )

    const result = await getPredictionStats()
    expect(result).toEqual(mockStats)
    expect(result.hit_rate).toBe(0.8)
    expect(fetch).toHaveBeenCalledWith(
      '/api/agent/predictions/stats',
      expect.any(Object),
    )
  })

  it('surfaces non-200 responses as errors', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(new Response('boom', { status: 500 }))
    await expect(getPredictions()).rejects.toThrow('500: boom')
  })
})
