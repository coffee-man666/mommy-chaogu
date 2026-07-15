// 轻量 fetch wrapper
// 开发：走 Vite/Taro proxy（/api/*, /ws/*）
// 生产：用环境变量 VITE_API_BASE

const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined) || ''
const TOKEN_KEY = 'mommy-owner-token'
const CHAT_SESSION_KEY = 'mommy-chat-session'

export function getApiToken(): string {
  if (typeof window === 'undefined') return ''
  return window.sessionStorage.getItem(TOKEN_KEY) || ''
}

export function setApiToken(token: string): void {
  if (typeof window === 'undefined') return
  const normalized = token.trim()
  if (normalized) window.sessionStorage.setItem(TOKEN_KEY, normalized)
  else window.sessionStorage.removeItem(TOKEN_KEY)
}

export function getChatSessionId(): string {
  if (typeof window === 'undefined') return 'web-default'
  const existing = window.sessionStorage.getItem(CHAT_SESSION_KEY)
  if (existing) return existing
  const generated = `web-${crypto.randomUUID()}`
  window.sessionStorage.setItem(CHAT_SESSION_KEY, generated)
  return generated
}

function authHeaders(extra: Record<string, string> = {}): Record<string, string> {
  const token = getApiToken()
  return token ? { ...extra, Authorization: `Bearer ${token}` } : extra
}

export async function apiGet<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { headers: authHeaders() })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(`GET ${path} → ${res.status}: ${text}`)
  }
  return res.json()
}

export async function apiPost<T>(
  path: string,
  body: unknown,
  signal?: AbortSignal,
): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify(body),
    signal,
  })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(`POST ${path} → ${res.status}: ${text}`)
  }
  return res.json()
}

export async function apiDelete(path: string): Promise<void> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: 'DELETE',
    headers: authHeaders(),
  })
  if (!res.ok && res.status !== 204) {
    const text = await res.text()
    throw new Error(`DELETE ${path} → ${res.status}: ${text}`)
  }
}

export function wsUrl(path: string): string {
  if (typeof window === 'undefined') return ''
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  // 生产用相对路径，开发用 proxy
  if (API_BASE) {
    return `${API_BASE.replace(/^http/, 'ws')}${path}`
  }
  return `${protocol}//${window.location.host}${path}`
}

export async function authenticatedWsUrl(path: string): Promise<string> {
  const token = getApiToken()
  if (!token) return wsUrl(path)
  const response = await apiPost<{ ticket: string; expires_at: number }>(
    '/api/auth/ws-ticket',
    {},
  )
  const separator = path.includes('?') ? '&' : '?'
  return wsUrl(`${path}${separator}ticket=${encodeURIComponent(response.ticket)}`)
}
