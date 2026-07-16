import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('./client', () => ({
  authenticatedWsUrl: () => Promise.resolve('ws://localhost/ws/quotes'),
}))

import { QuotesWS } from './ws'

class MockWebSocket {
  static OPEN = 1
  static instances: MockWebSocket[] = []
  readyState = 0
  onopen: (() => void) | null = null
  onmessage: ((event: { data: string }) => void) | null = null
  onclose: (() => void) | null = null
  onerror: ((event: unknown) => void) | null = null
  send = vi.fn()
  close = vi.fn()

  constructor(public url: string) {
    MockWebSocket.instances.push(this)
  }
}

describe('quote websocket reconnect behavior', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    MockWebSocket.instances = []
    vi.stubGlobal('WebSocket', MockWebSocket)
  })

  it('delivers snapshots and reconnects once after close', async () => {
    const handler = vi.fn()
    const client = new QuotesWS()
    client.connect(handler)
    await vi.runAllTicks()
    const first = MockWebSocket.instances[0]
    first.onmessage?.({ data: JSON.stringify({ type: 'quote_update', snapshot: { quotes: [] } }) })
    expect(handler).toHaveBeenCalledWith({ quotes: [] })
    first.onclose?.()
    first.onclose?.()
    await vi.advanceTimersByTimeAsync(3000)
    expect(MockWebSocket.instances).toHaveLength(2)
    client.disconnect()
  })
})
