// 交易风格预设 — P3 个性化
// 存储在 localStorage，影响 Agent 回答侧重点和首页排序优先级

export type StylePreset = 'balanced' | 'conservative' | 'aggressive'

export interface StyleConfig {
  id: StylePreset
  label: string
  emoji: string
  description: string
  /** 给 Agent 的自然语言上下文提示（不暴露 prompt 技术细节） */
  agentHint: string
}

export const STYLE_PRESETS: StyleConfig[] = [
  {
    id: 'conservative',
    label: '稳健',
    emoji: '🛡️',
    description: '注重风险控制，优先提示回撤风险和止损建议',
    agentHint: '用户偏好稳健投资，请更多关注下行风险、止损位和资金安全',
  },
  {
    id: 'balanced',
    label: '均衡',
    emoji: '⚖️',
    description: '兼顾机会与风险，默认的均衡视角',
    agentHint: '用户偏好均衡分析，请同时呈现机会和风险',
  },
  {
    id: 'aggressive',
    label: '积极',
    emoji: '🚀',
    description: '关注短期爆发力和资金动向，寻找进攻机会',
    agentHint: '用户偏好积极策略，请更多关注短期动能、资金流入和爆发机会',
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

export function getStyleAgentHint(): string {
  return getStyleConfig(getStyle()).agentHint
}
