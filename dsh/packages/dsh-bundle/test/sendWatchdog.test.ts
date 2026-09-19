import { describe, expect, it } from 'vitest'
import {
  createSendWatchdogCore,
  isUnaryRpcRequest,
  STUCK_AFTER_MS,
  type SendWatchdogCore,
} from '../src/client/sendWatchdog.ts'

const ENVELOPE_BODY = '{"type":"client-request","rpcId":"r1","method":"session/prompt","payload":{}}'

/** 手工定时器桩：schedule 记录计时器，fire 手动触发，canceled 后不再执行。 */
function manualScheduler() {
  const timers: Array<{ fn: () => void; ms: number; canceled: boolean }> = []
  return {
    timers,
    schedule(fn: () => void, ms: number) {
      const t = { fn, ms, canceled: false }
      timers.push(t)
      return () => {
        t.canceled = true
      }
    },
    fire(index: number) {
      const t = timers[index]
      if (t !== undefined && !t.canceled) t.fn()
    },
  }
}

/** 组装被测核心，收集 onStuckChange 序列。 */
function buildCore(scheduler = manualScheduler()): {
  core: SendWatchdogCore
  changes: number[]
  fire: (index: number) => void
  timers: ReturnType<typeof manualScheduler>['timers']
} {
  const changes: number[] = []
  const core = createSendWatchdogCore({
    stuckAfterMs: STUCK_AFTER_MS,
    schedule: scheduler.schedule,
    onStuckChange: (n) => {
      changes.push(n)
    },
  })
  return { core, changes, fire: scheduler.fire, timers: scheduler.timers }
}

describe('isUnaryRpcRequest（信封判定：零误报优先）', () => {
  it('POST + client-request 信封 → 命中', () => {
    expect(isUnaryRpcRequest(new URL('http://h/api/session/prompt'), { method: 'POST', body: ENVELOPE_BODY })).toBe(true)
  })

  it('method 大小写不敏感', () => {
    expect(isUnaryRpcRequest('http://h/api/session/prompt', { method: 'post', body: ENVELOPE_BODY })).toBe(true)
  })

  it('GET / 非信封体 / 空体 / 缺 init → 一律不命中', () => {
    expect(isUnaryRpcRequest('http://h/api/session/prompt', { method: 'GET', body: ENVELOPE_BODY })).toBe(false)
    expect(isUnaryRpcRequest('http://h/api/upload', { method: 'POST', body: '{"other":1}' })).toBe(false)
    expect(isUnaryRpcRequest('http://h/api/session/prompt', { method: 'POST' })).toBe(false)
    expect(isUnaryRpcRequest('http://h/api/session/prompt')).toBe(false)
  })

  it('method 缺省但不否决（信封前缀本身足够精确）', () => {
    expect(isUnaryRpcRequest('http://h/api/session/prompt', { body: ENVELOPE_BODY })).toBe(true)
  })

  it('Request 对象（body 为流）自然排除', () => {
    const req = new Request('http://h/api/session/prompt', { method: 'POST', body: ENVELOPE_BODY })
    expect(isUnaryRpcRequest(req)).toBe(false)
  })
})

describe('sendWatchdog 核心（登记 / 静默判死 / 结算回收）', () => {
  it('非 RPC 请求不登记：无计时器、无结算钩子', () => {
    const { core, timers } = buildCore()
    expect(core.observe('http://h/api/x', { method: 'POST', body: '{"other":1}' })).toBeUndefined()
    expect(timers).toHaveLength(0)
  })

  it('结算先于阈值：计时器取消、不判死', () => {
    const { core, changes, fire, timers } = buildCore()
    const settle = core.observe(new URL('http://h/api/session/prompt'), { method: 'POST', body: ENVELOPE_BODY })
    expect(settle).toBeTypeOf('function')
    expect(timers).toHaveLength(1)
    expect(timers[0]!.ms).toBe(STUCK_AFTER_MS)
    settle!()
    fire(0)
    expect(core.stuckCount).toBe(0)
    expect(changes).toEqual([])
  })

  it('静默超过阈值：判死 +1 并通知；随后结算回收归零', () => {
    const { core, changes, fire } = buildCore()
    const settle = core.observe(new URL('http://h/api/session/prompt'), { method: 'POST', body: ENVELOPE_BODY })
    fire(0)
    expect(core.stuckCount).toBe(1)
    expect(changes).toEqual([1])
    settle!()
    expect(core.stuckCount).toBe(0)
    expect(changes).toEqual([1, 0])
  })

  it('并发多请求：部分结算时剩余保持判死计数', () => {
    const { core, changes, fire } = buildCore()
    const a = core.observe(new URL('http://h/api/session/prompt'), { method: 'POST', body: ENVELOPE_BODY })
    core.observe(new URL('http://h/api/session/create'), { method: 'POST', body: ENVELOPE_BODY })
    fire(0) // 只有第一个到点判死
    expect(core.stuckCount).toBe(1)
    a!()
    expect(core.stuckCount).toBe(0)
    expect(changes).toEqual([1, 0])
  })

  it('已判死请求迟到结算：横幅面可收敛（不误报到底）', () => {
    const { core, changes, fire } = buildCore()
    const a = core.observe(new URL('http://h/api/session/prompt'), { method: 'POST', body: ENVELOPE_BODY })
    const b = core.observe(new URL('http://h/api/session/create'), { method: 'POST', body: ENVELOPE_BODY })
    fire(0)
    fire(1)
    expect(core.stuckCount).toBe(2)
    a!()
    b!()
    expect(core.stuckCount).toBe(0)
    expect(changes).toEqual([1, 2, 1, 0])
  })
})
