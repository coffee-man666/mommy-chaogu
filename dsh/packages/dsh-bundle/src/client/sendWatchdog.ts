/**
 * 发送链路看门狗（纯 UX 安全网，嫁接面 4 的附加检测）。
 *
 * 背景（0.1.5-rc.2 实测 + 源码核实）：DSH 客户端一元 RPC（POST
 * `{origin}/api/<channel>/<endpoint>`，请求体以 {"type":"client-request"}
 * 开头）没有任何 deadline；session.prompt 的用户气泡是宿主对象层的本地
 * echo（beginSubmission 同步入快照），只有 RPC 结算或宿主观测事件才能
 * 使其退场。传输层挂起时（本地代理吞请求、休眠唤醒、连接半开）三重静默：
 * 气泡永不退场、promptError 横幅永不出现、宿主零痕迹——用户视角即
 * “AI 不回我了”（2026-09-17 GUI 测试复现两次，详见
 * gui-test-screenshots/20260917-ashare-semi/REPORT.md）。
 *
 * 宿主源码不可改（嫁接纪律），故在 bundle 客户端做最小检测：包装
 * fetch，按 RPC 信封精确识别一元请求，30s 无响应即展示可操作的提醒
 * 横幅。不 abort——零干扰；请求迟到的响应照常结算并自动撤横幅。若
 * 宿主其实已受理（仅响应丢失），回合会经事件流正常展开，横幅文案
 * 提示用户此时忽略即可。
 *
 * 横幅文案不走 locale NS：紧急面必须在 locale 服务本身异常时仍然
 * 可渲染，故内联中英双语。
 */

/** DSH 一元 RPC 信封前缀（createWebConnectionRpc 固定序列化形状）。 */
const RPC_ENVELOPE_PREFIX = '{"type":"client-request"'

/** 一元 RPC 静默判定阈值：本地产应用 30s 无任何响应即视为链路异常。 */
export const STUCK_AFTER_MS = 30_000

export interface SendWatchdogCore {
  /**
   * 判定一次 fetch 调用是否属于一元 RPC；是则登记静默计时并返回结算
   * 钩子（调用方必须在请求结算时调用恰好一次，无论成败），否则返回
   * undefined 表示与本看门狗无关。
   */
  observe(input: unknown, init?: RequestInit | undefined): (() => void) | undefined
  /** 当前“已判死但未结算”的请求数（>0 时应展示横幅）。 */
  readonly stuckCount: number
}

/**
 * 看门狗核心（纯逻辑，DOM 无关，可注入计时器做单元测试）。
 * @param opts.schedule 可取消定时器；onStuckChange 在 stuckCount 变化时
 *   同步回调（含 0→N 与 N→0 两个方向）。
 */
export function createSendWatchdogCore(opts: {
  stuckAfterMs: number
  schedule(fn: () => void, ms: number): () => void
  onStuckChange(stuckCount: number): void
}): SendWatchdogCore {
  let stuck = 0
  const notify = () => opts.onStuckChange(stuck)
  return {
    get stuckCount() {
      return stuck
    },
    observe(input, init) {
      if (!isUnaryRpcRequest(input, init)) return undefined
      let flagged = false
      const cancelTimer = opts.schedule(() => {
        flagged = true
        stuck += 1
        notify()
      }, opts.stuckAfterMs)
      return () => {
        cancelTimer()
        if (flagged) {
          stuck -= 1
          notify()
        }
      }
    },
  }
}

/**
 * 信封判定：只认“能直接检视的字符串请求体 + 一元 RPC 信封前缀”。
 * method 缺省时不否决（信封前缀本身已足够精确）；Request 对象的 body
 * 是流、文件上传是 multipart/binary，均自然排除——零误报优先。
 */
