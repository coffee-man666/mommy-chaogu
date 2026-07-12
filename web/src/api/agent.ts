// Agent API client
import { apiPost, wsUrl } from './client'

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

export async function agentChat(
  message: string,
  history?: Array<{ role: string; content: string }>,
): Promise<ChatResponse> {
  return apiPost<ChatResponse>('/api/agent/chat', { message, history })
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
): {
  send: (message: string, history?: Array<{ role: string; content: string }>) => void
  close: () => void
} {
  // 连接建立前的待发消息缓冲
  let pendingMessage: { message: string; history?: Array<{ role: string; content: string }> } | null = null
  // 初始连接失败时，最多重试一次
  let retried = false
  let closedByClient = false
  let retryTimer: number | null = null
  let ws = new WebSocket(wsUrl('/ws/agent'))

  function attachHandlers(socket: WebSocket) {
    socket.onopen = () => {
      if (closedByClient) {
        socket.close()
        return
      }
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
          onError(msg.message || '未知错误')
        }
      } catch {
        // ignore parse errors
      }
    }

    socket.onerror = () => {
      if (closedByClient) return
      if (socket.readyState === WebSocket.CONNECTING && !retried) {
        // 初始连接失败，2 秒后重连一次
        retried = true
        socket.close()
        retryTimer = window.setTimeout(() => {
          retryTimer = null
          if (closedByClient) return
          ws = new WebSocket(wsUrl('/ws/agent'))
          attachHandlers(ws)
        }, 2000)
      } else if (socket.readyState === WebSocket.CONNECTING) {
        onError('WebSocket 连接失败，请检查服务是否正常运行')
      } else {
        onError('WebSocket 连接中断')
      }
    }
  }

  attachHandlers(ws)

  return {
    send(message: string, history?: Array<{ role: string; content: string }>) {
      if (closedByClient) {
        onError('WebSocket 连接已关闭，请重新发送消息')
        return
      }
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ message, history }))
      } else if (ws.readyState === WebSocket.CONNECTING) {
        // 连接还没建立，缓冲等 onopen
        pendingMessage = { message, history }
      } else {
        // CLOSING / CLOSED
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
      ws.onopen = null
      ws.onmessage = null
      ws.onerror = null
      ws.close()
    },
  }
}
