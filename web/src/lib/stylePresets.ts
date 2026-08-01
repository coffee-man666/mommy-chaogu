// 交易风格预设 — P3 个性化
// 存储在 localStorage，影响 Agent 回答侧重点和首页排序优先级

export type StylePreset = 'balanced' | 'conservative' | 'aggressive'

export interface StyleConfig {
  id: StylePreset
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

const STYLE_KEY = 'mommy-trading-style'

export function getStyle(): StylePreset {
  if (typeof window === 'undefined') return 'balanced'
  const stored = localStorage.getItem(STYLE_KEY)
  if (stored && STYLE_PRESETS.some(s => s.id === stored)) {
    return stored as StylePreset
  }
  return 'balanced'
}

export function setStyle(style: StylePreset): void {
  if (typeof window === 'undefined') return
  localStorage.setItem(STYLE_KEY, style)
}

export function getStyleConfig(style: StylePreset): StyleConfig {
  return STYLE_PRESETS.find(s => s.id === style) ?? STYLE_PRESETS[1]
}
