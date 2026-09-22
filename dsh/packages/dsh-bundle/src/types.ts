/**
 * 宿主服务的最小结构面（鸭式）——避免对未安装的宿主包产生类型依赖，
 * dsh-trading client-ui-trading 同款纪律。签名语义以 DSH 0.1.5-rc 系
 * 源码为准（packages/core/tools 的 Events 声明、web 宿主的 webServer）。
 */

/** cordis Context 的最小面（事件 + inject + effect + get）。 */
export interface HostContext {
  on(event: 'tools/pre-execute', listener: GateListener): () => void
  inject(services: readonly string[], callback: (ctx: HostContext) => void): unknown
  effect(dispose: () => unknown, label?: string): unknown
  get(key: string, strict?: boolean): unknown
}

/**
 * tools/pre-execute waterfall 监听器（core/tools Events 声明）：
 * 返回决策对象即截断，返回 next() 的结果继续 waterfall——监听器永不
 * 直接 allow，避免越过宿主其他策略层。
 */
export type GateListener = (
  this: unknown,
  exec: ToolExecution,
  next: () => Promise<PreToolDecision>,
) => Promise<PreToolDecision>

/** waterfall 的执行描述：工具名 + 参数（形状不信任，判定只做保守读取）。 */
export interface ToolExecution {
  name: string
  arguments: unknown
}

/** 三态决策（core/tools PreToolDecision 的结构子集）。 */
export type PreToolDecision =
  | { kind: 'allow' }
  | { kind: 'deny'; reason?: string }
  | { kind: 'ask'; reason?: string }

/** web 宿主 webServer 的最小面：注册路由，返回注销器。 */
export interface WebServerLike {
  register(route: {
    kind: 'exact' | 'prefix'
    path: string
    handler: (req: MinimalIncomingMessage, res: MinimalServerResponse) => void | Promise<void>
  }): () => void
}

/** web 宿主 connection 的认证栅栏：返回 401/403 状态码，undefined = 放行。 */
export interface ConnectionLike {
  requestRejection(req: MinimalIncomingMessage): number | undefined
}

export interface MinimalIncomingMessage {
  method?: string
  url?: string
}

export interface MinimalServerResponse {
  writeHead(status: number, headers?: Record<string, string | number>): void
  write(chunk: string | Uint8Array): boolean
  end(chunk?: string | Uint8Array): void
  once(event: 'close' | 'error', listener: () => void): unknown
}
