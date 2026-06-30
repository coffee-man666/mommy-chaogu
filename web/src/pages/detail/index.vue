<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed, nextTick, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getQuote, getBars, getOrderBook, getTodayMoneyFlow, getHistoryMoneyFlow } from '../../api'
import { fmtPrice, fmtPct, fmtMoney, fmtAge, changeColor } from '../../api'
import type { Quote, Bar, OrderBook, MoneyFlowItem, MoneyFlowCumulative } from '../../api/types'

const route = useRoute()
const router = useRouter()
const quote = ref<Quote | null>(null)
const bars = ref<Bar[]>([])
const orderBook = ref<OrderBook | null>(null)
const interval = ref<string>('1d')
const klineChart = ref<any>(null)

// 资金流
const flowToday = ref<{ items: MoneyFlowItem[]; cumulative: MoneyFlowCumulative } | null>(null)
const flowHistory = ref<{ items: MoneyFlowItem[]; cumulative: MoneyFlowCumulative; days: number } | null>(null)
const flowTab = ref<'today' | 'history'>('today')
const flowDays = ref(30)
const flowLoading = ref(false)

const intervals = [
  { key: '5m', label: '5分' },
  { key: '15m', label: '15分' },
  { key: '30m', label: '30分' },
  { key: '60m', label: '60分' },
  { key: '1d', label: '日K' },
  { key: '1w', label: '周K' },
  { key: '1M', label: '月K' }
]

const efinanceToKlineInterval: Record<string, string> = {
  '5m': '5m',
  '15m': '15m',
  '30m': '30m',
  '60m': '60m',
  '1d': '1d',
  '1w': '1w',
  '1M': '1M'
}

const code = computed(() => String(route.params.code || '600519'))

async function loadQuote() {
  try {
    quote.value = await getQuote(code.value)
  } catch (e) {
    console.error(e)
  }
}

async function loadBars() {
  try {
    const apiInterval = efinanceToKlineInterval[interval.value] || 'd1'
    const limit = interval.value === '1d' ? 250 : interval.value === '1w' ? 250 : 200
    bars.value = await getBars(code.value, apiInterval, limit)
    await nextTick()
    drawKLine()
  } catch (e) {
    console.error(e)
  }
}

async function loadOrderBook() {
  // 盘口已隐藏，不再拉取
  orderBook.value = null
}

async function loadFlow() {
  flowLoading.value = true
  try {
    const [today, hist] = await Promise.all([
      getTodayMoneyFlow(code.value).catch(() => null),
      getHistoryMoneyFlow(code.value, flowDays.value).catch(() => null),
    ])
    if (today) flowToday.value = today
    if (hist) flowHistory.value = hist
  } finally {
    flowLoading.value = false
  }
}

function fmtFlowWan(s: string | null | undefined): string {
  if (!s) return '-'
  const n = Number(s)
  if (isNaN(n)) return s
  if (Math.abs(n) >= 1e8) return `${(n / 1e8).toFixed(2)}亿`
  if (Math.abs(n) >= 1e4) return `${(n / 1e4).toFixed(2)}万`
  return n.toFixed(0)
}

function flowColor(s: string | null | undefined): string {
  if (!s) return '#999'
  return Number(s) >= 0 ? 'var(--color-primary)' : 'var(--color-down)'
}

function flowSign(s: string | null | undefined): string {
  if (!s) return ''
  return Number(s) >= 0 ? '+' : ''
}

async function changeFlowDays(d: number) {
  flowDays.value = d
  try {
    const hist = await getHistoryMoneyFlow(code.value, d)
    flowHistory.value = hist
  } catch (e) {
    console.error(e)
  }
}

function barWidth(val: string | null, all: MoneyFlowItem[]): number {
  if (!val) return 0
  const maxAbs = Math.max(...all.map(i => Math.abs(Number(i.main_net) || 0)), 1)
  return Math.min(48, (Math.abs(Number(val)) / maxAbs) * 48)
}

