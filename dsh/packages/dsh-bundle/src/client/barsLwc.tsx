/**
 * get_bars 卡片·Lightweight-Charts 交互 K 线（可选模式）。
 *
 * 纪律：LWC 无指标引擎，正合「市场计算不落 TS 侧」——MA 一律以 LineSeries
 * 喂服务端 ma_<w> 值，绝不引入任何计算。蜡烛涨跌色从 tokens.css 的 A 股
 * 语义变量读取（getComputedStyle），宿主深浅主题下都保持涨红跌绿。图表
 * 生命周期：挂载创建、卸载 remove()、ResizeObserver 跟随卡片宽度；创建
 * 失败回落表格（不炸 slot）。
 */
import { useEffect, useRef, useState } from 'react'
import { CandlestickSeries, LineSeries, createChart, type IChartApi } from 'lightweight-charts'
import type { BarView } from './parse.ts'

const HEIGHT = 210

/** 均线配色（与 barsSvg.tsx 保持一致）。 */
const MA_COLORS: Record<string, string> = { '5': '#f59e0b', '20': '#3b82f6', '50': '#a855f7' }
const MA_FALLBACK = '#8b8b8b'

function cssVar(name: string, fallback: string): string {
  if (typeof document === 'undefined') return fallback
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  return v === '' ? fallback : v
}

export function BarsLwcChart(props: { bars: BarView[]; maWindows: string[]; onFailed: () => void }) {
  const { bars, maWindows, onFailed } = props
  const ref = useRef<HTMLDivElement | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    const el = ref.current
    if (el === null || bars.length === 0) return undefined
    let chart: IChartApi | null = null
    let observer: ResizeObserver | null = null
    try {
      const upColor = cssVar('--mommy-up', '#d93025')
      const downColor = cssVar('--mommy-down', '#1a7f37')
      chart = createChart(el, {
        width: el.clientWidth,
        height: HEIGHT,
        autoSize: false,
        layout: {
          background: { color: 'transparent' },
          textColor: cssVar('--mommy-text-dim', '#8b8b8b'),
          fontFamily: cssVar('--mommy-font-num', 'monospace'),
          fontSize: 10,
        },
        grid: {
          vertLines: { color: 'rgba(127,127,127,0.12)' },
          horzLines: { color: 'rgba(127,127,127,0.12)' },
        },
        timeScale: { borderVisible: false },
        rightPriceScale: { borderVisible: false },
        crosshair: { mode: 0 },
      })
      const candles = chart.addSeries(CandlestickSeries, {
        upColor,
        downColor,
        borderVisible: false,
        wickUpColor: upColor,
        wickDownColor: downColor,
      })
      candles.setData(
        bars.map(bar => ({
          time: bar.timestamp.slice(0, 10),
          open: bar.open,
          high: bar.high,
          low: bar.low,
          close: bar.close,
        })),
      )
      for (const win of maWindows) {
        const color = MA_COLORS[win] ?? MA_FALLBACK
        const line = chart.addSeries(LineSeries, { color, lineWidth: 1, priceLineVisible: false, lastValueVisible: false })
        line.setData(
          bars
            .filter(bar => bar.ma[win] !== null && bar.ma[win] !== undefined)
            .map(bar => ({ time: bar.timestamp.slice(0, 10), value: bar.ma[win] as number })),
        )
      }
      chart.timeScale().fitContent()
      observer = new ResizeObserver(() => {
        chart?.applyOptions({ width: el.clientWidth })
      })
      observer.observe(el)
      return () => {
        observer?.disconnect()
        chart?.remove()
      }
    } catch (error) {
      console.error('[mommy-chaogu] lightweight-charts failed, falling back to table', error)
      setFailed(true)
      onFailed()
      return undefined
    }
  }, [bars, maWindows, onFailed])

  if (failed) return null
  return <div className="mommy-bars-lwc" ref={ref} style={{ width: '100%' }} />
}
