/**
 * get_bars 卡片·自绘迷你 K 线（SVG）：蜡烛 + 影线 + 服务端均线折线。
 *
 * 零依赖纯渲染：坐标全部来自 barsGeometry.ts 的映射，颜色走 tokens.css 的
 * A 股语义变量（涨红跌绿），深浅色主题自动跟随。悬停提示用 SVG 原生
 * <title>（零 JS 交互即满足速览需求）。数据量级 get_bars ≤120 根，全量
 * 渲染无压力。
 */
import { useCallback, useRef, useState } from 'react'
import type { BarView } from './parse.ts'
import {
  candleGeom,
  candleWidthOf,
  maSegments,
  priceDigits,
  priceExtent,
  priceTicks,
  type ChartBox,
} from './barsGeometry.ts'

/** 均线配色（区分度优先，与涨跌语义色无冲突）。 */
const MA_COLORS: Record<string, string> = { '5': '#f59e0b', '20': '#3b82f6', '50': '#a855f7' }
const MA_FALLBACK = '#8b8b8b'

const HEIGHT = 190
const BOX: Omit<ChartBox, 'width'> = { height: HEIGHT, padLeft: 4, padRight: 46, padTop: 8, padBottom: 16 }

function maColor(windowKey: string): string {
  return MA_COLORS[windowKey] ?? MA_FALLBACK
}

/** 容器实测宽度（chat 卡片宽度不固定，且 slot 包装层变化不重挂载）。
 * 回调 ref（@types/react 18 的 RefObject<T> 不含 null，与 useRef 初值冲突，
 * dock.tsx 同款解法）；observer 存 ref，卸载时经 null 回调断开。 */
function useContainerWidth(fallback: number): [(el: HTMLDivElement | null) => void, number] {
  const [width, setWidth] = useState(fallback)
  const observerRef = useRef<ResizeObserver | null>(null)
  const attach = useCallback((el: HTMLDivElement | null) => {
    observerRef.current?.disconnect()
    observerRef.current = null
    if (el === null) return
    const update = () => setWidth(Math.max(el.clientWidth, 120))
    update()
    const observer = new ResizeObserver(update)
    observer.observe(el)
    observerRef.current = observer
  }, [])
  return [attach, width]
}

export function BarsSvgChart(props: { bars: BarView[]; maWindows: string[] }) {
  const { bars, maWindows } = props
  const [wrapRef, width] = useContainerWidth(560)
  if (bars.length === 0) return null

  const box: ChartBox = { ...BOX, width }
  const extent = priceExtent(bars, maWindows)
  const candleW = candleWidthOf(bars.length, box)
  const ticks = priceTicks(extent, 4)
  const digits = priceDigits(bars[bars.length - 1]!.close)
  const fmt = (v: number) => v.toFixed(digits)

  return (
    <div className="mommy-bars-chart" ref={wrapRef} style={{ width: '100%' }}>
      <svg width={width} height={HEIGHT} role="img" aria-label="K line chart" style={{ display: 'block' }}>
        {ticks.map(tick => {
          const y = (() => {
            const inner = box.height - box.padTop - box.padBottom
            const ratio = (tick - extent.min) / (extent.max - extent.min)
            return box.padTop + inner * (1 - ratio)
          })()
          return (
            <g key={`tick-${tick}`}>
              <line
                x1={box.padLeft}
                x2={width - box.padRight}
                y1={y}
                y2={y}
                stroke="var(--mommy-card-border)"
                strokeWidth={1}
                strokeDasharray="2 4"
              />
              <text
                x={width - box.padRight + 4}
                y={y + 3}
                fontSize={10}
                fill="var(--mommy-text-dim)"
                fontFamily="var(--mommy-font-num)"
              >
                {fmt(tick)}
              </text>
            </g>
          )
        })}
        {bars.map((bar, index) => {
          const g = candleGeom(bar, index, bars.length, extent, box)
          const color = g.up
            ? 'var(--mommy-up)'
            : bar.close < bar.open
              ? 'var(--mommy-down)'
              : 'var(--mommy-flat)'
          const bodyH = Math.max(g.bodyBottom - g.bodyTop, 1)
          const date = bar.timestamp.slice(0, 10)
          const chg = bar.changePct
          const title = `${date} 开 ${fmt(bar.open)} · 高 ${fmt(bar.high)} · 低 ${fmt(bar.low)} · 收 ${fmt(bar.close)}${
            chg !== null && chg !== undefined ? ` · ${chg > 0 ? '+' : ''}${chg.toFixed(2)}%` : ''
          }`
          return (
            <g key={bar.timestamp}>
              <title>{title}</title>
              <line x1={g.x} x2={g.x} y1={g.wickTop} y2={g.wickBottom} stroke={color} strokeWidth={1} />
              <rect
                x={g.x - candleW / 2}
                y={g.bodyTop}
                width={candleW}
                height={bodyH}
                fill={color}
                rx={0.5}
              />
            </g>
          )
        })}
        {maWindows.map(win => (
          <g key={`ma-${win}`}>
            <title>{`MA${win}`}</title>
            {maSegments(bars, win, extent, box).map((segment, si) => (
              <polyline
                key={si}
                points={segment.map(p => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ')}
                fill="none"
                stroke={maColor(win)}
                strokeWidth={1.2}
                strokeLinejoin="round"
              />
            ))}
          </g>
        ))}
        <text x={box.padLeft} y={HEIGHT - 4} fontSize={10} fill="var(--mommy-text-dim)">
          {bars[0]!.timestamp.slice(0, 10)}
        </text>
        <text
          x={width - box.padRight}
          y={HEIGHT - 4}
          fontSize={10}
          fill="var(--mommy-text-dim)"
          textAnchor="end"
        >
          {bars[bars.length - 1]!.timestamp.slice(0, 10)}
        </text>
      </svg>
      <div style={{ display: 'flex', gap: 10, fontSize: 10, color: 'var(--mommy-text-dim)' }}>
        {maWindows.map(win => (
          <span key={`legend-${win}`}>
            <span style={{ color: maColor(win) }}>━</span> MA{win}
          </span>
        ))}
      </div>
    </div>
  )
}
