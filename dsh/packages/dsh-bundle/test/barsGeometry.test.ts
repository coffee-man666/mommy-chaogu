import { describe, expect, it } from 'vitest'
import {
  candleGeom,
  candleWidthOf,
  maSegments,
  priceDigits,
  priceExtent,
  priceTicks,
  xOf,
  yOf,
  type ChartBox,
} from '../src/client/barsGeometry.ts'
import type { BarView } from '../src/client/parse.ts'

function bar(o: number, h: number, l: number, c: number, ma: Record<string, number | null> = {}): BarView {
  return { timestamp: `2026-09-17T13:30:00+00:00`, open: o, high: h, low: l, close: c, volume: 1000, changePct: null, ma }
}

const BOX: ChartBox = { width: 400, height: 200, padLeft: 4, padRight: 46, padTop: 8, padBottom: 16 }

describe('priceExtent（覆盖蜡烛与均线，4% 呼吸）', () => {
  it('覆盖 low/high 与非空均线值', () => {
    const bars = [bar(10, 12, 9, 11, { '5': 8.5 }), bar(11, 13, 10.5, 12.5, { '5': 13.2 })]
    const e = priceExtent(bars, ['5'])
    expect(e.min).toBeLessThan(8.5)
    expect(e.max).toBeGreaterThan(13.2)
  })

  it('null 均线值不参与范围', () => {
    const bars = [bar(10, 12, 9, 11, { '20': null })]
    const e = priceExtent(bars, ['20'])
    expect(e.min).toBeLessThan(9)
    expect(e.max).toBeGreaterThan(12)
  })

  it('单一价格防除零', () => {
    const e = priceExtent([bar(5, 5, 5, 5, {})], [])
    expect(e.max).toBeGreaterThan(e.min)
  })
})

describe('坐标映射（数字 → 像素，纯函数）', () => {
  it('xOf 随索引单调递增且落在留白内', () => {
    const a = xOf(0, 5, BOX)
    const b = xOf(4, 5, BOX)
    expect(b).toBeGreaterThan(a)
    expect(a).toBeGreaterThanOrEqual(BOX.padLeft)
    expect(b).toBeLessThanOrEqual(BOX.width - BOX.padRight)
  })

  it('yOf：高价在上（y 小），低价在下（y 大）', () => {
    const e = priceExtent([bar(10, 20, 0, 15, {})], [])
    expect(yOf(20, e, BOX)).toBeLessThan(yOf(0, e, BOX))
  })

  it('candleWidthOf 夹在 [1, 13]', () => {
    expect(candleWidthOf(3, BOX)).toBeLessThanOrEqual(13)
    expect(candleWidthOf(500, { ...BOX, width: 100 })).toBeGreaterThanOrEqual(1)
  })

  it('candleGeom：收 ≥ 开 为涨（红），实体顶=开低、底=高低', () => {
    const e = priceExtent([bar(10, 15, 8, 14, {})], [])
    const g = candleGeom(bar(10, 15, 8, 14, {}), 0, 1, e, BOX)
    expect(g.up).toBe(true)
    expect(g.bodyTop).toBeCloseTo(yOf(14, e, BOX), 6)
    expect(g.bodyBottom).toBeCloseTo(yOf(10, e, BOX), 6)
    expect(g.wickTop).toBeCloseTo(yOf(15, e, BOX), 6)
    expect(g.wickBottom).toBeCloseTo(yOf(8, e, BOX), 6)
    const bear = candleGeom(bar(14, 15, 8, 9, {}), 0, 1, e, BOX)
    expect(bear.up).toBe(false)
  })
})

describe('maSegments（null 断段，不填补）', () => {
  it('前导 null + 中段空洞 → 两段', () => {
    const bars = [
      bar(1, 1, 1, 1, { '5': null }),
      bar(1, 1, 1, 1, { '5': 10 }),
      bar(1, 1, 1, 1, { '5': 11 }),
      bar(1, 1, 1, 1, { '5': null }),
      bar(1, 1, 1, 1, { '5': 12 }),
    ]
    const e = priceExtent(bars, ['5'])
    const segments = maSegments(bars, '5', e, BOX)
    expect(segments).toHaveLength(2)
    expect(segments[0]).toHaveLength(2)
    expect(segments[1]).toHaveLength(1)
  })

  it('全 null → 无折线', () => {
    const bars = [bar(1, 1, 1, 1, { '50': null })]
    expect(maSegments(bars, '50', priceExtent(bars, ['50']), BOX)).toHaveLength(0)
  })
})

describe('priceTicks / priceDigits', () => {
  it('刻度落在范围内且步长整齐', () => {
    const e = priceExtent([bar(100, 200, 100, 150, {})], [])
    const ticks = priceTicks(e, 4)
    expect(ticks.length).toBeGreaterThan(0)
    for (const t of ticks) {
      expect(t).toBeGreaterThanOrEqual(e.min)
      expect(t).toBeLessThanOrEqual(e.max)
    }
    const diffs = ticks.slice(1).map((t, i) => t - ticks[i]!)
    expect(new Set(diffs.map(d => d.toFixed(6))).size).toBe(1)
  })

  it('精度随量级收敛', () => {
    expect(priceDigits(26418.3)).toBe(0)
    expect(priceDigits(561.47)).toBe(1)
    expect(priceDigits(9.145)).toBe(2)
  })
})
