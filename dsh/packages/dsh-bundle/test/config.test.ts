import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import {
  DEFAULT_CONFIG,
  loadConfig,
  resetConfigCacheForTest,
  saveConfig,
  subscribeConfig,
} from '../src/client/config.ts'

type Store = Record<string, string>

/** node 测试环境手工桩：localStorage + window 事件面（config.ts 只用这些）。 */
function installStubs(): { store: Store; listeners: Set<() => void> } {
  const store: Store = {}
  const listeners = new Set<() => void>()
  const g = globalThis as Record<string, unknown>
  g.localStorage = {
    getItem: (k: string) => (k in store ? store[k]! : null),
    setItem: (k: string, v: string) => {
      store[k] = v
    },
    removeItem: (k: string) => {
      delete store[k]
    },
    clear: () => {
      for (const k of Object.keys(store)) delete store[k]
    },
  }
  g.window = {
    addEventListener: (_type: string, fn: () => void) => {
      listeners.add(fn)
    },
    removeEventListener: (_type: string, fn: () => void) => {
      listeners.delete(fn)
    },
    dispatchEvent: () => {
      for (const fn of [...listeners]) fn()
      return true
    },
  }
  return { store, listeners }
}

describe('client config（展示偏好：localStorage + 事件同步）', () => {
  beforeEach(() => {
    installStubs()
    resetConfigCacheForTest()
  })

  afterEach(() => {
    const g = globalThis as Record<string, unknown>
    delete g.localStorage
    delete g.window
  })

  it('空存储回落默认值（svg）', () => {
    expect(loadConfig()).toEqual(DEFAULT_CONFIG)
    expect(DEFAULT_CONFIG.barsMode).toBe('svg')
  })

  it('saveConfig 持久化并能重载（缓存失效后）', () => {
    saveConfig({ barsMode: 'table' })
    resetConfigCacheForTest()
    expect(loadConfig().barsMode).toBe('table')
  })

  it('存储里的非法取值回落默认（不炸渲染）', () => {
    const g = globalThis as Record<string, unknown>
    ;(g.localStorage as { setItem(k: string, v: string): void }).setItem(
      'mommy.client.config.v1',
      JSON.stringify({ barsMode: 'hologram' }),
    )
    resetConfigCacheForTest()
    expect(loadConfig().barsMode).toBe(DEFAULT_CONFIG.barsMode)
  })

  it('损坏 JSON 回落默认', () => {
    const g = globalThis as Record<string, unknown>
    ;(g.localStorage as { setItem(k: string, v: string): void }).setItem('mommy.client.config.v1', '{oops')
    resetConfigCacheForTest()
    expect(loadConfig()).toEqual(DEFAULT_CONFIG)
  })

  it('subscribeConfig：save 触发监听，退订后不再触发', () => {
    let hits = 0
    const unsubscribe = subscribeConfig(() => {
      hits += 1
    })
    saveConfig({ barsMode: 'lwc' })
    expect(hits).toBe(1)
    unsubscribe()
    saveConfig({ barsMode: 'svg' })
    expect(hits).toBe(1)
  })
})
