// Agent API client
import { apiPost, authenticatedWsUrl, getChatSessionId } from './client'

export interface ChatResponse {
  reply: string
  tools_used: string[]
  rounds: number
}

export interface RouteStep {
  name: string
  tool: string
  success: boolean
}

export interface RouteResponse {
  matched: boolean
  workflow_id?: string
  reply?: string
  steps?: RouteStep[]
}

export type AgentStreamState = 'connecting' | 'connected' | 'disconnected'

export async function agentChat(
  message: string,
  history?: Array<{ role: string; content: string }>,
): Promise<ChatResponse> {
  return apiPost<ChatResponse>('/api/agent/chat', {
    message,
    history,
    session_id: getChatSessionId(),
  })
}

export async function agentRoute(
  message: string,
  signal?: AbortSignal,
): Promise<RouteResponse> {
  return apiPost<RouteResponse>('/api/agent/route', { message }, signal)
}

// WebSocket 流式对话
export function agentStream(
  onChunk: (text: string) => void,
  onDone: (toolsUsed: string[], rounds: number) => void,
  onThinking: () => void,
  onError: (msg: string) => void,
  onStateChange: (state: AgentStreamState) => void = () => {},
): {
  send: (message: string, history?: Array<{ role: string; content: string }>) => void
  close: () => void
} {
  // 连接建立前的待发消息缓冲
  let pendingMessage: {
    message: string
    history?: Array<{ role: string; content: string }>
    session_id: string
  } | null = null
  // 初始连接失败时，最多重试一次
  let retried = false
  let closedByClient = false
  let retryTimer: number | null = null
  let ws: WebSocket | null = null

  function reconnectOrFail(message: string) {
    if (closedByClient) return
    if (retryTimer != null) return
    if (!retried) {
      retried = true
      onStateChange('connecting')
      retryTimer = window.setTimeout(() => {
        retryTimer = null
        if (!closedByClient) void openSocket()
      }, 2000)
      return
    }
    onStateChange('disconnected')
    onError(message)
  }

  async function openSocket() {
    onStateChange('connecting')
    try {
      const url = await authenticatedWsUrl('/ws/agent')
      if (closedByClient) return
      ws = new WebSocket(url)
      attachHandlers(ws)
    } catch (error) {
      reconnectOrFail(error instanceof Error ? error.message : 'WebSocket 认证失败')
    }
  }

  function attachHandlers(socket: WebSocket) {
    socket.onopen = () => {
      if (closedByClient) {
        socket.close()
        return
      }
      onStateChange('connected')
      if (pendingMessage) {
        socket.send(JSON.stringify(pendingMessage))
        pendingMessage = null
      }
    }

    socket.onmessage = (event) => {
      if (closedByClient) return
      try {
        const msg = JSON.parse(event.data)
        if (msg.type === 'chunk') {
          onChunk(msg.text)
        } else if (msg.type === 'done') {
          onDone(msg.tools_used || [], msg.rounds || 0)
        } else if (msg.type === 'thinking') {
          onThinking()
        } else if (msg.type === 'error') {
          onStateChange('disconnected')
          onError(msg.message || '未知错误')
        }
      } catch {
        // ignore parse errors
      }
    }

    socket.onerror = () => {
      // Browsers provide no useful detail here; onclose owns retry/failure UI.
    }
    socket.onclose = () => {
      reconnectOrFail('WebSocket 连接失败，请检查服务是否正常运行')
    }
  }

  void openSocket()

  return {
    send(message: string, history?: Array<{ role: string; content: string }>) {
      if (closedByClient) {
        onError('WebSocket 连接已关闭，请重新发送消息')
        return
      }
      if (ws?.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ message, history, session_id: getChatSessionId() }))
      } else if (ws == null || ws.readyState === WebSocket.CONNECTING) {
        // 连接还没建立，缓冲等 onopen
        pendingMessage = { message, history, session_id: getChatSessionId() }
      } else {
        // CLOSING / CLOSED
        onStateChange('disconnected')
        onError('WebSocket 连接已关闭，请刷新页面重试')
      }
    },
    close() {
      closedByClient = true
      pendingMessage = null
      if (retryTimer != null) {
        window.clearTimeout(retryTimer)
        retryTimer = null
      }
      if (ws) {
        ws.onopen = null
        ws.onmessage = null
        ws.onerror = null
        ws.close()
      }
    },
  }
}
