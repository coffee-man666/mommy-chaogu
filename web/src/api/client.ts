// 轻量 fetch wrapper
// 开发：走 Vite/Taro proxy（/api/*, /ws/*）
// 生产：用环境变量 VITE_API_BASE

const API_BASE = (typeof process !== 'undefined' && process.env?.TARO_APP_API_BASE) || ''

export async function apiGet<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`)
  if (!res.ok) {
    const text = await res.text()
    throw new Error(`GET ${path} → ${res.status}: ${text}`)
  }
  return res.json()
}

export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(`POST ${path} → ${res.status}: ${text}`)
  }
  return res.json()
}

export async function apiDelete(path: string): Promise<void> {
  const res = await fetch(`${API_BASE}${path}`, { method: 'DELETE' })
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
