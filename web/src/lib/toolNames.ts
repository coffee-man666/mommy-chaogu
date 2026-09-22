// 工具名 → 中文显示名
// 移植自 src/mommy_chaogu/tui/widgets/tool_indicator.py TOOL_DISPLAY_NAMES
// 覆盖 agent/tools/ 的 37 个工具（tests/test_tool_surface_mirrors.py 断言完备，
// 漏加会红）；新工具若缺中文会 fallback 到原名。

export const TOOL_DISPLAY_NAMES: Record<string, string> = {
  get_quote: '查行情',
  get_quotes: '批量查行情',
  get_market_indexes: '查大盘指数',
  get_sector_ranking: '查板块排行',
  search_sector: '搜板块',
  get_sector_stocks: '查板块成分股',
  get_money_flow_today: '查今日资金流',
  get_money_flow_history: '查资金流历史',
  get_bars: '查K线',
  get_watchlist: '查自选股',
  manage_watchlist: '管理自选股',
  get_portfolio: '查持仓',
  search_news: '搜新闻',
  get_announcements: '查公告',
  get_longhuban: '查龙虎榜',
  get_fundamentals: '查基本面',
  get_portfolio_analysis: '持仓分析',
  backfill_history: '补历史数据',
  manage_alert: '管理告警',
  search_similar_events: '搜相似事件',
  get_prediction_history: '查预测记录',
  get_market_narrative: '查市场叙事',
  list_themes: '查主题列表',
  get_theme_stocks: '查主题个股',
  get_memory_context: '查记忆',
  get_memory_health: '查记忆健康',
  check_earnings_catalyst: '查业绩催化',
  check_kline_signal: '查K线信号',
  screen_inflow_stocks: '筛主力流入',
  run_backtest: '回放回测',
  strategy_save: '保存策略卡',
  strategy_archive: '归档策略卡',
  strategy_activate_monitor: '启用策略监控',
  strategy_list: '查策略卡',
  strategy_get: '查策略卡详情',
  strategy_prepare_application: '准备策略应用',
  strategy_prepare_monitor: '准备策略监控',
}

export function toolDisplayName(tool: string): string {
  return TOOL_DISPLAY_NAMES[tool] ?? tool
}

/** 词边界截断（对标 TUI truncate_at_word）。超过 maxLen 在词边界加 …，否则原样。 */
export function truncateAtWord(text: string, maxLen: number): string {
  if (text.length <= maxLen) return text
  const cut = text.lastIndexOf(' ', maxLen)
  if (cut > maxLen * 0.5) return text.slice(0, cut) + '…'
  return text.slice(0, maxLen) + '…'
}

/**
 * 格式化工具参数用于单行展示。移植自 TUI format_tool_args。
 * query 类参数显示为 "..."；其余 k=v 拼接，单值最长 40 字符。
 */
export function formatToolArgs(args: Record<string, unknown> | undefined | null): string {
  if (!args) return ''
  const query = args.query
  if (typeof query === 'string') return `"${truncateAtWord(query, 40)}"`
  const parts: string[] = []
  for (const [key, value] of Object.entries(args)) {
    if (typeof value === 'string') parts.push(`${key}=${truncateAtWord(value, 40)}`)
    else if (typeof value === 'number' || typeof value === 'boolean') parts.push(`${key}=${value}`)
  }
  return parts.join(', ')
}

/**
 * 工具结果 → 单行摘要：取首行、压缩空白、截断。移植自 TUI format_result_digest。
 */
export function formatResultDigest(result: string, maxLen = 60): string {
  const trimmed = result.trim()
  if (!trimmed) return '完成'
  const firstLine = trimmed.split(/\r?\n/, 1)[0]
  const collapsed = firstLine.split(/\s+/).join(' ')
  return truncateAtWord(collapsed, maxLen)
}
