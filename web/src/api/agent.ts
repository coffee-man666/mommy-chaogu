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

export async function agentRoute(message: string): Promise<RouteResponse> {
  return apiPost<RouteResponse>('/api/agent/route', { message })
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
  const ws = new WebSocket(wsUrl('/ws/agent'))

  ws.onmessage = (event) => {
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

  ws.onerror = () => onError('WebSocket 连接失败')

  return {
    send(message: string, history?: Array<{ role: string; content: string }>) {
      ws.send(JSON.stringify({ message, history }))
    },
    close() {
      ws.close()
    },
  }
}
