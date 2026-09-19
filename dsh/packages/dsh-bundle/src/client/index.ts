/**
 * mommy-chaogu 浏览器半（嫁接面 4）：对话流富卡片 + 右缘自选停靠。
 *
 * Slot 布局（不改 DSH 源码，全部走官方 slot 机制）：
 * - `tool.call.toolview` ×7（key = 宿主公开工具名 mcp__mommy-chaogu__*）：
 *   报价 / 批量报价 / 指数 / 资金流 / K 线（三渲染模式）/ 预测历史 / 自选写回执；
 * - `shell.overlay`（mommy-chaogu-watchlist-dock）→ 右缘自选停靠（固定右缘
 *   满高面板，可收起为右缘垂直拉手）。
 *
 * 静态包的 slot 条目崩溃默认无人上报（监督缝只覆盖动态插件）——打到
 * console 可见化。数据经 node 半 /mommy/api 同源桥。
 *
 * 另含发送链路看门狗（sendWatchdog）：宿主一元 RPC 无 deadline，传输
 * 挂起时用户消息会三重静默丢失（气泡滞留 / 无横幅 / 宿主零痕迹），
 * 此处只做检测与提醒，不改变任何请求语义。
 */
import type { Context as ClientContext } from '@deepseek-ai/cordis'
import {
  BacktestCard,
  BarsCard,
  FlowCard,
  FlowHistoryCard,
  IndexesCard,
  KlineSignalCard,
  PredictionsCard,
  QuoteCard,
  QuotesCard,
  RecordConclusionCard,
  ScreenInflowCard,
  SimilarEventsCard,
  WatchlistOpCard,
} from './cards.tsx'
import { MommyDock } from './dock.tsx'
import { en, zh } from './locales.ts'
import { installSendWatchdog } from './sendWatchdog.ts'
import './tokens.css'

/**
 * 浏览器 cordis Context 的最小结构面：slots/locale 是宿主 client 服务的
 * 声明合并面（dsh-client-ui-slots / dsh-client-locale），此处以本地鸭式
 * 声明替代对未安装宿主包的类型依赖（与 types.ts 同款纪律）。
 */
interface SlotsFace {
  onEntryError?(reporter: (slot: string, entry: unknown, error: unknown) => void): unknown
  inject(slot: string, factory: () => unknown): unknown
  register(
    registration: { name: string; key?: string; id?: string; order?: number; locale?: string },
    component: unknown,
  ): unknown
}

interface LocaleFace {
  bind(ns: string): unknown
  register(ns: string, dictionaries: Record<string, unknown>): unknown
}

/** 本面板/字符串翻译的 locale namespace。 */
const NS = 'mommy.chaogu'

/** Required services：slot 注册面 + locale；无宿主会话面依赖（停靠不写会话）。 */
export const inject = ['slots', 'locale']

/** MCP 公开工具名（宿主 mcp-client 命名 mcp__<serverName>__<rawName>）。 */
const TOOL = (raw: string) => `mcp__mommy-chaogu__${raw}`

export function apply(ctx: ClientContext): void {
  // 发送链路看门狗：boot 时安装，覆盖连接层后续全部一元 RPC（幂等）。
  installSendWatchdog()

  const slots = (ctx as unknown as { slots: SlotsFace }).slots
  const locale = (ctx as unknown as { locale: LocaleFace }).locale
  // bind 的 t 由 slot 的 locale: NS 声明经框架注入组件；本文件不直接消费。
  locale.bind(NS)
  const effect = (ctx as unknown as { effect(dispose: () => unknown, label?: string): unknown }).effect
  // effect 语义 = 立即执行并取返回值为清理函数：register 的注销器原样交还宿主
  effect(() => locale.register(NS, { zh, en }), 'mommy-chaogu: dictionaries')

  // 静态包 slot 条目崩溃 console 可见化（dsh-trading 同款纪律）。
  slots.onEntryError?.((slot: string, _entry: unknown, error: unknown) => {
    console.error(`[mommy-chaogu] slot entry crashed: ${slot}`, error)
  })

  // 对话内富卡片：keyed slot，一个工具一把。
  slots.inject('tool.call.toolview', function* () {
    yield slots.register({ name: 'tool.call.toolview', key: TOOL('get_quote'), locale: NS }, QuoteCard)
    yield slots.register({ name: 'tool.call.toolview', key: TOOL('get_quotes'), locale: NS }, QuotesCard)
    yield slots.register({ name: 'tool.call.toolview', key: TOOL('get_market_indexes'), locale: NS }, IndexesCard)
    yield slots.register({ name: 'tool.call.toolview', key: TOOL('get_money_flow_today'), locale: NS }, FlowCard)
    yield slots.register({ name: 'tool.call.toolview', key: TOOL('get_bars'), locale: NS }, BarsCard)
    yield slots.register({ name: 'tool.call.toolview', key: TOOL('get_prediction_history'), locale: NS }, PredictionsCard)
    yield slots.register({ name: 'tool.call.toolview', key: TOOL('manage_watchlist'), locale: NS }, WatchlistOpCard)
    yield slots.register({ name: 'tool.call.toolview', key: TOOL('check_kline_signal'), locale: NS }, KlineSignalCard)
    yield slots.register({ name: 'tool.call.toolview', key: TOOL('run_backtest'), locale: NS }, BacktestCard)
    yield slots.register({ name: 'tool.call.toolview', key: TOOL('get_money_flow_history'), locale: NS }, FlowHistoryCard)
    yield slots.register({ name: 'tool.call.toolview', key: TOOL('screen_inflow_stocks'), locale: NS }, ScreenInflowCard)
    yield slots.register({ name: 'tool.call.toolview', key: TOOL('search_similar_events'), locale: NS }, SimilarEventsCard)
    yield slots.register({ name: 'tool.call.toolview', key: TOOL('record_research_conclusion'), locale: NS }, RecordConclusionCard)
  })

  // 左侧自选停靠（官方浮层通道）。
  slots.inject('shell.overlay', () =>
    slots.register(
      { name: 'shell.overlay', id: 'mommy-chaogu-watchlist-dock', order: 10, locale: NS },
      MommyDock as never,
    ),
  )
}
