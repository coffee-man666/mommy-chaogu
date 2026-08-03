// 预测证据展示辅助 — 决策记录 Tab 与预测跟踪页共用
// data_coverage_* 是后端写入的 JSON 字符串（历史行可能为 null / 老格式），
// 所有解析都是防御式的：任何异常都退回「未记录」，绝不在渲染中抛错。

/** 验证倒计时（pending 预测距 verify_after 的剩余时间）。 */
export function fmtCountdown(iso: string): string {
  const d = new Date(iso)
  if (isNaN(d.getTime())) return '-'
  const diff = d.getTime() - Date.now()
  if (diff <= 0) return '已到期'
  const days = Math.floor(diff / 86_400_000)
  const hours = Math.floor((diff % 86_400_000) / 3_600_000)
  if (days >= 1) return `${days}天后`
  if (hours >= 1) return `${hours}小时后`
  const mins = Math.floor((diff % 3_600_000) / 60_000)
  return `${mins}分钟后`
}

/** 依据覆盖 key → 中文标签；未收录的 truthy key 原样展示 key 名。 */
const COVERAGE_LABELS: Record<string, string> = {
  quote: '行情',
  kline: 'K线',
  bars: 'K线',
  flow: '资金流',
  money_flow: '资金流',
  flow_today: '当日资金流',
  flow_5d: '5日资金流',
  news: '新闻',
  earnings: '业绩',
}

/**
 * 解析 data_coverage_at_creation → 徽章标签数组。
 * 返回 null 表示「未记录」（null / 解析失败 / 非对象）。
 */
export function coverageBadgeLabels(json: string | null | undefined): string[] | null {
  if (!json) return null
  try {
    const parsed: unknown = JSON.parse(json)
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return null
    const labels: string[] = []
    for (const [key, value] of Object.entries(parsed)) {
      if (!value) continue
      const label = COVERAGE_LABELS[key] ?? key
      if (!labels.includes(label)) labels.push(label)
    }
    return labels
  } catch {
    return null
  }
}

/**
 * 解析 data_coverage_at_verify → 新鲜度文案。
 * 新格式 {quote, quote_age_seconds, source} / 老格式 {quote: bool} / null → 未记录。
 */
export function verifyFreshnessText(json: string | null | undefined): string {
  if (!json) return '未记录'
  try {
    const parsed: unknown = JSON.parse(json)
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return '未记录'
    const data = parsed as Record<string, unknown>
    const parts: string[] = []
    if (typeof data.source === 'string') {
      // 后端取值：adapter=实时报价，stale_cache=缓存报价（也兼容 live/cache 写法）
      const SOURCE_LABELS: Record<string, string> = {
        adapter: '实时报价',
        live: '实时报价',
        stale_cache: '缓存报价',
        cache: '缓存报价',
      }
      const sourceLabel = SOURCE_LABELS[data.source] ?? data.source
      parts.push(`验证数据：${sourceLabel}`)
    } else if (typeof data.quote === 'boolean') {
      parts.push(`验证数据：报价${data.quote ? '可用' : '不可用'}`)
    }
    if (typeof data.quote_age_seconds === 'number') {
      parts.push(`报价年龄 ${data.quote_age_seconds}s`)
    }
    return parts.length > 0 ? parts.join(' · ') : '未记录'
  } catch {
    return '未记录'
  }
}
