import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('./client', () => ({
  authenticatedWsUrl: () => Promise.resolve('ws://localhost/ws/agent'),
  getChatSessionId: () => 'web-test-session',
  apiPost: vi.fn(),
}))

import { agentStream } from './agent'

class MockWebSocket {
  static CONNECTING = 0
  static OPEN = 1
  static CLOSED = 3
  static instances: MockWebSocket[] = []

  readyState = MockWebSocket.CONNECTING
  onopen: (() => void) | null = null
  onmessage: ((event: { data: string }) => void) | null = null
  onclose: (() => void) | null = null
  onerror: (() => void) | null = null
  send = vi.fn()
  close = vi.fn()

  constructor(public url: string) {
    MockWebSocket.instances.push(this)
  }
}

describe('agent websocket lifecycle', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    MockWebSocket.instances = []
    vi.stubGlobal('WebSocket', MockWebSocket)
  })

  it('buffers a message and reports the real connection state', async () => {
    const onError = vi.fn()
    const onStateChange = vi.fn()
    const client = agentStream(vi.fn(), vi.fn(), vi.fn(), onError, onStateChange)

    client.send('分析 600519')
    await vi.runAllTicks()

    const socket = MockWebSocket.instances[0]
    socket.readyState = MockWebSocket.OPEN
    socket.onopen?.()

    expect(onStateChange.mock.calls.map(([state]) => state)).toEqual([
      'connecting',
      'connected',
    ])
    expect(JSON.parse(socket.send.mock.calls[0][0])).toMatchObject({
      message: '分析 600519',
      session_id: 'web-test-session',
    })
    expect(onError).not.toHaveBeenCalled()
    client.close()
  })

  it('retries once before showing a useful disconnected state', async () => {
    const onError = vi.fn()
    const onStateChange = vi.fn()
    const client = agentStream(vi.fn(), vi.fn(), vi.fn(), onError, onStateChange)
    await vi.runAllTicks()

    MockWebSocket.instances[0].onclose?.()
    await vi.advanceTimersByTimeAsync(2000)
    expect(MockWebSocket.instances).toHaveLength(2)

    MockWebSocket.instances[1].onclose?.()
    expect(onStateChange).toHaveBeenLastCalledWith('disconnected')
    expect(onError).toHaveBeenCalledWith(
      'WebSocket 连接失败，请检查服务是否正常运行',
    )
    client.close()
  })
})
