/**
 * 客户端配置（纯展示偏好）：localStorage 持久化 + 跨组件同步。
 *
 * 纪律：这里只放渲染/展示偏好。任何影响数据语义的口径（复权、周期、均线
 * 窗口）唯一真相源在服务端工具参数，绝不进浏览器侧配置。Storage 不可用
 * （隐私模式）时静默退化为默认值，功能不受影响；未知取值一律回落默认
 * （与 parse.ts 的 fail-safe 同款纪律）。
 */
export type BarsMode = 'table' | 'svg' | 'lwc'

export interface MommyClientConfig {
  /** get_bars 卡片渲染模式：表格 / 自绘迷你 K 线 / Lightweight-Charts 交互图。 */
  barsMode: BarsMode
}

export const DEFAULT_CONFIG: MommyClientConfig = { barsMode: 'svg' }

const STORAGE_KEY = 'mommy.client.config.v1'
const CHANGE_EVENT = 'mommy:config-changed'

const BARS_MODES: readonly BarsMode[] = ['table', 'svg', 'lwc']

function normalize(raw: unknown): MommyClientConfig {
  const r = (typeof raw === 'object' && raw !== null ? raw : {}) as Partial<MommyClientConfig>
  return {
    barsMode: BARS_MODES.includes(r.barsMode as BarsMode) ? (r.barsMode as BarsMode) : DEFAULT_CONFIG.barsMode,
  }
}

function storage(): Storage | null {
  try {
    return typeof localStorage === 'undefined' ? null : localStorage
  } catch {
    return null
  }
}

let cached: MommyClientConfig | null = null

export function loadConfig(): MommyClientConfig {
  if (cached !== null) return cached
  const store = storage()
  if (store === null) {
    cached = { ...DEFAULT_CONFIG }
    return cached
  }
  try {
    const raw = store.getItem(STORAGE_KEY)
    cached = raw === null ? { ...DEFAULT_CONFIG } : normalize(JSON.parse(raw))
  } catch {
    cached = { ...DEFAULT_CONFIG }
  }
  return cached
}

export function saveConfig(patch: Partial<MommyClientConfig>): MommyClientConfig {
  cached = normalize({ ...loadConfig(), ...patch })
  const store = storage()
  if (store !== null) {
    try {
      store.setItem(STORAGE_KEY, JSON.stringify(cached))
    } catch {
      // 隐私模式等 storage 不可用：只影响本次会话内存态
    }
  }
  emitChange()
  return cached
}

/** 订阅配置变更（同文档内广播，不跨 tab）。返回注销函数。 */
export function subscribeConfig(listener: () => void): () => void {
  if (typeof window === 'undefined') return () => {}
  const handler = () => listener()
  window.addEventListener(CHANGE_EVENT, handler)
  return () => window.removeEventListener(CHANGE_EVENT, handler)
}

function emitChange(): void {
  if (typeof window === 'undefined') return
  window.dispatchEvent(new CustomEvent(CHANGE_EVENT))
}

/** 测试辅助：清空内存缓存（不清理外部注入的 storage，由用例自理）。 */
export function resetConfigCacheForTest(): void {
  cached = null
}
