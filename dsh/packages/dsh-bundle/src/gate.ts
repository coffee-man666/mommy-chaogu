/**
 * mommy-chaogu-gate —— 写操作审批闸门（嫁接面 3）。
 *
 * mommy 的写工具经 MCP 行以 `mcp__mommy-chaogu__<rawName>` 暴露；判定语义
 * 逐条移植自 Python 侧 `agent/service.py` 的 requires_confirmation 白名单：
 * strategy_* 三件套恒确认；manage_watchlist / manage_alert 仅 add/remove
 * 动作确认（list 等查询动作不打扰）。挂 `tools/pre-execute` waterfall，
 * 命中返回 `{kind:'ask'}` 交宿主审批层——永不直接 allow（要么 ask 要么
 * next()）；headless 宿主无审批者时 ask 被宿主自动降级 deny（fail-closed
 * 白送，core/tools serviceAsk 语义）。
 *
 * 两个容易混淆的「写」概念，刻意不同表：
 * - 「有副作用」（Python WRITE_TOOL_NAMES / MCP readOnlyHint=False，7 个）：
 *   含 backfill_history（写行情缓存，非用户数据）与 record_research_conclusion
 *   （写记忆，其 schema 自带 user_confirmed 参数收授权）——它们不进本表，
 *   gate 不应拦；gate.test.ts 对 backfill_history 断言不拦是正确语义。
 * - 「改动用户数据须逐次授权」（确认表 5 项）：自选/告警/策略卡——TUI 确认条
 *   与本闸门共用这张表。前缀命中、确认表查不到、也不在工具面快照里的名字
 *   一律 ask（fail-closed）：快照与 Python registry 漂移时宁可多问一次，
 *   绝不静默放行。
 */
import Schema from '@deepseek-ai/schemastery'
import type { GateListener, HostContext, PreToolDecision } from './types.ts'

/** Cordis 插件名 = patch 行 id。 */
export const name = 'mommy-chaogu-gate'

export interface Config {
  /** 闸门开关；false 时完全不挂监听器（仅测试/显式降级用）。 */
  enabled: boolean
}

export const Config: Schema<Config> = Schema.object({
  enabled: Schema.boolean().default(true),
})

/** MCP serverName（与 patch 行 mommy-chaogu-mcp 的 config.serverName 一致）。 */
export const MCP_TOOL_PREFIX = 'mcp__mommy-chaogu__'

/** 恒确认：策略卡三件套（保存/归档/启用监控是三次独立授权，见产品文档）。 */
export const CONFIRM_ALWAYS: ReadonlySet<string> = new Set([
  'strategy_save',
  'strategy_archive',
  'strategy_activate_monitor',
])

/** 按动作确认：manage_* 的 add/remove 是写，list 等动作是读。 */
export const CONFIRM_BY_ACTION: Readonly<Record<string, ReadonlySet<string>>> = {
  manage_alert: new Set(['add', 'remove']),
  manage_watchlist: new Set(['add', 'remove']),
}

/**
 * mommy 工具面快照（37 个基础工具 + 7 个 research 工具 @ 2026-09-14，
 * 导出自 `agent/tools` registry + `research_tools.RESEARCH_TOOL_DEFS`）。
 * 只用于 fail-closed 判定：前缀命中但既不在确认表、也不在此快照里的
 * 工具名 → ask。新增工具后此表过期，表现为多问一次（可见、安全），
 * 更新此表即可；后续应由 Python 侧导出的 manifest fixture 派生，消灭手抄。
 */
export const MOMMY_TOOL_SURFACE: ReadonlySet<string> = new Set([
  'backfill_history', 'check_earnings_catalyst', 'check_kline_signal',
  'get_announcements', 'get_bars', 'get_fundamentals', 'get_longhuban',
  'get_market_indexes', 'get_market_narrative', 'get_memory_context',
  'get_memory_health', 'get_money_flow_history', 'get_money_flow_today',
  'get_portfolio', 'get_portfolio_analysis', 'get_prediction_history',
  'get_quote', 'get_quotes', 'get_sector_ranking', 'get_sector_stocks',
  'get_theme_stocks', 'get_watchlist', 'list_themes', 'manage_alert',
  'manage_watchlist', 'record_research_conclusion', 'research_market_brief',
  'research_money_flow', 'research_portfolio', 'research_sector',
  'research_stock', 'research_us_market', 'run_backtest',
  'screen_inflow_stocks', 'search_news', 'search_sector',
  'search_similar_events', 'strategy_activate_monitor', 'strategy_archive',
  'strategy_get', 'strategy_list', 'strategy_prepare_application',
  'strategy_prepare_monitor', 'strategy_save',
])

