/**
 * 浏览器半 SSE 订阅的失效/重连契约（fake EventSource + fake timers）：
 * - onopen = 桥就绪信号：触发全部订阅 handler 重拉，并清空 revision 去重基数
 *   （换桥后 revision 从 1 重新计数，旧基数会吞掉新桥头几条信号）；
 * - onerror 指数退避重连（1s→2s→…封顶 30s），超上限放弃（headless 错挂护栏）；
 * - 全部退订后取消 pending 重连。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

class FakeEventSource {
  static instances: FakeEventSource[] = []
  onopen: (() => void) | null = null
  onerror: (() => void) | null = null
  closed = false
  private readonly listeners = new Map<string, ((event: { data: string }) => void)[]>()

  constructor(public readonly url: string) {
    FakeEventSource.instances.push(this)
  }

  addEventListener(type: string, callback: (event: { data: string }) => void): void {
    const list = this.listeners.get(type) ?? []
    list.push(callback)
    this.listeners.set(type, list)
  }

  close(): void {
    this.closed = true
  }

  // —— 测试驱动钩子 ——
  simulateOpen(): void {
    this.onopen?.()
  }

  simulateError(): void {
    this.onerror?.()
  }

  emitChanged(store: string, revision: number): void {
    for (const callback of this.listeners.get('store.changed') ?? []) {
      callback({ data: JSON.stringify({ store, revision }) })
    }
  }
}

async function loadApi() {
  return await import('../src/client/api.ts')
}

describe('subscribeMommyEvents（SSE 就绪重拉与去重基数）', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    FakeEventSource.instances = []
    vi.stubGlobal('EventSource', FakeEventSource)
    vi.resetModules()
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('onopen 触发全部订阅 handler（桥就绪统一重拉）', async () => {
    const api = await loadApi()
    const fired: string[] = []
    api.subscribeMommyEvents({ portfolio: () => fired.push('portfolio') })
    expect(FakeEventSource.instances).toHaveLength(1)
    FakeEventSource.instances[0]!.simulateOpen()
    expect(fired).toEqual(['portfolio'])
  })

  it('onopen 清空 revision 基数：换桥后 revision 从 1 重计不被旧基数吞', async () => {
    const api = await loadApi()
    const fired: number[] = []
    const first = FakeEventSource.instances.length
    api.subscribeMommyEvents({ portfolio: () => fired.push(0) })
    const sse = FakeEventSource.instances[first]!
    sse.emitChanged('portfolio', 5)
    expect(fired).toHaveLength(1)
    sse.emitChanged('portfolio', 5) // 同连接内去重仍生效
    expect(fired).toHaveLength(1)
    sse.simulateOpen() // 重连成功（换桥）：基数作废
    expect(fired).toHaveLength(2)
    sse.emitChanged('portfolio', 1) // 新桥 revision 重新计数
    expect(fired).toHaveLength(3)
  })

  it('onerror 后按退避重建连接，成功后重置退避计数', async () => {
    const api = await loadApi()
    api.subscribeMommyEvents({ portfolio: () => {} })
    const first = FakeEventSource.instances[0]!
    first.simulateError()
    expect(first.closed).toBe(true)
    // 未到退避时窗（1s）不重建
    vi.advanceTimersByTime(999)
    expect(FakeEventSource.instances).toHaveLength(1)
    vi.advanceTimersByTime(1)
    expect(FakeEventSource.instances).toHaveLength(2)
    FakeEventSource.instances[1]!.simulateOpen()
    // 二次断连应从 1s 重新起步（成功已重置计数）
    FakeEventSource.instances[1]!.simulateError()
    vi.advanceTimersByTime(1_000)
    expect(FakeEventSource.instances).toHaveLength(3)
  })

  it('连续失败超过上限后放弃（headless 错挂护栏）', async () => {
    const api = await loadApi()
    const delays = [1_000, 2_000, 4_000, 8_000, 16_000, 30_000]
    api.subscribeMommyEvents({ portfolio: () => {} })
    for (const delay of delays) {
      const sse = FakeEventSource.instances.at(-1)
      sse?.simulateError()
      vi.advanceTimersByTime(delay)
    }
    const total = FakeEventSource.instances.length // 1 + 6 次重连
    const sse = FakeEventSource.instances.at(-1)
    sse?.simulateError()
    vi.advanceTimersByTime(60_000)
    expect(FakeEventSource.instances).toHaveLength(total)
  })

  it('全部退订后取消 pending 重连', async () => {
    const api = await loadApi()
    const unsubscribe = api.subscribeMommyEvents({ portfolio: () => {} })
    FakeEventSource.instances[0]!.simulateError()
    unsubscribe()
    vi.advanceTimersByTime(60_000)
    expect(FakeEventSource.instances).toHaveLength(1)
  })
})

describe('reconnectDelayMs（退避纯函数）', () => {
  it('指数增长且封顶 30s', async () => {
    const api = await loadApi()
    expect(api.reconnectDelayMs(0)).toBe(1_000)
    expect(api.reconnectDelayMs(1)).toBe(2_000)
    expect(api.reconnectDelayMs(4)).toBe(16_000)
    expect(api.reconnectDelayMs(5)).toBe(30_000)
    expect(api.reconnectDelayMs(50)).toBe(30_000)
  })
})

describe('fetchQuotes（错误载荷透传）', () => {
  beforeEach(() => {
    vi.resetModules()
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('CLI exit 0 + error 载荷时把 error 透传给调用方判定降级', async () => {
    const fetchMock = vi.fn(async () =>
      new Response(JSON.stringify({ source: '', quotes: [], error: 'eastmoney 重试耗尽' }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    )
    vi.stubGlobal('fetch', fetchMock)
    const api = await loadApi()
    const payload = await api.fetchQuotes(['600519'])
    expect(payload.error).toBe('eastmoney 重试耗尽')
    expect(payload.quotes).toEqual([])
  })

  it('成功载荷的 error 为 undefined（不误报降级）', async () => {
    const fetchMock = vi.fn(async () =>
      new Response(
        JSON.stringify({
          source: 'eastmoney(缓存)',
          quotes: [{ code: '600519', name: '贵州茅台', price: 1275.16, change_pct: 0.86, change: 10.9 }],
        }),
        { status: 200, headers: { 'content-type': 'application/json' } },
      ),
    )
    vi.stubGlobal('fetch', fetchMock)
    const api = await loadApi()
    const payload = await api.fetchQuotes(['600519'])
    expect(payload.error).toBeUndefined()
    expect(payload.quotes).toHaveLength(1)
    expect(payload.source).toBe('eastmoney(缓存)')
  })
})
