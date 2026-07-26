// 轻量 fetch wrapper
// 开发：走 Vite/Taro proxy（/api/*, /ws/*）
// 生产：用环境变量 VITE_API_BASE

import { ref } from 'vue'

const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined) || ''
const TOKEN_KEY = 'mommy-owner-token'
const CHAT_SESSION_KEY = 'mommy-chat-session'

/**
 * 统一 API 错误。
 * - friendly：给用户看的中文人话（页面 / ErrorState 展示）
 * - raw：技术细节（进 console，不给用户看）
 * - status：HTTP 状态码，网络层失败为 0
 */
export class ApiError extends Error {
  readonly status: number
  readonly friendly: string
  readonly raw: string

  constructor(status: number, friendly: string, raw: string) {
    super(friendly)
    this.name = 'ApiError'
    this.status = status
    this.friendly = friendly
    this.raw = raw
  }
}

/** 401 全局标记：任一请求返回 401 置位，任一请求成功后清除（App.vue 顶部横幅用） */
export const authRequired = ref(false)

function friendlyForStatus(status: number): string {
  if (status === 401) return '需要访问令牌'
  if (status === 403) return '没有访问权限'
  if (status === 404) return '没有找到'
  if (status >= 500) return '服务暂时不可用'
  return '请求失败'
}

/** 把任意异常归一化为 ApiError（已是的原样返回；网络错误 / 意外错误包一层） */
export function toApiError(e: unknown, context = '请求'): ApiError {
  if (e instanceof ApiError) return e
  if (e instanceof TypeError) {
    // fetch 网络层失败（服务没起 / 断网 / CORS）
    return new ApiError(0, '网络连接失败', `${context} → 网络错误: ${e.message}`)
  }
  const raw = e instanceof Error ? e.message : String(e)
  return new ApiError(0, '请求失败', `${context} → ${raw}`)
}

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

export function resetChatSessionId(): string {
  if (typeof window === 'undefined') return 'web-default'
  window.sessionStorage.removeItem(CHAT_SESSION_KEY)
  return getChatSessionId()
}

function authHeaders(extra: Record<string, string> = {}): Record<string, string> {
  const token = getApiToken()
  return token ? { ...extra, Authorization: `Bearer ${token}` } : extra
}

async function doFetch(method: string, path: string, init: RequestInit): Promise<Response> {
  let res: Response
  try {
    res = await fetch(`${API_BASE}${path}`, init)
  } catch (e) {
    // 主动取消的请求原样抛出，不包装成 ApiError
    if (e instanceof DOMException && e.name === 'AbortError') throw e
    throw toApiError(e, `${method} ${path}`)
  }
  if (!res.ok) {
    const text = await res.text()
    if (res.status === 401) authRequired.value = true
    throw new ApiError(
      res.status,
      friendlyForStatus(res.status),
      `${method} ${path} → ${res.status}: ${text}`,
    )
  }
  authRequired.value = false
  return res
}

export async function apiGet<T>(path: string): Promise<T> {
  const res = await doFetch('GET', path, { headers: authHeaders() })
  return res.json()
}

export async function apiPost<T>(
  path: string,
  body: unknown,
  signal?: AbortSignal,
): Promise<T> {
  const res = await doFetch('POST', path, {
    method: 'POST',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify(body),
    signal,
  })
  return res.json()
}

export async function apiDelete(path: string): Promise<void> {
  await doFetch('DELETE', path, {
    method: 'DELETE',
    headers: authHeaders(),
  })
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
