/**
 * 自绘迷你 K 线的纯几何映射：服务端数值 → SVG 坐标。
 *
 * 纪律：本模块只做「数字 → 像素」的映射，不含任何指标计算——均线值一律
 * 取服务端 get_bars include_ma 附带的 ma_<w> 字段（parse.ts 已解析），这里
 * 只负责把 null 断开的段拼成折线。全部函数无副作用、无 DOM 依赖，可独立
 * 单测。
 */
import type { BarView } from './parse.ts'

export interface Extent {
  min: number
  max: number
}

export interface Point {
  x: number
  y: number
}

export interface CandleGeom {
  /** 蜡烛中心 x。 */
  x: number
  bodyTop: number
  bodyBottom: number
  wickTop: number
  wickBottom: number
  /** 收 ≥ 开（A股红涨）。 */
  up: boolean
}

export interface ChartBox {
  width: number
  height: number
  /** 左右留白（右侧留给价格轴标签）。 */
  padLeft: number
  padRight: number
  padTop: number
  padBottom: number
}

/** 价格范围：覆盖 low/high 与参与渲染的均线值，上下各留 4% 呼吸空间。 */
export function priceExtent(bars: BarView[], maWindows: readonly string[]): Extent {
  let min = Number.POSITIVE_INFINITY
  let max = Number.NEGATIVE_INFINITY
  for (const bar of bars) {
    if (bar.low < min) min = bar.low
    if (bar.high > max) max = bar.high
    for (const w of maWindows) {
      const v = bar.ma[w]
      if (v !== null && v !== undefined) {
        if (v < min) min = v
        if (v > max) max = v
      }
    }
  }
  if (!Number.isFinite(min) || !Number.isFinite(max)) return { min: 0, max: 1 }
  if (min === max) {
    min -= 1
    max += 1
  }
  const pad = (max - min) * 0.04
  return { min: min - pad, max: max + pad }
}

export function xOf(index: number, count: number, box: ChartBox): number {
  const inner = box.width - box.padLeft - box.padRight
  const slot = inner / Math.max(count, 1)
  return box.padLeft + slot * (index + 0.5)
}

export function candleWidthOf(count: number, box: ChartBox): number {
  const inner = box.width - box.padLeft - box.padRight
  const slot = inner / Math.max(count, 1)
  return Math.max(Math.min(slot * 0.7, 13), 1)
}

export function yOf(price: number, extent: Extent, box: ChartBox): number {
  const inner = box.height - box.padTop - box.padBottom
  const ratio = (price - extent.min) / (extent.max - extent.min)
  return box.padTop + inner * (1 - ratio)
}

export function candleGeom(bar: BarView, index: number, count: number, extent: Extent, box: ChartBox): CandleGeom {
  const x = xOf(index, count, box)
  const bodyTop = yOf(Math.max(bar.open, bar.close), extent, box)
  const bodyBottom = yOf(Math.min(bar.open, bar.close), extent, box)
  return {
    x,
    bodyTop,
    bodyBottom,
    wickTop: yOf(bar.high, extent, box),
    wickBottom: yOf(bar.low, extent, box),
    up: bar.close >= bar.open,
  }
}

/**
 * 均线折线段：服务端值 null 的窗口前导/空洞处断开（不做填补——填补即是
 * 在浏览器侧发明数据）。返回若干段，每段内 x 递增。
 */
export function maSegments(
  bars: BarView[],
  windowKey: string,
  extent: Extent,
  box: ChartBox,
): Point[][] {
  const segments: Point[][] = []
  let current: Point[] | null = null
  bars.forEach((bar, index) => {
    const v = bar.ma[windowKey]
    if (v === null || v === undefined) {
      current = null
      return
    }
    const point = { x: xOf(index, bars.length, box), y: yOf(v, extent, box) }
    if (current === null) {
      current = [point]
      segments.push(current)
    } else {
      current.push(point)
    }
  })
  return segments
}

/** 网格刻度：在价格范围内取 count 个整值刻度（含边界 rounded）。 */
export function priceTicks(extent: Extent, count: number): number[] {
  if (!(extent.max > extent.min) || count < 2) return []
  const rawStep = (extent.max - extent.min) / (count - 1)
  const mag = 10 ** Math.floor(Math.log10(rawStep))
  const normalized = rawStep / mag
  const step = (normalized >= 5 ? 10 : normalized >= 2 ? 5 : normalized >= 1 ? 2 : 1) * mag
  const first = Math.ceil(extent.min / step) * step
  const ticks: number[] = []
  for (let v = first; v <= extent.max; v += step) {
    ticks.push(Number(v.toFixed(6)))
  }
  return ticks
}

/** 轴/提示里的价格显示精度：按价格量级自适应（≥1000 取 0 位，≥10 取 1 位，其余 2 位）。 */
export function priceDigits(price: number): number {
  const abs = Math.abs(price)
  if (abs >= 1000) return 0
  if (abs >= 10) return 1
  return 2
}