/** 与 Python 侧 requires_confirmation(fn_name, fn_args) 同语义的纯判定。 */
export function requiresConfirmation(rawToolName: string, args: unknown): boolean {
  const actions = CONFIRM_BY_ACTION[rawToolName]
  if (actions !== undefined) {
    const action = (args as { action?: unknown } | null | undefined)?.action
    return typeof action === 'string' && actions.has(action.toLowerCase())
  }
  return CONFIRM_ALWAYS.has(rawToolName)
}

/**
 * 审批理由的增补细节：让用户在审批对话框里看到「他要保存什么」，而不只是
 * 「他要写」。参数形状不信任（工具自校验 schema，这里只做保守读取）——
 * 拿不到关键字段就退回通用理由，绝不因参数形状异常而放行或崩溃。
 */
export function writeDetail(rawToolName: string, args: unknown): string | null {
  const a = (args ?? {}) as Record<string, unknown>
  const str = (v: unknown): string | null => (typeof v === 'string' && v !== '' ? v : null)
  if (rawToolName === 'strategy_save') {
    const card = a.card as { title?: unknown } | undefined
    const title = card === undefined ? null : str(card.title)
    const note = str(a.confirmation_note)
    const parts = [title === null ? null : `策略卡「${title}」`, note === null ? null : `确认注记：${note}`]
    return parts.filter(p => p !== null).join('；') || null
  }
  if (rawToolName === 'strategy_archive' || rawToolName === 'strategy_activate_monitor') {
    const id = str(a.strategy_id)
    return id === null ? null : `策略卡 ${id}`
  }
  const actions = CONFIRM_BY_ACTION[rawToolName]
  if (actions !== undefined) {
    const action = str(a.action)
    const code = str(a.code)
    const parts = [action === null ? null : `${action} ${code ?? ''}`.trim()]
    return parts[0] ?? null
  }
  return null
}

/**
 * 纯判定：这次工具调用是否需要用户审批。
 *
 * 非 mommy 工具或只读调用 → undefined（调用方必须 next()）；写调用 →
 * `{kind:'ask'}`。参数形状不信任（工具自校验 schema，闸门只做保守读取）。
 * 前缀命中但两张表都查不到的 mommy 工具 → `{kind:'ask'}`（fail-closed）：
 * 这是判定表与 Python 侧漂移的信号，静默放行会让审批闸门对新增写工具失效。
 */
export function decideWriteGate(
  toolName: string,
  args: unknown,
  prefix: string = MCP_TOOL_PREFIX,
): PreToolDecision | undefined {
  if (!toolName.startsWith(prefix)) return undefined
  const rawName = toolName.slice(prefix.length)
  if (!(CONFIRM_ALWAYS.has(rawName) || CONFIRM_BY_ACTION[rawName] !== undefined)) {
    if (!MOMMY_TOOL_SURFACE.has(rawName)) {
      return {
        kind: 'ask',
        reason:
          `mommy tool "${toolName}" is not in the gate's tool surface `
          + '(the snapshot may have drifted from the Python registry); failing closed — '
          + 'approve explicitly or update MOMMY_TOOL_SURFACE.',
      }
    }
    return undefined
  }
  if (!requiresConfirmation(rawName, args)) return undefined
  const detail = writeDetail(rawName, args)
  return {
    kind: 'ask',
    reason:
      `mommy tool "${toolName}" modifies user data (watchlist / alerts / strategy cards)`
      + (detail === null ? '' : ` — ${detail}`)
      + '; the mommy-chaogu gate requires explicit user approval. '
      + 'Headless deployments with no approver will deny this call — fail closed by design.',
  }
}

/** waterfall 监听器工厂（独立导出便于单测直接驱动 next() 契约）。 */
export function createGateListener(prefix: string = MCP_TOOL_PREFIX): GateListener {
  return async (exec, next) => decideWriteGate(exec.name, exec.arguments, prefix) ?? next()
}

/** 插件入口：挂统一审批监听器（不声明 inject——事件面无需服务）。 */
export function apply(ctx: HostContext, config: Config = { enabled: true }): void {
  if (config.enabled === false) return
  ctx.on('tools/pre-execute', createGateListener())
}
