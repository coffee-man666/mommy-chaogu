// 判断市场阶段（A 股 Asia/Shanghai 或 美股 America/New_York）
// 移植自 src/mommy_chaogu/tui/widgets/top_bar.py market_phase()
//
// 用于：StatusBar 的"交易中/午休/已收盘/集合竞价"标签，
// 以及看板的自适应轮询节奏（交易中 5s / 午休 60s / 收盘停）。

export type MarketPhase = '交易中' | '午休' | '集合竞价' | '已收盘' | '盘前' | '盘后'

const SHANGHAI_TZ = 'Asia/Shanghai'
const NY_TZ = 'America/New_York'

/** 检测代码属于哪个市场（字母开头=美股，数字开头=A 股）。 */
export function detectMarket(code: string): 'CN' | 'US' {
  return code && /^[A-Z]/i.test(code) ? 'US' : 'CN'
}

/** 当前指定时区的 {hm, weekday}。 */
function nowInTz(tz: string): { hm: number; weekday: number } {
  const fmt = new Intl.DateTimeFormat('en-US', {
    timeZone: tz,
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

/** A 股市场阶段。 */
export function marketPhase(): MarketPhase {
  const { hm, weekday } = nowInTz(SHANGHAI_TZ)
  if (weekday >= 5) return '已收盘'
  if (hm >= 555 && hm < 565) return '集合竞价' // 9:15-9:25
  if ((hm >= 570 && hm < 690) || (hm >= 780 && hm < 900)) return '交易中' // 9:30-11:30, 13:00-15:00
  if (hm >= 690 && hm < 780) return '午休' // 11:30-13:00
  return '已收盘'
}

/** 美股市场阶段。 */
export function usMarketPhase(): MarketPhase {
  const { hm, weekday } = nowInTz(NY_TZ)
  if (weekday >= 5) return '已收盘'
  if (hm >= 240 && hm < 570) return '盘前' // 4:00-9:30 ET
  if (hm >= 570 && hm < 960) return '交易中' // 9:30-16:00 ET
  if (hm >= 960 && hm < 1080) return '盘后' // 16:00-18:00 ET
  return '已收盘'
}

/** 按代码自动返回对应市场的阶段。 */
export function marketPhaseForCode(code: string): MarketPhase {
  return detectMarket(code) === 'US' ? usMarketPhase() : marketPhase()
}

/** Asia/Shanghai 当前 HH:MM:SS。 */
export function shanghaiClock(): string {
  return new Date().toLocaleTimeString('zh-CN', {
    hour12: false,
    timeZone: SHANGHAI_TZ,
  })
}

/** America/New_York 当前 HH:MM:SS。 */
export function nyClock(): string {
  return new Date().toLocaleTimeString('zh-CN', {
    hour12: false,
    timeZone: NY_TZ,
  })
}
