// 共享格式化工具 — 消除多页面重复定义

/** 格式化价格，保留 2 位小数 */
export function fmtPrice(s: string | number | null | undefined): string {
  if (s == null) return '-'
  const n = Number(s)
  if (isNaN(n)) return String(s)
  return n.toFixed(2)
}

/** 格式化涨跌幅，自动加 + 号 */
export function fmtPct(s: string | number | null | undefined): string {
  if (s == null) return '-'
  const n = Number(s)
  if (isNaN(n)) return String(s)
  return `${n >= 0 ? '+' : ''}${n.toFixed(2)}%`
}

/** 大金额智能转 万/亿 */
export function fmtWan(s: string | number | null | undefined): string {
  if (s == null || s === '') return '-'
  const n = Number(s)
  if (isNaN(n)) return String(s)
  if (Math.abs(n) >= 1e8) return `${(n / 1e8).toFixed(2)}亿`
  if (Math.abs(n) >= 1e4) return `${(n / 1e4).toFixed(2)}万`
  return n.toFixed(2)
}

/** 精确金额格式化，指定单位 */
export function fmtMoney(
  s: string | number | null | undefined,
  unit: 'yuan' | 'wan' | 'yi' = 'yuan'
): string {
  if (s == null || s === '') return '-'
  const n = Number(s)
  if (isNaN(n)) return String(s)
  if (unit === 'yi') return `${(n / 1e8).toFixed(2)}亿`
  if (unit === 'wan') return `${(n / 1e4).toFixed(2)}万`
  return n.toFixed(2)
}

/** 数据年龄格式化 */
export function fmtAge(seconds: number): string {
  if (seconds < 60) return `${seconds}秒前`
  if (seconds < 3600) return `${Math.floor(seconds / 60)}分钟前`
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}小时前`
  return `${Math.floor(seconds / 86400)}天前`
}

/** A 股红涨绿跌颜色 */
export function changeColor(changePct: string | number | null | undefined): string {
  if (changePct == null) return '#666'
  const n = Number(changePct)
  if (isNaN(n)) return '#666'
  if (n > 0) return '#c83e3e' // 红涨
  if (n < 0) return '#2d8e3d' // 绿跌
  return '#666'
}

/** 盈亏颜色（使用 CSS 变量） */
export function pnlColor(pnl: string | number | null | undefined): string {
  if (pnl == null || pnl === '') return '#999'
  return Number(pnl) >= 0 ? 'var(--color-primary)' : 'var(--color-down)'
}

/** 盈亏正负号 */
export function pnlSign(pnl: string | number | null | undefined): string {
  if (pnl == null || pnl === '') return ''
  return Number(pnl) >= 0 ? '+' : ''
}
