/**
 * mommy-chaogu-bridge —— node 半 HTTP 桥（嫁接面 4，web 宿主专用）。
 *
 * 浏览器半（exports['./client']）经同源 fetch 拉数据，本半把请求转成
 * mommy CLI 子进程调用（CLI 是工具箱的稳定契约面）。双宿主安全：
 * webServer/connection 只在 web 宿主存在，apply 内用 ctx.inject 子插件
 * 声明依赖——headless 宿主子 fiber 静默挂起，不崩 profile。
 *
 * 安全：路由挂在 connection.requestRejection 认证栅栏之后（与宿主 /api
 * 同一 browser auth cookie），未认证一律 401/403；数据面端点无凭证、
 * no-store（行情易变，代理层也不许缓存）。
 */
import { homedir } from 'node:os'
import { join } from 'node:path'
import Schema from '@deepseek-ai/schemastery'
import { RevisionBus, attachEventStream } from './events.ts'
import { createRunner, type MommyInvocation, type RunJson } from './spawn.ts'
import type {
  ConnectionLike,
  HostContext,
  MinimalIncomingMessage,
  MinimalServerResponse,
  WebServerLike,
} from './types.ts'

/** Cordis 插件名 = patch 行 id。 */
export const name = 'mommy-chaogu-bridge'

export interface Config {
  /** mommy CLI 命令（默认 PATH 上的 mommy；安装器会用绝对路径覆写）。 */
  mommyCommand: string
  /** 基础参数（uv run 包装时非空）。 */
  mommyArgs: string[]
  /** mommy 数据目录（portfolio.db 所在；失效信号监视用）。 */
  dataDir?: string
}

export const Config: Schema<Config> = Schema.object({
  mommyCommand: Schema.string().default('mommy'),
  mommyArgs: Schema.array(String).default([]),
  dataDir: Schema.string(),
})

export const API_PREFIX = '/mommy/api'
const MAX_QUOTE_CODES = 50
/** 与 mommy CLI / agent 工具一致的代码词法（A 股 6 位 / 美股字母 / ^指数）。 */
const CODE_RE = /^(\^[A-Z]{1,6}|[A-Z]{1,6}|\d{6})$/

/** 发 JSON 响应（禁缓存：行情是易变数据，代理层也不许缓存）。 */
export function sendJson(res: MinimalServerResponse, status: number, payload: unknown): void {
  res.writeHead(status, {
    'content-type': 'application/json; charset=utf-8',
    'cache-control': 'no-store',
  })
  res.end(JSON.stringify(payload))
}

/** 解析 ?codes=a,b,c（逗号分隔；重复去重保持顺序）。 */
export function parseCodes(query: string | null): { ok: true; codes: string[] } | { ok: false; error: string } {
  if (query === null || query.trim() === '') return { ok: false, error: 'missing required query parameter: codes' }
  const seen = new Set<string>()
  const codes: string[] = []
  for (const raw of query.split(',')) {
    const code = raw.trim()
    if (code === '') continue
    if (!CODE_RE.test(code)) return { ok: false, error: `invalid stock code: ${raw}` }
    if (!seen.has(code)) {
      seen.add(code)
      codes.push(code)
    }
  }
  if (codes.length === 0) return { ok: false, error: 'no valid stock codes provided' }
  if (codes.length > MAX_QUOTE_CODES) return { ok: false, error: `too many codes (max ${MAX_QUOTE_CODES})` }
  return { ok: true, codes }
}

export interface BridgeDeps {
  runJson: RunJson
  events: RevisionBus
  connection: ConnectionLike
}

export type BridgeRoute = {
  kind: 'exact'
  path: string
  handler: (req: MinimalIncomingMessage, res: MinimalServerResponse) => Promise<void> | void
}

/** 路由表工厂（纯函数，测试注入 fake deps 直接驱动）。 */
export function createMommyRoutes(deps: BridgeDeps): BridgeRoute[] {
  const guard = (req: MinimalIncomingMessage, res: MinimalServerResponse): boolean => {
    const rejection = deps.connection.requestRejection(req)
    if (rejection !== undefined) {
      sendJson(res, rejection, { error: 'unauthorized' })
      return false
    }
    return true
  }

  const handleWatchlist = async (req: MinimalIncomingMessage, res: MinimalServerResponse): Promise<void> => {
    if (!guard(req, res)) return
    const result = await deps.runJson(['watchlist', 'list', '--json'])
    if (!result.ok) {
      sendJson(res, 502, { error: `mommy watchlist unavailable: ${result.error}` })
      return
    }
    sendJson(res, 200, result.data)
  }

  const handleQuotes = async (req: MinimalIncomingMessage, res: MinimalServerResponse): Promise<void> => {
    if (!guard(req, res)) return
    const url = new URL(req.url ?? '/', 'http://mommy.local')
    const parsed = parseCodes(url.searchParams.get('codes'))
    if (!parsed.ok) {
      sendJson(res, 400, { error: parsed.error })
      return
    }
    const result = await deps.runJson(['quote', ...parsed.codes])
    if (!result.ok) {
      sendJson(res, 502, { error: `mommy quotes unavailable: ${result.error}` })
      return
    }
    sendJson(res, 200, result.data)
  }

  const handleEvents = (req: MinimalIncomingMessage, res: MinimalServerResponse): void => {
    if (!guard(req, res)) return
    attachEventStream(res, deps.events)
  }

  return [
    { kind: 'exact', path: `${API_PREFIX}/watchlist`, handler: handleWatchlist },
    { kind: 'exact', path: `${API_PREFIX}/quotes`, handler: handleQuotes },
    { kind: 'exact', path: `${API_PREFIX}/events`, handler: handleEvents },
  ]
}

function defaultDataDir(): string {
  return process.env.MOMMY_DATA_DIR !== undefined && process.env.MOMMY_DATA_DIR !== ''
    ? process.env.MOMMY_DATA_DIR
    : join(homedir(), '.local', 'share', 'mommy-chaogu')
}

/**
 * Host plugin body：web 宿主注册 /mommy/api 路由 + 失效信号轮询；
 * headless 宿主 inject 子插件永不解析（挂起无害）cordis effect 语义 = 立即
 * 执行回调、返回值即清理函数——副作用必须在 effect 体内发起并返回注销器。
 */
export function apply(ctx: HostContext, config: Config = { mommyCommand: 'mommy', mommyArgs: [] }): void {
  ctx.inject(['webServer', 'connection'], webCtx => {
    const webServer = webCtx.get('webServer') as WebServerLike | undefined
    const connection = webCtx.get('connection') as ConnectionLike | undefined
    if (webServer === undefined || connection === undefined) return

    const invocation: MommyInvocation = { command: config.mommyCommand, baseArgs: config.mommyArgs }
    const dataDir = config.dataDir ?? defaultDataDir()
    const events = new RevisionBus(dataDir)
    // 数据目录显式传给 mommy 子进程（cwd 继承自宿主，不钉住会解析错库）
    const runner = createRunner(invocation, { MOMMY_DATA_DIR: dataDir })
    webCtx.effect(() => {
      events.start()
      return () => {
        events.stop()
      }
    })

    for (const route of createMommyRoutes({ runJson: runner, events, connection })) {
      webCtx.effect(() => webServer.register(route), 'mommy-chaogu-bridge: route')
    }
  })
}
