/**
 * 浏览器半数据面：同源 fetch /mommy/api（node 半桥注册，宿主认证栅栏内）
 * + SSE 失效信号订阅（EventSource 单例，多卡片/停靠共享一条连接）。
 * 桥不可达时静默降级为一次性 fetch（不劣于现状），SSE 失败不重连轰炸。
 */
import type { QuoteView } from './parse.ts'
import { coerceQuote } from './parse.ts'

export interface WatchlistEntry {
  code: string
  name: string | null
  group: string
  note: string | null
}

export interface QuotesPayload {
  source: string
  quotes: QuoteView[]
  error?: string
}

async function fetchJson<T>(path: string): Promise<T> {
  const res = await fetch(path, { credentials: 'same-origin' })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return (await res.json()) as T
}

export function fetchWatchlist(): Promise<WatchlistEntry[]> {
  return fetchJson<WatchlistEntry[]>('/mommy/api/watchlist')
}

/** 桥返回原始 snake_case 字典；这里强制过 coerceQuote 转视图模型（缺失容错）。
 *  error 字段透传：CLI 拉新失败输出 exit 0 + error 载荷（桥转 200），调用方
 *  须凭它判定降级——丢弃它会把「数据源挂了」伪装成「空自选」。 */
export async function fetchQuotes(codes: string[]): Promise<QuotesPayload> {
  const raw = await fetchJson<{ source: string; quotes: unknown[]; error?: string }>(
    `/mommy/api/quotes?codes=${encodeURIComponent(codes.join(','))}`,
  )
  const quotes = (raw.quotes ?? [])
    .map(coerceQuote)
    .filter((q): q is QuoteView => q !== null)
  const payload: QuotesPayload = { source: raw.source, quotes }
  if (raw.error !== undefined) payload.error = raw.error
  return payload
}

export type StoreName = 'portfolio'

/** SSE store.changed 帧。 */
interface InvalidationEvent {
  store: StoreName
  revision: number
}

type StoreHandlers = Partial<Record<StoreName, () => void>>

let sharedSource: EventSource | null = null
let sharedHandlers: StoreHandlers = {}
const seenRevisions = new Map<StoreName, number>()

// —— 断线重连（指数退避，有限次）：宿主 profile patch 是 live-reload，桥路由
// 会先注销再注册；期间 SSE 断开若不重连，停靠/卡片就永远收不到失效信号。
// 重试上限同时是 headless 错挂（桥永远缺席）的轰炸护栏。
const MAX_RECONNECT_ATTEMPTS = 6
const BASE_RECONNECT_DELAY_MS = 1_000
const MAX_RECONNECT_DELAY_MS = 30_000
let reconnectAttempts = 0
let reconnectTimer: ReturnType<typeof setTimeout> | null = null

export function reconnectDelayMs(attempts: number): number {
  return Math.min(MAX_RECONNECT_DELAY_MS, BASE_RECONNECT_DELAY_MS * 2 ** attempts)
}

function cancelReconnect(): void {
  if (reconnectTimer !== null) {
    clearTimeout(reconnectTimer)
    reconnectTimer = null
  }
}

function scheduleReconnect(): void {
  if (reconnectTimer !== null || Object.keys(sharedHandlers).length === 0) return
  if (reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) return
  const delay = reconnectDelayMs(reconnectAttempts)
  reconnectAttempts += 1
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null
    void ensureSource()
  }, delay)
}

function ensureSource(): EventSource {
  if (sharedSource !== null) return sharedSource
  cancelReconnect()
  const source = new EventSource('/mommy/api/events')
  source.onopen = () => {
    // 连接（重）建立 = 桥就绪信号：首屏 fetch 可能落在 patch live-reload 前的
    // 旧桥上（profile 覆盖行未生效 → 默认数据目录 → 空表），就绪后统一重拉。
    // 同时清空 revision 去重基数——新桥实例的 revision 从 1 重新计数，旧基数
    // 会把换桥后的头几条信号全部吞掉。
    reconnectAttempts = 0
    seenRevisions.clear()
    for (const handler of Object.values(sharedHandlers)) handler?.()
  }
  source.addEventListener('store.changed', event => {
    try {
      const payload = JSON.parse(String((event as MessageEvent).data)) as InvalidationEvent
      const last = seenRevisions.get(payload.store)
      if (last !== undefined && payload.revision <= last) return
      seenRevisions.set(payload.store, payload.revision)
      sharedHandlers[payload.store]?.()
    } catch {
      // 帧损坏：忽略（下一次信号仍会触发）
    }
  })
  source.onerror = () => {
    source.close()
    if (sharedSource !== source) return
    sharedSource = null
    scheduleReconnect()
  }
  sharedSource = source
  return source
}

/** 订阅失效信号；返回退订函数（最后一个订阅者退订时关闭共享连接）。 */
export function subscribeMommyEvents(handlers: StoreHandlers): () => void {
  sharedHandlers = { ...sharedHandlers }
  for (const [store, handler] of Object.entries(handlers)) {
    if (handler !== undefined) sharedHandlers[store as StoreName] = handler
  }
  reconnectAttempts = 0
  void ensureSource()
  let active = true
  return () => {
    if (!active) return
    active = false
    // 共享单例随首个订阅者建立；退订只摘自己的 handler，连接留给仍订阅者。
    for (const [store, handler] of Object.entries(handlers)) {
      if (handler !== undefined && sharedHandlers[store as StoreName] === handler) {
        delete sharedHandlers[store as StoreName]
      }
    }
    // 没有订阅者了：pending 的重连也不必再发生。
    if (Object.keys(sharedHandlers).length === 0) cancelReconnect()
  }
}