// ---------- SVG 资金流图 ----------

const SVG_W = 350
const SVG_H_TODAY = 160
const SVG_H_HISTORY = 200
const PAD_L = 4
const PAD_R = 4
const PAD_T = 10
const PAD_B = 20

// 日内分时折线图
const todayFlowPoints = computed(() => {
  if (!flowToday.value?.items?.length) return ''
  const items = flowToday.value.items
  const W = SVG_W - PAD_L - PAD_R
  const H = SVG_H_TODAY - PAD_T - PAD_B
  const vals = items.map((i: any) => Number(i.main_net) || 0)
  const maxAbs = Math.max(...vals.map(Math.abs), 1)
  const n = items.length
  const stepX = W / Math.max(n - 1, 1)
  // debug
  if (typeof window !== 'undefined' && (window as any).__debugFlow) {
    console.log('todayFlowPoints', { n, W, H, maxAbs, firstVal: vals[0] })
  }
  return items.map((v: number, i: number) => {
    const val = Number((items[i] as any).main_net) || 0
    const x = PAD_L + i * stepX
    const y = PAD_T + H / 2 - (val / maxAbs) * (H / 2 - 4)
    return `${x.toFixed(1)},${y.toFixed(1)}`
  }).join(' ')
})

const todayFlowArea = computed(() => {
  if (!flowToday.value?.items?.length) return ''
  const pts = todayFlowPoints.value
  if (!pts) return ''
  const items = flowToday.value.items
  const W = SVG_W - PAD_L - PAD_R
  const stepX = W / Math.max(items.length - 1, 1)
  const lastX = PAD_L + (items.length - 1) * stepX
  const midY = PAD_T + (SVG_H_TODAY - PAD_T - PAD_B) / 2
  return `${PAD_L},${midY} ${pts} ${lastX},${midY}`
})

const todayFlowColor = computed(() => {
  const c = flowToday.value?.cumulative
  if (!c) return '#999'
  return Number(c.main_net) >= 0 ? 'var(--color-primary)' : 'var(--color-down)'
})

const todayTimeLabels = computed(() => {
  if (!flowToday.value?.items?.length) return []
  const items = flowToday.value.items
  return [items[0]?.timestamp?.slice(11, 16) || '', items[Math.floor(items.length / 2)]?.timestamp?.slice(11, 16) || '', items[items.length - 1]?.timestamp?.slice(11, 16) || '']
})

const historyBars = computed(() => {
  if (!flowHistory.value?.items?.length) return []
  const items = flowHistory.value.items
  const W = SVG_W - PAD_L - PAD_R
  const H = SVG_H_HISTORY - PAD_T - PAD_B
  const vals = items.map(i => Number(i.main_net) || 0)
  const maxAbs = Math.max(...vals.map(Math.abs), 1)
  const barW = Math.min(24, W / items.length * 0.6)
  const gap = W / items.length
  const midY = PAD_T + H / 2
  return items.map((item, i) => {
    const v = Number(item.main_net) || 0
    const x = PAD_L + i * gap + (gap - barW) / 2
    const barH = (Math.abs(v) / maxAbs) * (H / 2 - 4)
    const y = v >= 0 ? midY - barH : midY
    return { x: x.toFixed(1), y: y.toFixed(1), w: barW.toFixed(1), h: barH.toFixed(1), color: v >= 0 ? 'var(--color-primary)' : 'var(--color-down)', date: item.date?.slice(5) || '', val: fmtFlowWan(item.main_net) }
  })
})

const historyMidY = computed(() => PAD_T + (SVG_H_HISTORY - PAD_T - PAD_B) / 2)

