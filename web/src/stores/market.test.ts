import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { ApiError, authRequired } from '../api/client'
import { useMarketStore } from './market'

const indexesFixture = [
  { code: 'sh000001', name: '上证指数', price: '3000', change_pct: '1.2' },
]

describe('market store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    sessionStorage.clear()
    authRequired.value = false
    vi.stubGlobal('fetch', vi.fn())
  })

  it('keeps old indexes on failure and records ApiError', async () => {
    const store = useMarketStore()
    vi.mocked(fetch).mockResolvedValueOnce(
      new Response(JSON.stringify(indexesFixture), { status: 200 }),
    )
    await store.fetchIndexes()
    expect(store.error).toBeNull()
    expect(store.indexes).toHaveLength(1)

    vi.mocked(fetch).mockResolvedValueOnce(new Response('boom', { status: 503 }))
    await store.fetchIndexes()
    expect(store.error).toBeInstanceOf(ApiError)
    expect(store.error?.friendly).toBe('服务暂时不可用')
    expect(store.indexes).toHaveLength(1)

    vi.mocked(fetch).mockResolvedValueOnce(
      new Response(JSON.stringify(indexesFixture), { status: 200 }),
    )
    await store.fetchIndexes()
    expect(store.error).toBeNull()
  })

  it('keeps old sectors on network failure', async () => {
    const store = useMarketStore()
    vi.mocked(fetch).mockResolvedValueOnce(
      new Response(JSON.stringify([{ code: 'bk1', name: '半导体' }]), { status: 200 }),
    )
    await store.fetchSectors()
    expect(store.sectors).toHaveLength(1)

    vi.mocked(fetch).mockRejectedValueOnce(new TypeError('Failed to fetch'))
    await store.fetchSectors()
    expect(store.error?.friendly).toBe('网络连接失败')
    expect(store.sectors).toHaveLength(1)
  })
})
