<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed, nextTick, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getQuote, getBars, getOrderBook } from '../../api'
import { fmtPrice, fmtPct, fmtMoney, fmtAge, changeColor } from '../../api'
import type { Quote, Bar, OrderBook } from '../../api/types'

const route = useRoute()
const router = useRouter()
const quote = ref<Quote | null>(null)
const bars = ref<Bar[]>([])
const orderBook = ref<OrderBook | null>(null)
const interval = ref<string>('1d')
const klineChart = ref<any>(null)

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
  try {
    orderBook.value = await getOrderBook(code.value)
  } catch (e) {
    orderBook.value = null
  }
}

async function drawKLine() {
  try {
    if (!klineChart.value) {
      const klinecharts = await import('klinecharts')
      const el = document.getElementById('kline') as HTMLElement
      if (!el) return
      klineChart.value = klinecharts.init(el)
    }
    const chart = klineChart.value
    chart.setStyles({
      grid: {
        show: true,
        horizontal: { show: true, color: '#eee' },
        vertical: { show: true, color: '#eee' }
      },
      candle: {
        bar: {
          upColor: '#c83e3e',
          downColor: '#2d8e3d',
          noChangeColor: '#999'
        }
      },
      indicator: {
        tooltip: { text: { color: '#333' } }
      }
    })

    chart.createIndicator('MA', false, { id: 'candle_pane' })
    chart.createIndicator('VOL')

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
})

onMounted(async () => {
  await loadQuote()
  await loadBars()
  await loadOrderBook()
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
          <span :style="{ color: Number(quote.main_net_inflow) >= 0 ? '#c83e3e' : '#2d8e3d' }">
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

    <div class="orderbook" v-if="orderBook">
      <div class="section-title">5档盘口</div>
      <div class="orderbook-cols">
        <div class="asks">
          <div class="ob-row" v-for="(lv, i) in orderBook.asks.slice().reverse()" :key="`a${i}`">
            <span class="price">{{ fmtPrice(lv.price) }}</span>
            <span class="volume">{{ lv.volume.toLocaleString() }}</span>
          </div>
        </div>
        <div class="bids">
          <div class="ob-row" v-for="(lv, i) in orderBook.bids" :key="`b${i}`">
            <span class="price">{{ fmtPrice(lv.price) }}</span>
            <span class="volume">{{ lv.volume.toLocaleString() }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.detail {
  min-height: 100vh;
  background: #f5f5f5;
  padding-bottom: 24px;
}

.header {
  background: #c83e3e;
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
  background: #c83e3e;
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
}

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
  font-size: 13px;
  padding: 4px 0;
  font-family: 'Courier New', monospace;
}

.asks .price { color: #2d8e3d; }
.bids .price { color: #c83e3e; }
.volume { color: #999; }
</style>
