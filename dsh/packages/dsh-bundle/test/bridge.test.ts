import { mkdtemp, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { API_PREFIX, createMommyRoutes, parseCodes } from '../src/bridge.ts'
import { RevisionBus } from '../src/events.ts'
import type { RunJson } from '../src/spawn.ts'
import type { MinimalIncomingMessage, MinimalServerResponse } from '../src/types.ts'

interface FakeRes {
  status: number
  headers: Record<string, string | number>
  chunks: string[]
  closed: false
}

function makeRes(): { res: FakeRes & MinimalServerResponse; raw: FakeRes } {
  const raw: FakeRes = { status: 0, headers: {}, chunks: [], closed: false }
  const res = raw as unknown as FakeRes & MinimalServerResponse
  res.writeHead = (status: number, headers?: Record<string, string | number>) => {
    raw.status = status
    raw.headers = headers ?? {}
  }
  res.write = (chunk: string) => {
    raw.chunks.push(chunk)
    return true
  }
  res.end = (chunk?: string) => {
    if (chunk !== undefined) raw.chunks.push(chunk)
  }
  res.once = () => raw
  return { res, raw }
}

function makeBridge(runJson: RunJson, rejection: (req: MinimalIncomingMessage) => number | undefined) {
  return createMommyRoutes({
    runJson,
    events: new RevisionBus('/nonexistent', 60_000),
    connection: { requestRejection: rejection },
  })
}

const route = (routes: ReturnType<typeof createMommyRoutes>, path: string) => {
  const found = routes.find(r => r.path === path)
  if (found === undefined) throw new Error(`missing route: ${path}`)
  return found.handler
}

describe('parseCodes（?codes= 词法与上限）', () => {
  it('合法代码去重保序', () => {
    expect(parseCodes('600519,AAPL,^GSPC,600519')).toEqual({ ok: true, codes: ['600519', 'AAPL', '^GSPC'] })
  })
  it('非法词法 / 超限 / 空值拒绝', () => {
    expect(parseCodes('60051x').ok).toBe(false)
    expect(parseCodes('rm -rf').ok).toBe(false)
    // 上限按去重后的独立代码数计（重复发同一只不算滥用）
    const dupes = Array.from({ length: 51 }, () => '600519').join(',')
    expect(parseCodes(dupes).ok).toBe(true)
    const distinct = Array.from({ length: 51 }, (_, i) => String(600000 + i)).join(',')
    expect(parseCodes(distinct).ok).toBe(false)
    expect(parseCodes(null).ok).toBe(false)
    expect(parseCodes(' , ').ok).toBe(false)
  })
})

describe('/mommy/api 路由（认证栅栏 + no-store + 子进程数据面）', () => {
  const okRun: RunJson = async args => {
    if (args[0] === 'watchlist') return { ok: true, data: [{ code: '600519', name: '贵州茅台', group: '白酒', note: null }] }
    return { ok: true, data: { source: 'tencent', quotes: [{ code: '600519', price: 1 }] } }
  }

  it('watchlist 200 + no-store + 透传 JSON', async () => {
    const routes = makeBridge(okRun, () => undefined)
    const { res, raw } = makeRes()
    await route(routes, `${API_PREFIX}/watchlist`)({ method: 'GET', url: `${API_PREFIX}/watchlist` }, res)
    expect(raw.status).toBe(200)
    expect(raw.headers['cache-control']).toBe('no-store')
    expect(JSON.parse(raw.chunks.join(''))[0]?.code).toBe('600519')
  })

  it('quotes：合法 codes 传给 mommy quote，非法 400', async () => {
    const routes = makeBridge(okRun, () => undefined)
    const { res, raw } = makeRes()
    await route(routes, `${API_PREFIX}/quotes`)({ method: 'GET', url: `${API_PREFIX}/quotes?codes=600519,000001` }, res)
    expect(raw.status).toBe(200)
    const bad = makeRes()
    await route(routes, `${API_PREFIX}/quotes`)({ method: 'GET', url: `${API_PREFIX}/quotes?codes=oops` }, bad.res)
    expect(bad.raw.status).toBe(400)
  })

  it('认证栅栏：requestRejection 返回状态码即拒（401/403）', async () => {
    const routes = makeBridge(okRun, () => 401)
    const { res, raw } = makeRes()
    await route(routes, `${API_PREFIX}/watchlist`)({ method: 'GET', url: `${API_PREFIX}/watchlist` }, res)
    expect(raw.status).toBe(401)
    expect(raw.chunks.join('')).toContain('unauthorized')
  })

  it('mommy 子进程失败 → 502 结构化错误（不炸宿主）', async () => {
    const routes = makeBridge(async () => ({ ok: false, error: 'exit 1' }), () => undefined)
    const { res, raw } = makeRes()
    await route(routes, `${API_PREFIX}/watchlist`)({ method: 'GET', url: `${API_PREFIX}/watchlist` }, res)
    expect(raw.status).toBe(502)
    expect(JSON.parse(raw.chunks.join('')).error).toContain('exit 1')
  })

  it('events：SSE 头 + 立即注释帧', async () => {
    const routes = makeBridge(okRun, () => undefined)
    const { res, raw } = makeRes()
    route(routes, `${API_PREFIX}/events`)({ method: 'GET', url: `${API_PREFIX}/events` }, res)
    expect(raw.status).toBe(200)
    expect(raw.headers['content-type']).toContain('text/event-stream')
    expect(raw.headers['x-accel-buffering']).toBe('no')
    expect(raw.chunks[0]).toBe(': connected\n\n')
  })
})

describe('RevisionBus（mtime 失效信号）', () => {
  it('portfolio.db mtime 变化 → {store:"portfolio", revision} 自增扇出；基线轮询不误发', async () => {
    const dir = await mkdtemp(join(tmpdir(), 'mommy-bus-'))
    try {
      await writeFile(join(dir, 'portfolio.db'), 'v1')
      const bus = new RevisionBus(dir, 60_000)
      const events: Array<{ store: string; revision: number }> = []
      const unsubscribe = bus.subscribe(event => events.push(event))
      const poll = (bus as unknown as { poll: (emit: boolean) => Promise<void> }).poll.bind(bus)
      await poll(false) // 基线：不误发
      expect(events).toEqual([])
      await new Promise(resolve => setTimeout(resolve, 5))
      await writeFile(join(dir, 'portfolio.db'), 'v2') // 写入（mtime 变化）
      await new Promise(resolve => setTimeout(resolve, 5))
      await poll(true)
      expect(events).toEqual([{ store: 'portfolio', revision: 1 }])
      await poll(true) // 无变化不再发
      expect(events).toHaveLength(1)
      unsubscribe()
    } finally {
      await rm(dir, { recursive: true, force: true })
    }
  })

  it('db 不存在时静默降级为零信号', async () => {
    const bus = new RevisionBus('/nonexistent', 60_000)
    const poll = (bus as unknown as { poll: (emit: boolean) => Promise<void> }).poll.bind(bus)
    await expect(poll(true)).resolves.toBeUndefined()
  })
})
