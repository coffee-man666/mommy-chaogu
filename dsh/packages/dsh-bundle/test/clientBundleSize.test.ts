import { existsSync, readFileSync } from 'node:fs'
import { gzipSync } from 'node:zlib'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

/**
 * client.js 体积预算：浏览器半经三段 CJS 注入宿主，每次会话加载一次，
 * 无序内联依赖会直接放大宿主首开成本。lightweight-charts 内联后
 * 基线 ~85KB gzip（table-only 时代是 16KB）；超过 90KB 的新依赖必须
 * 论证（动态 chunk 在三段包裹下不可用，只能整包内联）。
 */
const clientPath = join(import.meta.dirname, '..', 'lib', 'client.js')

describe('client bundle 体积预算', () => {
  it.skipIf(!existsSync(clientPath))('lib/client.js gzip ≤ 90KB', () => {
    const gz = gzipSync(readFileSync(clientPath)).length
    expect(gz).toBeLessThanOrEqual(90 * 1024)
  })
})