async function drawKLine() {
  try {
    const isFirstInit = !klineChart.value
    if (isFirstInit) {
      const klinecharts = await import('klinecharts')
      const el = document.getElementById('kline') as HTMLElement
      if (!el) return
      klineChart.value = klinecharts.init(el)
    }
    const chart = klineChart.value

    // 样式每次都设（幂等，无副作用）
    chart.setStyles({
      grid: {
        show: true,
        horizontal: { show: true, color: '#eee' },
        vertical: { show: true, color: '#eee' }
      },
      candle: {
        bar: {
          upColor: 'var(--color-primary)',
          downColor: 'var(--color-down)',
          noChangeColor: '#999'
        }
      },
      indicator: {
        tooltip: { text: { color: '#333' } }
      }
    })

    // 指标只在首次初始化时创建，避免切换周期重复叠加
    if (isFirstInit) {
      chart.createIndicator('MA', false, { id: 'candle_pane' })
      chart.createIndicator('VOL')
    }

    const dataList = bars.value.map(b => ({
      timestamp: new Date(b.timestamp).getTime(),
      open: Number(b.open),
      high: Number(b.high),
      low: Number(b.low),
      close: Number(b.close),
      volume: Number(b.volume)
    }))
    chart.applyNewData(dataList)
  } catch (e) {
    console.error('drawKLine failed', e)
  }
}

function changeInterval(key: string) {
  interval.value = key
  loadBars()
}

function goBack() {
  router.back()
}

watch(code, async () => {
  await loadQuote()
  await loadBars()
  await loadOrderBook()
  loadFlow()
})

onMounted(async () => {
  await loadQuote()
  await loadBars()
  await loadOrderBook()
  loadFlow()
})

onUnmounted(() => {
  if (klineChart.value) {
    klineChart.value.dispose()
    klineChart.value = null
  }
})
</script>

