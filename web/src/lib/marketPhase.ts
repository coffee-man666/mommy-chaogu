// 判断 A 股市场阶段（Asia/Shanghai 时区）
// 移植自 src/mommy_chaogu/tui/widgets/top_bar.py market_phase()
//
// 用于：StatusBar 的"交易中/午休/已收盘/集合竞价"标签，
// 以及看板的自适应轮询节奏（交易中 5s / 午休 60s / 收盘停）。

export type MarketPhase = '交易中' | '午休' | '集合竞价' | '已收盘'

const SHANGHAI_TZ = 'Asia/Shanghai'

/** 当前 Asia/Shanghai 时区的 Date（用 toLocaleString 拿 parts，避免依赖 Temporal）。 */
function nowInShanghai(): { hm: number; weekday: number } {
  const fmt = new Intl.DateTimeFormat('en-US', {
    timeZone: SHANGHAI_TZ,
    hour: 'numeric',
    minute: 'numeric',
    weekday: 'short',
    hour12: false,
  })
  const parts = fmt.formatToParts(new Date())
  const get = (t: string) => parts.find((p) => p.type === t)?.value ?? ''
  const h = parseInt(get('hour'), 10) % 24
  const m = parseInt(get('minute'), 10)
  const wdMap: Record<string, number> = { Sun: 0, Mon: 1, Tue: 2, Wed: 3, Thu: 4, Fri: 5, Sat: 6 }
  return { hm: h * 60 + m, weekday: wdMap[get('weekday')] ?? 0 }
}

export function marketPhase(): MarketPhase {
  const { hm, weekday } = nowInShanghai()
  if (weekday >= 5) return '已收盘'
  if (hm >= 555 && hm < 565) return '集合竞价' // 9:15-9:25
  if ((hm >= 570 && hm < 690) || (hm >= 780 && hm < 900)) return '交易中' // 9:30-11:30, 13:00-15:00
  if (hm >= 690 && hm < 780) return '午休' // 11:30-13:00
  return '已收盘'
}

/** Asia/Shanghai 当前 HH:MM:SS。 */
export function shanghaiClock(): string {
  return new Date().toLocaleTimeString('zh-CN', {
    hour12: false,
    timeZone: SHANGHAI_TZ,
  })
}
