import { createApp, nextTick } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/api/market', () => ({
  searchStocks: vi.fn(),
}))

import { searchStocks } from '@/api/market'
import StockSearch from './StockSearch.vue'

const result = { code: '600519', name: '贵州茅台', source: 'watchlist' as const }

describe('StockSearch', () => {
  afterEach(() => {
    vi.useRealTimers()
    document.body.innerHTML = ''
  })

  it('debounces name searches and supports keyboard selection', async () => {
    vi.useFakeTimers()
    vi.mocked(searchStocks).mockResolvedValue([result])
    const onSelect = vi.fn()
    const host = document.createElement('div')
    document.body.append(host)
    const app = createApp(StockSearch, { onSelect })
    app.mount(host)

    const input = host.querySelector('input') as HTMLInputElement
    input.value = '茅台'
    input.dispatchEvent(new Event('input', { bubbles: true }))
    await vi.advanceTimersByTimeAsync(180)
    await nextTick()

    expect(searchStocks).toHaveBeenCalledWith('茅台')
    expect(host.querySelector('[role="option"]')?.textContent).toContain('贵州茅台')

    input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))
    await nextTick()
    expect(onSelect).toHaveBeenCalledWith(result)
    app.unmount()
  })
})