<template>
  <div class="detail">
    <header class="header">
      <span class="back" @click="goBack">‹</span>
      <div class="title" v-if="quote">
        <span class="name">{{ quote.name }}</span>
        <span class="code">{{ quote.code }}</span>
      </div>
    </header>

    <div class="quote-box" v-if="quote">
      <div class="price-row">
        <span class="price" :style="{ color: changeColor(quote.change_pct) }">{{ fmtPrice(quote.price) }}</span>
        <span class="pct" :style="{ color: changeColor(quote.change_pct) }">{{ fmtPct(quote.change_pct) }}</span>
      </div>
      <div class="detail-row">
        <div class="detail-cell"><span class="label">今开</span><span>{{ fmtPrice(quote.open) }}</span></div>
        <div class="detail-cell"><span class="label">昨收</span><span>{{ fmtPrice(quote.prev_close) }}</span></div>
        <div class="detail-cell"><span class="label">最高</span><span>{{ fmtPrice(quote.high) }}</span></div>
        <div class="detail-cell"><span class="label">最低</span><span>{{ fmtPrice(quote.low) }}</span></div>
      </div>
      <div class="detail-row">
        <div class="detail-cell"><span class="label">成交量</span><span>{{ quote.volume.toLocaleString() }}</span></div>
        <div class="detail-cell"><span class="label">成交额</span><span>{{ fmtMoney(quote.turnover, 'yi') }}</span></div>
        <div class="detail-cell"><span class="label">换手</span><span>{{ quote.turnover_rate || '-' }}%</span></div>
        <div class="detail-cell"><span class="label">量比</span><span>{{ quote.volume_ratio || '-' }}</span></div>
      </div>
      <div class="detail-row" v-if="quote.pe || quote.main_net_inflow">
        <div class="detail-cell" v-if="quote.pe"><span class="label">PE</span><span>{{ quote.pe }}</span></div>
        <div class="detail-cell" v-if="quote.main_net_inflow">
          <span class="label">主力</span>
          <span :style="{ color: Number(quote.main_net_inflow) >= 0 ? 'var(--color-primary)' : 'var(--color-down)' }">
            {{ fmtMoney(quote.main_net_inflow, 'yi') }}
          </span>
        </div>
        <div class="detail-cell"><span class="label">数据</span><span>{{ fmtAge(quote.data_age_seconds) }}</span></div>
        <div class="detail-cell"></div>
      </div>
    </div>

    <div class="kline-section">
      <div class="interval-tabs">
        <span
          v-for="i in intervals"
          :key="i.key"
          :class="['interval-tab', { active: interval === i.key }]"
          @click="changeInterval(i.key)"
        >{{ i.label }}</span>
      </div>
      <div class="kline-box">
        <div id="kline" class="kline-canvas"></div>
      </div>
    </div>

    <!-- 资金流 -->
    <div class="money-flow">
      <div class="section-title">
        资金流向
        <div class="flow-tabs">
          <span :class="['flow-tab', { active: flowTab === 'today' }]" @click="flowTab = 'today'">日内</span>
          <span :class="['flow-tab', { active: flowTab === 'history' }]" @click="flowTab = 'history'">历史</span>
        </div>
      </div>

      <!-- 累计汇总卡片 -->
      <div class="flow-summary" v-if="(flowTab === 'today' ? flowToday?.cumulative : flowHistory?.cumulative)">
        <div class="flow-sum-row">
          <div class="flow-sum-item main">
            <span class="fs-label">主力净流入</span>
            <span class="fs-value" :style="{ color: flowColor(flowTab === 'today' ? flowToday?.cumulative.main_net : flowHistory?.cumulative.main_net) }">
              {{ flowSign(flowTab === 'today' ? flowToday?.cumulative.main_net : flowHistory?.cumulative.main_net) }}{{ fmtFlowWan(flowTab === 'today' ? flowToday?.cumulative.main_net : flowHistory?.cumulative.main_net) }}
            </span>
          </div>
          <div class="flow-sum-item">
            <span class="fs-label">超大单</span>
            <span class="fs-value" :style="{ color: flowColor(flowTab === 'today' ? flowToday?.cumulative.super_net : flowHistory?.cumulative.super_net) }">
              {{ flowSign(flowTab === 'today' ? flowToday?.cumulative.super_net : flowHistory?.cumulative.super_net) }}{{ fmtFlowWan(flowTab === 'today' ? flowToday?.cumulative.super_net : flowHistory?.cumulative.super_net) }}
            </span>
          </div>
          <div class="flow-sum-item">
            <span class="fs-label">大单</span>
            <span class="fs-value" :style="{ color: flowColor(flowTab === 'today' ? flowToday?.cumulative.big_net : flowHistory?.cumulative.big_net) }">
              {{ flowSign(flowTab === 'today' ? flowToday?.cumulative.big_net : flowHistory?.cumulative.big_net) }}{{ fmtFlowWan(flowTab === 'today' ? flowToday?.cumulative.big_net : flowHistory?.cumulative.big_net) }}
            </span>
          </div>
          <div class="flow-sum-item">
            <span class="fs-label">中单</span>
            <span class="fs-value" :style="{ color: flowColor(flowTab === 'today' ? flowToday?.cumulative.medium_net : flowHistory?.cumulative.medium_net) }">
              {{ flowSign(flowTab === 'today' ? flowToday?.cumulative.medium_net : flowHistory?.cumulative.medium_net) }}{{ fmtFlowWan(flowTab === 'today' ? flowToday?.cumulative.medium_net : flowHistory?.cumulative.medium_net) }}
            </span>
          </div>
          <div class="flow-sum-item">
            <span class="fs-label">小单</span>
            <span class="fs-value" :style="{ color: flowColor(flowTab === 'today' ? flowToday?.cumulative.small_net : flowHistory?.cumulative.small_net) }">
              {{ flowSign(flowTab === 'today' ? flowToday?.cumulative.small_net : flowHistory?.cumulative.small_net) }}{{ fmtFlowWan(flowTab === 'today' ? flowToday?.cumulative.small_net : flowHistory?.cumulative.small_net) }}
            </span>
          </div>
        </div>
      </div>

      <!-- 历史天数选择 -->
      <div class="flow-days" v-if="flowTab === 'history'">
        <span :class="['day-btn', { active: flowDays === 7 }]" @click="changeFlowDays(7)">7天</span>
        <span :class="['day-btn', { active: flowDays === 30 }]" @click="changeFlowDays(30)">30天</span>
        <span :class="['day-btn', { active: flowDays === 90 }]" @click="changeFlowDays(90)">90天</span>
      </div>

      <!-- 日内分时图 -->
      <div class="flow-chart-box" v-if="flowTab === 'today' && flowToday && flowToday.items.length">
        <svg :viewBox="`0 0 ${SVG_W} ${SVG_H_TODAY}`" class="flow-svg" preserveAspectRatio="xMidYMid meet">
          <!-- 零线 -->
          <line :x1="PAD_L" :y1="SVG_H_TODAY / 2" :x2="SVG_W - PAD_R" :y2="SVG_H_TODAY / 2" stroke="#eee" stroke-width="1" />
          <!-- 面积填充 -->
          <polygon :points="todayFlowArea" :fill="todayFlowColor" fill-opacity="0.12" />
          <!-- 折线 -->
          <polyline :points="todayFlowPoints" :stroke="todayFlowColor" stroke-width="1.5" fill="none" />
        </svg>
        <div class="flow-time-labels">
          <span v-for="(t, i) in todayTimeLabels" :key="i">{{ t }}</span>
        </div>
      </div>
      <div class="flow-empty" v-else-if="flowTab === 'today' && !flowLoading">
        暂无日内数据（非盘中时段）
      </div>

      <!-- 历史柱状图 -->
      <div class="flow-chart-box" v-if="flowTab === 'history' && flowHistory && flowHistory.items.length">
        <svg :viewBox="`0 0 ${SVG_W} ${SVG_H_HISTORY}`" class="flow-svg" preserveAspectRatio="xMidYMid meet">
          <!-- 零线 -->
          <line :x1="PAD_L" :y1="historyMidY" :x2="SVG_W - PAD_R" :y2="historyMidY" stroke="#ddd" stroke-width="1" stroke-dasharray="3,3" />
          <!-- 柱子 -->
          <template v-for="(b, i) in historyBars" :key="i">
            <rect :x="b.x" :y="b.y" :width="b.w" :height="b.h" :fill="b.color" rx="2" />
            <text :x="Number(b.x) + Number(b.w) / 2" :y="Number(b.y) < historyMidY ? Number(b.y) - 4 : Number(b.y) + Number(b.h) + 12" text-anchor="middle" font-size="8" fill="#999">{{ b.val }}</text>
            <text :x="Number(b.x) + Number(b.w) / 2" :y="SVG_H_HISTORY - 6" text-anchor="middle" font-size="8" fill="#aaa">{{ b.date }}</text>
          </template>
        </svg>
      </div>
      <div class="flow-empty" v-else-if="flowTab === 'history' && !flowLoading">
        暂无历史数据
      </div>
    </div>
  </div>