export function isUnaryRpcRequest(input: unknown, init?: RequestInit | undefined): boolean {
  if (typeof init !== 'object' || init === null) return false
  const method = (init as RequestInit | undefined)?.method
  if (typeof method === 'string' && method.toUpperCase() !== 'POST') return false
  const body = (init as RequestInit | undefined)?.body
  return typeof body === 'string' && body.startsWith(RPC_ENVELOPE_PREFIX)
}

interface BannerFace {
  show(): void
  hide(): void
}

function ensureBanner(): BannerFace | undefined {
  if (typeof document === 'undefined') return undefined
  let root = document.getElementById('mommy-chaogu-send-watchdog') as HTMLDivElement | null
  if (root === null) {
    root = document.createElement('div')
    root.id = 'mommy-chaogu-send-watchdog'
    root.setAttribute('role', 'alert')
    Object.assign(root.style, {
      position: 'fixed',
      top: '12px',
      left: '50%',
      transform: 'translateX(-50%)',
      zIndex: '2147483000',
      display: 'none',
      alignItems: 'center',
      gap: '10px',
      maxWidth: '560px',
      padding: '10px 14px',
      background: '#1f2937',
      color: '#f9fafb',
      fontSize: '13px',
      lineHeight: '1.5',
      borderRadius: '10px',
      boxShadow: '0 8px 24px rgba(0,0,0,.35)',
    } satisfies Partial<CSSStyleDeclaration>)
    const text = document.createElement('div')
    text.textContent =
      '检测到与宿主的请求长时间无响应：刚发送的消息可能没有送达。若回复尚未开始，请刷新页面后重发。' +
      ' Request unanswered — your last message may not have been delivered; if no reply has started, reload and resend.'
    const reload = document.createElement('button')
    reload.type = 'button'
    reload.textContent = '刷新页面 Reload'
    Object.assign(reload.style, {
      flexShrink: '0',
      padding: '4px 10px',
      borderRadius: '6px',
      border: '1px solid rgba(255,255,255,.4)',
      background: 'transparent',
      color: '#f9fafb',
      fontSize: '12px',
      cursor: 'pointer',
    } satisfies Partial<CSSStyleDeclaration>)
    reload.addEventListener('click', () => {
      location.reload()
    })
    root.append(text, reload)
    document.body.appendChild(root)
  }
  const el = root
  return {
    show() {
      el.style.display = 'flex'
    },
    hide() {
      el.style.display = 'none'
    },
  }
}

let installed = false

/**
 * 包装全局 fetch 并启用看门狗。幂等（重复安装直接忽略）；原 fetch 的
 * 参数、返回值与异常语义原样透传，仅对匹配请求附加观察分支（ detached
 * then，不改变应用侧拿到的 promise）。DSH 连接层每次调用都读当前
 * globalThis.fetch，boot 时安装即可覆盖其全部一元 RPC。
 */
export function installSendWatchdog(): void {
  if (installed) return
  installed = true
  const banner = ensureBanner()
  const core = createSendWatchdogCore({
    stuckAfterMs: STUCK_AFTER_MS,
    schedule: (fn, ms) => {
      const t = setTimeout(fn, ms)
      return () => clearTimeout(t)
    },
    onStuckChange: (count) => {
      if (count > 0) {
        console.warn(`[mommy-chaogu] send watchdog: ${count} unary RPC(s) unanswered for ${STUCK_AFTER_MS}ms`)
        banner?.show()
      } else {
        banner?.hide()
      }
    },
  })
  const original = globalThis.fetch.bind(globalThis)
  const watchdogged: typeof fetch = (input, init) => {
    const settle = core.observe(input, init)
    let promise: Promise<Response>
    try {
      promise = original(input, init)
    } catch (error) {
      // 同步抛出（参数非法等）也必须结算，否则 30s 后必然误报。
      settle?.()
      throw error
    }
    // detached 分支：只做结算，不改应用侧拿到的 promise 语义。
    if (settle !== undefined) promise.then(settle, settle)
    return promise
  }
  globalThis.fetch = watchdogged
}
