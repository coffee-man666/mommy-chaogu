import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('./client', () => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
}))

import { apiGet, apiPost } from './client'
import {
  getBasket,
  getBaskets,
  updateBasketMemberWeight,
  updateBasketPreference,
} from './baskets'

describe('basket API', () => {
  beforeEach(() => vi.clearAllMocks())

  it('loads the server-owned unified catalog', async () => {
    vi.mocked(apiGet).mockResolvedValueOnce([])
    await getBaskets()
    expect(apiGet).toHaveBeenCalledWith('/api/baskets')
  })

  it('encodes canonical basket ids in detail and preference paths', async () => {
    vi.mocked(apiGet).mockResolvedValueOnce({})
    vi.mocked(apiPost).mockResolvedValueOnce({})

    await getBasket('theme:chips')
    await updateBasketPreference('theme:chips', { followed: false, reason: '等待' })

    expect(apiGet).toHaveBeenCalledWith('/api/baskets/theme%3Achips')
    expect(apiPost).toHaveBeenCalledWith('/api/baskets/theme%3Achips/preference', {
      followed: false,
      reason: '等待',
    })
  })

  it('updates an optional member weight without float conversion', async () => {
    vi.mocked(apiPost).mockResolvedValueOnce({})
    await updateBasketMemberWeight('group:2', '600519', '12.50')
    expect(apiPost).toHaveBeenCalledWith('/api/baskets/group%3A2/members/600519/weight', {
      weight: '12.50',
    })
  })
})