</template>

<style scoped>
.detail {
  min-height: 100vh;
  background: var(--color-bg);
  padding-bottom: 24px;
}

.header {
  background: var(--color-primary);
  color: white;
  padding: 16px;
  display: flex;
  align-items: center;
}

.back {
  font-size: 32px;
  margin-right: 12px;
  width: 36px;
  cursor: pointer;
}

.title .name {
  font-size: 20px;
  font-weight: bold;
  margin-right: 12px;
}

.title .code {
  font-size: 14px;
  opacity: 0.8;
}

.quote-box {
  background: white;
  padding: 16px;
}

.price-row {
  display: flex;
  align-items: baseline;
  gap: 12px;
  margin-bottom: 16px;
}

.price {
  font-size: 40px;
  font-weight: bold;
  font-family: 'Courier New', monospace;
}

.pct {
  font-size: 20px;
  font-family: 'Courier New', monospace;
}

.detail-row {
  display: flex;
  justify-content: space-between;
  margin-bottom: 8px;
}

.detail-cell {
  flex: 1;
  font-size: 14px;
  display: flex;
  flex-direction: column;
  align-items: center;
}

.detail-cell .label {
  color: #999;
  font-size: 12px;
  margin-bottom: 2px;
}

.kline-section {
  background: white;
  margin-top: 12px;
}

