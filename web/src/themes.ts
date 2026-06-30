// 主题配置 —— 6 套预设主题
// 来源：团长 2026-06-28 提供的皇家风 + 交响乐演奏厅系列

export interface ThemeColors {
  primary: string       // 主色（header 渐变、按钮）
  primaryDark: string   // 主色暗调（渐变终止色）
  up: string            // A股涨（红）
  down: string          // A股跌（绿/主题色）
  gold: string          // 金色辅色（数字/强调）
  bg: string            // 页面背景
  card: string          // 卡片背景
  text: string          // 主文字
  textMuted: string     // 弱化文字
  border: string        // 边框
}

export interface Theme {
  id: string
  category: string
  categoryName: string
  name: string
  nameEn: string
  number: string
  description: string
  colors: ThemeColors
}

// 6 套主题（按团长提供的色卡）
// 映射规则：色卡颜色 → 应用 UI 角色
export const THEMES: Theme[] = [
  {
    id: 'forbidden-city',
    category: 'royal',
    categoryName: '中国皇家风',
    name: '紫禁城韵',
    nameEn: 'Forbidden City',
    number: '壹',
    description: '琉璃金瓦映日辉，朱红宫墙锁春秋',
    colors: {
      primary: '#C23A2B',     // 宫墙红
      primaryDark: '#9B2335',
      up: '#C23A2B',          // 涨=宫墙红
      down: '#4A6741',        // 跌=青铜绿
      gold: '#D4A853',        // 琉璃金
      bg: '#F0EDE4',          // 汉白玉
      card: '#FFFFFF',
      text: '#2B2B2B',
      textMuted: '#8B7355',
      border: '#E8E2D2',
    },
  },
  {
    id: 'temple-of-heaven',
    category: 'royal',
    categoryName: '中国皇家风',
    name: '天坛霁蓝',
    nameEn: 'Temple of Heaven',
    number: '贰',
    description: '霁蓝琉璃接天穹，鎏金宝顶耀皇仪',
    colors: {
      primary: '#1B4B8F',     // 霁蓝
      primaryDark: '#0F2E5C',
      up: '#8B1A1A',          // 朱砂红
      down: '#2E5D4E',        // 石青
      gold: '#C9A227',        // 鎏金黄
      bg: '#F5F2EB',
      card: '#FFFFFF',
      text: '#1C2B3A',
      textMuted: '#5C7A95',
      border: '#E0E5EB',
    },
  },
  {
    id: 'dragon-throne',
    category: 'royal',
    categoryName: '中国皇家风',
    name: '龙阙金銮',
    nameEn: 'Dragon Throne',
    number: '叁',
    description: '明黄御绫昭天命，玄青墨底隐龙纹',
    colors: {
      primary: '#9B2335',     // 赭红
      primaryDark: '#6B1820',
      up: '#9B2335',
      down: '#1C2B3A',        // 玄青（深蓝）
      gold: '#E8B94B',        // 明黄
      bg: '#FAF3E8',          // 象牙白
      card: '#FFFFFF',
      text: '#2B2B2B',
      textMuted: '#8B7355',
      border: '#EDE3D0',
    },
  },
  {
    id: 'organ-silver',
    category: 'symphony',
    categoryName: '交响乐演奏厅',
    name: '管风琴银韵',
    nameEn: 'Organ Silver',
    number: '肆',
    description: '银管如林耸入穹，暖木舞台上奏华章',
    colors: {
      primary: '#B8875C',     // 胡桃木
      primaryDark: '#8B6238',
      up: '#B8332E',          // 暖红
      down: '#3D2E22',        // 深褐木
      gold: '#9BA4A8',        // 银管灰
      bg: '#F2EDE6',          // 象牙白
      card: '#FFFFFF',
      text: '#2B2B2B',
      textMuted: '#7A736A',
      border: '#E5DED3',
    },
  },
  {
    id: 'stage-amber',
    category: 'symphony',
    categoryName: '交响乐演奏厅',
    name: '舞台鎏金',
    nameEn: 'Stage Amber',
    number: '伍',
    description: '聚光灯下琥珀暖，铜管声里韵悠长',
    colors: {
      primary: '#C4943D',     // 琥珀金
      primaryDark: '#8E6A2A',
      up: '#B8332E',          // 暖红
      down: '#4A3428',        // 红木棕
      gold: '#B8736A',        // 玫瑰金
      bg: '#F0E8DC',          // 奶白
      card: '#FFFFFF',
      text: '#2B2018',
      textMuted: '#8B7355',
      border: '#E5DCC8',
    },
  },
  {
    id: 'concert-noir',
    category: 'symphony',
    categoryName: '交响乐演奏厅',
    name: '乐手燕尾',
    nameEn: 'Concert Noir',
    number: '陆',
    description: '燕尾如墨映华灯，丝绒深处藏雅音',
    colors: {
      primary: '#6B2D3E',     // 天鹅绒红
      primaryDark: '#3D1822',
      up: '#B8332E',
      down: '#1E1E24',        // 燕尾黑
      gold: '#8B6F4E',        // 古铜
      bg: '#F5F2EC',
      card: '#FFFFFF',
      text: '#1E1E24',
      textMuted: '#6B6457',
      border: '#E0DCD2',
    },
  },
]

export const DEFAULT_THEME_ID = 'forbidden-city'

export function getThemeById(id: string): Theme {
  return THEMES.find(t => t.id === id) || THEMES[0]
}

// 把主题颜色应用到 CSS 变量
export function applyTheme(theme: Theme) {
  const root = document.documentElement
  root.style.setProperty('--color-primary', theme.colors.primary)
  root.style.setProperty('--color-primary-dark', theme.colors.primaryDark)
  root.style.setProperty('--color-up', theme.colors.up)
  root.style.setProperty('--color-down', theme.colors.down)
  root.style.setProperty('--color-gold', theme.colors.gold)
  root.style.setProperty('--color-bg', theme.colors.bg)
  root.style.setProperty('--color-card', theme.colors.card)
  root.style.setProperty('--color-text', theme.colors.text)
  root.style.setProperty('--color-text-muted', theme.colors.textMuted)
  root.style.setProperty('--color-border', theme.colors.border)
}