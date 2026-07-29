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

  it('forwards done.text so non-streaming fallbacks are visible', async () => {
    const onDone = vi.fn()
    const client = agentStream(vi.fn(), onDone, vi.fn(), vi.fn())
    client.send('你好')
    await vi.runAllTicks()

    const socket = MockWebSocket.instances[0]
    socket.readyState = MockWebSocket.OPEN
    socket.onopen?.()
    socket.onmessage?.({
      data: JSON.stringify({
        type: 'done',
        text: 'AI 助手未配置。',
        tools_used: [],
        rounds: 0,
      }),
    })

    expect(onDone).toHaveBeenCalledWith('AI 助手未配置。', [], 0)
    client.close()
  })

  it('forwards live tool call lifecycle events', async () => {
    const onToolCall = vi.fn()
    const onToolResult = vi.fn()
    const client = agentStream(
      vi.fn(),
      vi.fn(),
      vi.fn(),
      vi.fn(),
      vi.fn(),
      onToolCall,
      onToolResult,
    )
    client.send('分析 600519')
    await vi.runAllTicks()

    const socket = MockWebSocket.instances[0]
    socket.readyState = MockWebSocket.OPEN
    socket.onopen?.()
    socket.onmessage?.({
      data: JSON.stringify({
        type: 'tool_call_started',
        tool: 'get_quote',
        args: { code: '600519' },
      }),
    })
    socket.onmessage?.({
      data: JSON.stringify({
        type: 'tool_call_finished',
        tool: 'get_quote',
        status: 'done',
        elapsed_ms: 1200,
        result: '{"price":1689.5}',
      }),
    })

    expect(onToolCall).toHaveBeenCalledWith({
      tool: 'get_quote',
      args: { code: '600519' },
    })
    expect(onToolResult).toHaveBeenCalledWith({
      tool: 'get_quote',
      status: 'done',
      elapsedMs: 1200,
      result: '{"price":1689.5}',
    })
    client.close()
  })

  it('fails an interrupted turn immediately without reconnecting', async () => {
    const onError = vi.fn()
    const onStateChange = vi.fn()
    const client = agentStream(vi.fn(), vi.fn(), vi.fn(), onError, onStateChange)
    client.send('分析 600519')
    await vi.runAllTicks()

    const socket = MockWebSocket.instances[0]
    socket.readyState = MockWebSocket.OPEN
    socket.onopen?.()
    socket.onclose?.()

    expect(onStateChange).toHaveBeenLastCalledWith('disconnected')
    expect(onError).toHaveBeenCalledWith('连接中断，请重试')
    await vi.advanceTimersByTimeAsync(2000)
    expect(MockWebSocket.instances).toHaveLength(1)
    client.close()
  })
})
