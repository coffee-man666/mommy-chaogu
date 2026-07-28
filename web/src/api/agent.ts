// Agent API client
import { apiGet, apiPost, authenticatedWsUrl, getChatSessionId } from './client'
import type { AgentHistoryMessage } from './types'

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

/** 工具调用事件（后端 ws.py 推送） */
export interface ToolCallEvent {
  tool: string
  args?: Record<string, unknown>
}
export interface ToolResultEvent {
  tool: string
  status: 'done' | 'fail'
  elapsedMs: number
  result?: string
}

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

export function getAgentHistory(limit = 50): Promise<AgentHistoryMessage[]> {
  const sessionId = encodeURIComponent(getChatSessionId())
  return apiGet<{ messages: AgentHistoryMessage[]; total: number }>(
    `/api/agent/history?session_id=${sessionId}&limit=${limit}`,
  ).then((response) => response.messages)
}

// WebSocket 流式对话
export function agentStream(
  onChunk: (text: string) => void,
  onDone: (text: string, toolsUsed: string[], rounds: number) => void,
  onThinking: () => void,
  onError: (msg: string) => void,
  onStateChange: (state: AgentStreamState) => void = () => {},
  onToolCall: (e: ToolCallEvent) => void = () => {},
  onToolResult: (e: ToolResultEvent) => void = () => {},
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
  let hasConnected = false
  let turnInFlight = false

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
      hasConnected = true
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
          turnInFlight = false
          onDone(msg.text || '', msg.tools_used || [], msg.rounds || 0)
        } else if (msg.type === 'thinking') {
          onThinking()
        } else if (msg.type === 'tool_call_started') {
          onToolCall({ tool: msg.tool, args: msg.args })
        } else if (msg.type === 'tool_call_finished') {
          onToolResult({
            tool: msg.tool,
            status: msg.status === 'fail' ? 'fail' : 'done',
            elapsedMs: msg.elapsed_ms ?? 0,
            result: msg.result,
          })
        } else if (msg.type === 'error') {
          turnInFlight = false
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
      if (closedByClient) return
      if (!hasConnected) {
        reconnectOrFail('WebSocket 连接失败，请检查服务是否正常运行')
        return
      }
      onStateChange('disconnected')
      if (turnInFlight) {
        turnInFlight = false
        onError('连接中断，请重试')
      }
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
        turnInFlight = true
        ws.send(JSON.stringify({ message, history, session_id: getChatSessionId() }))
      } else if (ws == null || ws.readyState === WebSocket.CONNECTING) {
        // 连接还没建立，缓冲等 onopen
        turnInFlight = true
        pendingMessage = { message, history, session_id: getChatSessionId() }
      } else {
        // CLOSING / CLOSED
        onStateChange('disconnected')
        onError('WebSocket 连接已关闭，请刷新页面重试')
      }
    },
    close() {
      closedByClient = true
      turnInFlight = false
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
