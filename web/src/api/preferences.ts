// 服务端持有的用户交易偏好
// 后端为唯一真相源：影响今日排序、AI 回答侧重点、默认回测参数与微信提醒
// （行情数值本身不随风格改变）

import { apiGet, apiPost, apiPut } from './client'

export type TradingStyle = 'conservative' | 'balanced' | 'aggressive'
export type HoldingPeriod = 'short' | 'swing' | 'long'
export type DrawdownSensitivity = 'low' | 'medium' | 'high'
export type NotifySeverity = 'info' | 'warning' | 'critical'

export interface ReminderWindow {
  start: string // "HH:MM"
  end: string // "HH:MM"
}

export interface Preferences {
  style: TradingStyle
  holding_period: HoldingPeriod
  drawdown_sensitivity: DrawdownSensitivity
  notify_min_severity: NotifySeverity
  watched_rules: string[]
  reminder_windows: ReminderWindow[]
  default_hold_days: number
  updated_at: string | null
}

/** PUT /api/preferences 接受的可变字段（partial update） */
export type PreferencesUpdate = Partial<
  Pick<
    Preferences,
    | 'style'
    | 'holding_period'
    | 'drawdown_sensitivity'
    | 'notify_min_severity'
    | 'watched_rules'
    | 'reminder_windows'
  >
>

// ---------- 展示元数据 ----------

export interface StyleConfig {
  id: TradingStyle
  label: string
  emoji: string
  description: string
}

export const STYLE_PRESETS: StyleConfig[] = [
  {
    id: 'conservative',
    label: '稳健',
    emoji: '🛡️',
    description: '注重风险控制，优先提示回撤风险和止损建议',
  },
  {
    id: 'balanced',
    label: '均衡',
    emoji: '⚖️',
    description: '兼顾机会与风险，默认的均衡视角',
  },
  {
    id: 'aggressive',
    label: '积极',
    emoji: '🚀',
    description: '关注短期爆发力和资金动向，寻找进攻机会',
  },
]

export const HOLDING_PERIOD_OPTIONS: Array<{ id: HoldingPeriod; label: string }> = [
  { id: 'short', label: '短线（约 3 天）' },
  { id: 'swing', label: '波段（约 5 天）' },
  { id: 'long', label: '中长线（约 20 天）' },
]

export const DRAWDOWN_OPTIONS: Array<{ id: DrawdownSensitivity; label: string }> = [
  { id: 'low', label: '低' },
  { id: 'medium', label: '中' },
  { id: 'high', label: '高' },
]

export const NOTIFY_SEVERITY_OPTIONS: Array<{ id: NotifySeverity; label: string }> = [
  { id: 'info', label: '提示' },
  { id: 'warning', label: '警告' },
  { id: 'critical', label: '严重' },
]

// ---------- 一次性 localStorage 迁移 ----------

/** 旧版浏览器本地交易风格 key（迁移完成后删除，导出仅供测试） */
export const LEGACY_STYLE_KEY = 'mommy-trading-style'

function readLegacyStyle(): TradingStyle | null {
  if (typeof window === 'undefined') return null
  const stored = localStorage.getItem(LEGACY_STYLE_KEY)
  if (stored && STYLE_PRESETS.some((s) => s.id === stored)) {
    return stored as TradingStyle
  }
  return null
}

/** 旧版风格成功写到服务端后删除本地 key；临时失败保留，供下次重试。 */
async function migrateLegacyStyle(): Promise<void> {
  if (typeof window === 'undefined') return
  const legacy = readLegacyStyle()
  if (legacy === null) {
    localStorage.removeItem(LEGACY_STYLE_KEY)
    return
  }
  try {
    await updatePreferences({ style: legacy })
    localStorage.removeItem(LEGACY_STYLE_KEY)
  } catch {
    // 迁移失败不阻塞服务端读取，也不丢弃旧值；下次加载会再次尝试。
  }
}

// ---------- API ----------

export async function getPreferences(): Promise<Preferences> {
  await migrateLegacyStyle()
  return apiGet<Preferences>('/api/preferences')
}

export function updatePreferences(patch: PreferencesUpdate): Promise<Preferences> {
  return apiPut<Preferences>('/api/preferences', patch)
}

export function resetPreferences(): Promise<Preferences> {
  return apiPost<Preferences>('/api/preferences/reset', {})
}