.interval-tabs {
  display: flex;
  padding: 12px;
  border-bottom: 1px solid #eee;
}

.interval-tab {
  flex: 1;
  text-align: center;
  font-size: 13px;
  color: #666;
  padding: 6px 0;
  border-radius: 6px;
  cursor: pointer;
  user-select: none;
}

.interval-tab.active {
  background: var(--color-primary);
  color: white;
}

.kline-box {
  padding: 12px;
  height: 360px;
}

.kline-canvas {
  width: 100%;
  height: 100%;
}

.orderbook {
  background: white;
  margin-top: 12px;
  padding: 16px;
}

.section-title {
  font-size: 16px;
  font-weight: 600;
  margin-bottom: 12px;
  display: flex;
  align-items: center;
  gap: 12px;
}

.ob-legend {
  font-size: 11px;
  font-weight: normal;
  color: #666;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.ob-legend .dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  display: inline-block;
}

.ob-legend .dot.sell { background: var(--color-primary); }
.ob-legend .dot.buy { background: var(--color-down); }

.orderbook-cols {
  display: flex;
  gap: 12px;
}

.asks, .bids {
  flex: 1;
}

.ob-row {
  display: flex;
  justify-content: space-between;
  font-size: 14px;
  padding: 5px 0;
  font-family: 'Courier New', monospace;
}

/* A股约定：卖=红，买=绿 */
.asks .price { color: var(--color-primary); font-weight: 600; }
.bids .price { color: var(--color-down); font-weight: 600; }
.volume { color: #666; font-size: 12px; }

/* 资金流 */
.money-flow {
  background: white;
  margin-top: 12px;
  padding: 16px;
}

.flow-tabs {
  display: inline-flex;
  gap: 0;
  border: 1px solid #ddd;
  border-radius: 6px;
  overflow: hidden;
  font-weight: normal;
}

.flow-tab {
  padding: 4px 12px;
  font-size: 12px;
  color: #666;
  cursor: pointer;
  user-select: none;
}

.flow-tab.active {
  background: var(--color-primary);
  color: white;
}

/* 累计卡片 */
.flow-summary {
  margin-top: 12px;
}

.flow-sum-row {
  display: flex;
  gap: 4px;
}

.flow-sum-item {
  flex: 1;
  text-align: center;
  padding: 8px 4px;
  background: #f8f8f8;
  border-radius: 6px;
}

.flow-sum-item.main {
  background: var(--color-bg);
}

.fs-label {
  display: block;
  font-size: 10px;
  color: #999;
  margin-bottom: 4px;
}

.fs-value {
  display: block;
  font-size: 13px;
  font-weight: 700;
  font-family: 'Courier New', monospace;
}

/* 天数选择 */
.flow-days {
  display: flex;
  gap: 6px;
  margin-top: 12px;
}

.day-btn {
  padding: 4px 14px;
  font-size: 12px;
  border: 1px solid #ddd;
  border-radius: 14px;
  color: #666;
  cursor: pointer;
  user-select: none;
}

.day-btn.active {
  background: var(--color-primary);
  color: white;
  border-color: var(--color-primary);
}

/* 资金流图表 */
.flow-chart-box {
  margin-top: 12px;
}

.flow-svg {
  width: 100%;
  height: auto;
  display: block;
}

.flow-time-labels {
  display: flex;
  justify-content: space-between;
  padding: 4px 4px 0;
  font-size: 10px;
  color: #aaa;
  font-family: 'Courier New', monospace;
}

.flow-empty {
  padding: 24px 0;
  text-align: center;
  color: #999;
  font-size: 13px;
}
</style>
