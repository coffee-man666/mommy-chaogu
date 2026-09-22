/**
 * mommy CLI 子进程调用：node 半桥的数据面。
 *
 * CLI 是工具箱的稳定契约（`mommy watchlist list --json` / `mommy quote ...`），
 * 桥不碰 Python 内部 API、不实现 MCP 客户端协议。超时熔断 + maxBuffer 上限 +
 * 结构化错误返回，子进程崩溃不拖垮宿主路由。
 */
import { spawn } from 'node:child_process'

export interface MommyInvocation {
  command: string
  /** 基础参数（如 uv run 包装时的 ["run", "--directory", ...]）。 */
  baseArgs: string[]
}

export type RunJsonResult = { ok: true; data: unknown } | { ok: false; error: string }

export type RunJson = (args: string[], timeoutMs?: number) => Promise<RunJsonResult>

const DEFAULT_TIMEOUT_MS = 20_000
const MAX_BUFFER = 8 * 1024 * 1024

/** 造一个可注入替换的 runner（测试传 fake）。env 覆盖宿主进程环境。 */
export function createRunner(invocation: MommyInvocation, env: Record<string, string> = {}): RunJson {
  return (args, timeoutMs = DEFAULT_TIMEOUT_MS) =>
    new Promise<RunJsonResult>(resolve => {
      const child = spawn(
        invocation.command,
        [...invocation.baseArgs, ...args],
        {
          shell: false,
          stdio: ['ignore', 'pipe', 'pipe'],
          windowsHide: true,
          // 子进程继承宿主 cwd——mommy 的数据目录按 cwd 解析会指向错误位置，
          // 必须显式钉住数据目录（与 MCP 行 spec.env 绝对 DB 路径同一纪律）
          env: { ...process.env, ...env },
        },
      )
      let stdout = ''
      let stderr = ''
      let settled = false
      const finish = (result: RunJsonResult) => {
        if (settled) return
        settled = true
        clearTimeout(timer)
        resolve(result)
      }
      const timer = setTimeout(() => {
        child.kill('SIGKILL')
        finish({ ok: false, error: `mommy command timed out after ${timeoutMs}ms: ${invocation.command} ${args.join(' ')}` })
      }, timeoutMs)
      child.stdout.on('data', (chunk: Buffer) => {
        if (stdout.length < MAX_BUFFER) stdout += chunk.toString('utf8')
      })
      child.stderr.on('data', (chunk: Buffer) => {
        if (stderr.length < MAX_BUFFER) stderr += chunk.toString('utf8')
      })
      child.on('error', error => finish({ ok: false, error: `failed to spawn ${invocation.command}: ${String(error)}` }))
      child.on('close', code => {
        if (code !== 0) {
          finish({ ok: false, error: `mommy command exited with ${code}: ${stderr.trim() || stdout.trim().slice(0, 400)}` })
          return
        }
        try {
          finish({ ok: true, data: JSON.parse(stdout) })
        } catch {
          finish({ ok: false, error: `mommy command output is not valid JSON: ${stdout.trim().slice(0, 200)}` })
        }
      })
    })
}
