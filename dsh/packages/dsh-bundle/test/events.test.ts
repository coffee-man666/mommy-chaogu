/**
 * RevisionBus 的 WAL 盲区回归：mommy 的库全部跑 WAL 模式，长驻写者（MCP
 * server）的提交先落 portfolio.db-wal，checkpoint 前主文件 mtime 不动。
 * 曾经只 stat 主文件——AI 写完自选股，dock 收不到失效信号。
 *
 * 用 utimes 钉死 mtime（写入两次的 mtimeMs 可能同毫秒，不可靠）；真定时器
 * + 短轮询间隔（fs stat 走真实线程池，fake timers 等不到它）。
 */
import { mkdirSync, utimesSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

import { RevisionBus } from '../src/events.ts'

const POLL_MS = 5

function sleep(ms: number): Promise<void> {
  return new Promise(resolve => {
    setTimeout(resolve, ms)
  })
}

function makeDataDir(seed: string): string {
  const dir = join(tmpdir(), `mommy-events-${seed}-${Date.now()}-${Math.random().toString(36).slice(2)}`)
  mkdirSync(dir, { recursive: true })
  return dir
}

function createFile(path: string, mtimeMs: number): void {
  writeFileSync(path, 'x')
  const t = new Date(mtimeMs)
  utimesSync(path, t, t)
}

describe('RevisionBus（WAL 盲区回归）', () => {
  it('主文件 mtime 不动、只写 -wal 也要发失效信号', async () => {
    const dir = makeDataDir('wal')
    const db = join(dir, 'portfolio.db')
    createFile(db, 1_700_000_000_000)
    const bus = new RevisionBus(dir, POLL_MS)
    const revisions: number[] = []
    bus.subscribe(event => revisions.push(event.revision))
    bus.start()
    try {
      await sleep(POLL_MS * 3) // 基线 poll（emit=false）
      expect(revisions).toEqual([])

      createFile(join(dir, 'portfolio.db-wal'), 1_700_000_001_000) // 主文件不动
      await sleep(POLL_MS * 3)
      expect(revisions).toEqual([1])
    } finally {
      bus.stop()
    }
  })

  it('无变化不误发，启动基线本身不触发', async () => {
    const dir = makeDataDir('quiet')
    createFile(join(dir, 'portfolio.db'), 1_700_000_000_000)
    const bus = new RevisionBus(dir, POLL_MS)
    const revisions: number[] = []
    bus.subscribe(event => revisions.push(event.revision))
    bus.start()
    try {
      await sleep(POLL_MS * 6)
      expect(revisions).toEqual([])
    } finally {
      bus.stop()
    }
  })

  it('库不存在时启动不炸、建库即发首个信号', async () => {
    const dir = makeDataDir('create')
    const bus = new RevisionBus(dir, POLL_MS)
    const revisions: number[] = []
    bus.subscribe(event => revisions.push(event.revision))
    bus.start()
    try {
      await sleep(POLL_MS * 3)
      expect(revisions).toEqual([])
      createFile(join(dir, 'portfolio.db'), 1_700_000_002_000)
      await sleep(POLL_MS * 3)
      expect(revisions).toEqual([1])
    } finally {
      bus.stop()
    }
  })
})
