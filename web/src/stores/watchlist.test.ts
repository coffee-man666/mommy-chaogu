import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { ApiError, authRequired } from '../api/client'
import { useWatchlistStore } from './watchlist'

const entriesFixture = [{ code: '600519', name: '贵州茅台', group: '默认' }]
const groupsFixture = [{ name: '默认', description: '', n_stocks: 1 }]

function mockOkOnce(payload: unknown) {
  vi.mocked(fetch).mockResolvedValueOnce(
    new Response(JSON.stringify(payload), { status: 200 }),
  )
}

describe('watchlist store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    sessionStorage.clear()
    authRequired.value = false
    vi.stubGlobal('fetch', vi.fn())
  })

  it('populates entries + groups on success and clears error', async () => {
    const store = useWatchlistStore()
    mockOkOnce(entriesFixture)
    mockOkOnce(groupsFixture)
    await store.fetchAll()
    expect(store.error).toBeNull()
    expect(store.entries).toHaveLength(1)
    expect(store.groups).toHaveLength(1)
  })

  it('keeps old data when a refresh fails（不再清空成"没有自选股"）', async () => {
    const store = useWatchlistStore()
    mockOkOnce(entriesFixture)
    mockOkOnce(groupsFixture)
    await store.fetchAll()

    // entries 失败 + groups 成功：entries 保留旧数据，error 记录失败原因
    vi.mocked(fetch).mockRejectedValueOnce(new TypeError('Failed to fetch'))
    mockOkOnce(groupsFixture)
    await store.fetchAll()

    expect(store.error).toBeInstanceOf(ApiError)
    expect(store.error?.friendly).toBe('网络连接失败')
    expect(store.entries).toHaveLength(1)
    expect(store.groups).toHaveLength(1)
  })

  it('clears error after a successful refresh', async () => {
    const store = useWatchlistStore()
    vi.mocked(fetch).mockRejectedValueOnce(new TypeError('Failed to fetch'))
    vi.mocked(fetch).mockRejectedValueOnce(new TypeError('Failed to fetch'))
    await store.fetchAll()
    expect(store.error).toBeInstanceOf(ApiError)

    mockOkOnce(entriesFixture)
    mockOkOnce(groupsFixture)
    await store.fetchAll()
    expect(store.error).toBeNull()
  })
})
