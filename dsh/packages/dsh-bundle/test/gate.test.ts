import { describe, expect, it } from 'vitest'
import {
  apply,
  CONFIRM_ALWAYS,
  createGateListener,
  decideWriteGate,
  requiresConfirmation,
  writeDetail,
} from '../src/gate.ts'

const P = 'mcp__mommy-chaogu__'

describe('requiresConfirmation（Python 侧白名单同语义）', () => {
  it('strategy_* 三件套恒确认', () => {
    for (const tool of CONFIRM_ALWAYS) {
      expect(requiresConfirmation(tool, {})).toBe(true)
    }
  })
  it('manage_watchlist / manage_alert 仅 add/remove 确认', () => {
    expect(requiresConfirmation('manage_watchlist', { action: 'add', code: '600519' })).toBe(true)
    expect(requiresConfirmation('manage_watchlist', { action: 'remove', code: '600519' })).toBe(true)
    expect(requiresConfirmation('manage_watchlist', { action: 'list' })).toBe(false)
    expect(requiresConfirmation('manage_alert', { action: 'ADD' })).toBe(true)
    expect(requiresConfirmation('manage_alert', { action: 'list' })).toBe(false)
  })
  it('读工具不确认（backfill_history 写的是行情缓存而非用户数据——两个「写」概念刻意分表）', () => {
    expect(requiresConfirmation('get_quote', { code: '600519' })).toBe(false)
    expect(requiresConfirmation('backfill_history', {})).toBe(false)
  })
})

describe('decideWriteGate（waterfall 决策）', () => {
  it('mommy 写工具返回 ask，永不 allow', () => {
    const decision = decideWriteGate(`${P}strategy_save`, {})
    expect(decision).toEqual({ kind: 'ask', reason: expect.stringContaining('approval') })
  })
  it('mommy 读工具 → undefined（调用方 next()）', () => {
    expect(decideWriteGate(`${P}get_quote`, { code: '600519' })).toBeUndefined()
    expect(decideWriteGate(`${P}manage_watchlist`, { action: 'list' })).toBeUndefined()
  })
  it('非 mommy 工具不拦截（即使同名写词）', () => {
    expect(decideWriteGate('mcp__other__strategy_save', {})).toBeUndefined()
    expect(decideWriteGate('strategy_save', {})).toBeUndefined()
  })
  it('参数形状异常时保守：恒确认工具仍 ask', () => {
    expect(decideWriteGate(`${P}strategy_archive`, null)).toEqual({ kind: 'ask', reason: expect.any(String) })
  })
  it('前缀命中但不在工具面快照 → ask（fail-closed，快照漂移不静默放行）', () => {
    expect(decideWriteGate(`${P}strategy_delete`, {})).toEqual({
      kind: 'ask',
      reason: expect.stringContaining('failing closed'),
    })
  })
  it('审批理由带内容：strategy_save 显示卡标题与确认注记（用户看到「保存什么」）', () => {
    const decision = decideWriteGate(`${P}strategy_save`, {
      card: { title: '缩量回踩二十日线' },
      user_confirmed: true,
      confirmation_note: '用户看过最终卡片并要求保存',
    })
    expect(decision).toMatchObject({
      kind: 'ask',
      reason: expect.stringContaining('缩量回踩二十日线'),
    })
    expect(decision).toMatchObject({
      reason: expect.stringContaining('用户看过最终卡片并要求保存'),
    })
  })
  it('审批理由带内容：manage_watchlist add 显示代码；参数残缺退回通用理由不崩溃', () => {
    expect(decideWriteGate(`${P}manage_watchlist`, { action: 'add', code: '600519' })).toMatchObject(
      { kind: 'ask', reason: expect.stringContaining('add 600519') },
    )
    expect(writeDetail('strategy_save', null)).toBeNull()
    expect(writeDetail('strategy_save', { card: 'not-an-object' })).toBeNull()
    expect(writeDetail('manage_watchlist', {})).toBeNull()
  })
})

describe('createGateListener（next() 契约）', () => {
  it('不拦截时透传 next() 的结果，不越权 allow', async () => {
    const listener = createGateListener()
    const downstream = { kind: 'deny', reason: 'host policy' } as const
    const result = await listener({ name: `${P}get_quote`, arguments: {} }, async () => downstream)
    expect(result).toBe(downstream)
  })
  it('拦截时不再调用 next()（截断 waterfall）', async () => {
    const listener = createGateListener()
    let called = false
    const result = await listener({ name: `${P}manage_watchlist`, arguments: { action: 'add' } }, async () => {
      called = true
      return { kind: 'allow' }
    })
    expect(called).toBe(false)
    expect(result.kind).toBe('ask')
  })
  it('apply 挂监听器且 disabled 时不挂', () => {
    const registered: string[] = []
    const ctx = {
      on: (event: string, _listener: unknown) => {
        registered.push(event)
        return () => {}
      },
    }
    apply(ctx as never, { enabled: true })
    apply({ on: () => () => {} } as never, { enabled: false })
    expect(registered).toEqual(['tools/pre-execute'])
  })
})
