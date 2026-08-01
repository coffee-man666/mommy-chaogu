import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('./client', () => ({ apiGet: vi.fn() }))

import { apiGet } from './client'
import { getStockDecisionContext } from './market'

describe('stock decision context api', () => {
  beforeEach(() => vi.mocked(apiGet).mockReset())

  it('loads the server-owned context for one stock', async () => {
    vi.mocked(apiGet).mockResolvedValue({ code: '600519', holding: null, baskets: [] })

    await getStockDecisionContext('600519')

    expect(apiGet).toHaveBeenCalledWith('/api/stocks/600519/decision-context')
  })
})
