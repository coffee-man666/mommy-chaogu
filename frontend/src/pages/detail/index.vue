<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed, nextTick } from 'vue'
import Taro from '@tarojs/taro'
import { getQuote, getBars, getOrderBook } from '../../api'
import { fmtPrice, fmtPct, fmtMoney, fmtAge, changeColor } from '../../api'
import type { Quote, Bar, OrderBook } from '../../api/types'

const code = ref<string>('')
const quote = ref<Quote | null>(null)
const bars = ref<Bar[]>([])
const orderBook = ref<OrderBook | null>(null)
const interval = ref<string>('1d')  // 1d / 1w / 1M / 5m / 15m / 30m / 60m
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
  '5m': 'm5',
  '15m': 'm15',
  '30m': 'm30',
  '60m': 'm60',
  '1d': 'd1',
  '1w': 'w1',
  '1M': 'M'
}

const highest = computed(() => {
  if (!bars.value.length) return '0'
  return Math.max(...bars.value.map(b => Number(b.high))).toFixed(2)
})
const lowest = computed(() => {
  if (!bars.value.length) return '0'
  return Math.min(...bars.value.map(b => Number(b.low))).toFixed(2)
})

async function loadQuote() {
  quote.value = await getQuote(code.value)
}

async function loadBars() {
  const apiInterval = efinanceToKlineInterval[interval.value] || 'd1'
  const limit = interval.value === '1d' ? 250 : interval.value === '1w' ? 250 : 200
  bars.value = await getBars(code.value, apiInterval, limit)
  await nextTick()
  drawKLine()
}

async function loadOrderBook() {
  try {
    orderBook.value = await getOrderBook(code.value)
  } catch (e) {
    orderBook.value = null
  }
}

async function drawKLine() {
  // Lazy load klinecharts
  if (!klineChart.value) {
    const klinecharts = await import('klinecharts')
    klineChart.value = klinecharts.init(document.getElementById('kline') as HTMLElement)
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
      tooltip: {
        text: { color: '#333' }
      }
    }
  })

  // MA 均线
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
}

function changeInterval(key: string) {
  interval.value = key
  loadBars()
}

function goBack() {
  Taro.navigateBack().catch(() => {
    history.back()
  })
}

onMounted(() => {
  // 取 query 参数
  const pages = Taro.getCurrentInstance() as any
  code.value = pages?.router?.params?.code || pages?.page?.options?.code || '600519'
  if (!code.value) code.value = '600519'
  loadQuote()
  loadBars()
  loadOrderBook()
})

onUnmounted(() => {
  if (klineChart.value) {
    klineChart.value.dispose()
    klineChart.value = null
  }
})
</script>

<template>
  <view class="detail">
    <!-- 头部 -->
    <view class="header">
      <view class="back" @tap="goBack">‹</view>
      <view class="title" v-if="quote">
        <text class="name">{{ quote.name }}</text>
        <text class="code">{{ quote.code }}</text>
      </view>
    </view>

    <!-- 实时报价 -->
    <view class="quote-box" v-if="quote">
      <view class="price-row">
        <text class="price" :style="{ color: changeColor(quote.change_pct) }">{{ fmtPrice(quote.price) }}</text>
        <text class="pct" :style="{ color: changeColor(quote.change_pct) }">{{ fmtPct(quote.change_pct) }}</text>
      </view>
      <view class="detail-row">
        <view class="detail-cell"><text class="label">今开</text><text>{{ fmtPrice(quote.open) }}</text></view>
        <view class="detail-cell"><text class="label">昨收</text><text>{{ fmtPrice(quote.prev_close) }}</text></view>
        <view class="detail-cell"><text class="label">最高</text><text>{{ fmtPrice(quote.high) }}</text></view>
        <view class="detail-cell"><text class="label">最低</text><text>{{ fmtPrice(quote.low) }}</text></view>
      </view>
      <view class="detail-row">
        <view class="detail-cell"><text class="label">成交量</text><text>{{ quote.volume.toLocaleString() }}</text></view>
        <view class="detail-cell"><text class="label">成交额</text><text>{{ fmtMoney(quote.turnover, 'yi') }}</text></view>
        <view class="detail-cell"><text class="label">换手</text><text>{{ quote.turnover_rate || '-' }}%</text></view>
        <view class="detail-cell"><text class="label">量比</text><text>{{ quote.volume_ratio || '-' }}</text></view>
      </view>
      <view class="detail-row" v-if="quote.pe || quote.main_net_inflow">
        <view class="detail-cell" v-if="quote.pe"><text class="label">PE</text><text>{{ quote.pe }}</text></view>
        <view class="detail-cell" v-if="quote.main_net_inflow">
          <text class="label">主力</text>
          <text :style="{ color: Number(quote.main_net_inflow) >= 0 ? '#c83e3e' : '#2d8e3d' }">
            {{ fmtMoney(quote.main_net_inflow, 'yi') }}
          </text>
        </view>
        <view class="detail-cell"><text class="label">数据</text><text>{{ fmtAge(quote.data_age_seconds) }}</text></view>
        <view class="detail-cell"></view>
      </view>
    </view>

    <!-- K线 -->
    <view class="kline-section">
      <view class="interval-tabs">
        <view
          v-for="i in intervals"
          :key="i.key"
          class="interval-tab"
          :class="{ active: interval === i.key }"
          @tap="changeInterval(i.key)"
        >{{ i.label }}</view>
      </view>
      <view class="kline-box">
        <view id="kline" class="kline-canvas"></view>
      </view>
    </view>

    <!-- 5档盘口 -->
    <view class="orderbook" v-if="orderBook">
      <view class="section-title">5档盘口</view>
      <view class="orderbook-cols">
        <view class="asks">
          <view class="ob-row" v-for="(lv, i) in orderBook.asks.slice().reverse()" :key="`a${i}`">
            <text class="price">{{ fmtPrice(lv.price) }}</text>
            <text class="volume">{{ lv.volume.toLocaleString() }}</text>
          </view>
        </view>
        <view class="bids">
          <view class="ob-row" v-for="(lv, i) in orderBook.bids" :key="`b${i}`">
            <text class="price">{{ fmtPrice(lv.price) }}</text>
            <text class="volume">{{ lv.volume.toLocaleString() }}</text>
          </view>
        </view>
      </view>
    </view>
  </view>
</template>

<style scoped>
.detail {
  min-height: 100vh;
  background: #f5f5f5;
}

.header {
  background: #c83e3e;
  color: white;
  padding: 24rpx;
  display: flex;
  align-items: center;
}

.back {
  font-size: 48rpx;
  margin-right: 16rpx;
  width: 60rpx;
}

.title .name {
  font-size: 36rpx;
  font-weight: bold;
  margin-right: 16rpx;
}

.title .code {
  font-size: 24rpx;
  opacity: 0.8;
}

.quote-box {
  background: white;
  padding: 24rpx;
}

.price-row {
  display: flex;
  align-items: baseline;
  gap: 16rpx;
  margin-bottom: 24rpx;
}

.price {
  font-size: 64rpx;
  font-weight: bold;
  font-family: 'Courier New', monospace;
}

.pct {
  font-size: 32rpx;
  font-family: 'Courier New', monospace;
}

.detail-row {
  display: flex;
  justify-content: space-between;
  margin-bottom: 12rpx;
}

.detail-cell {
  flex: 1;
  font-size: 24rpx;
  display: flex;
  flex-direction: column;
  align-items: center;
}

.detail-cell .label {
  color: #999;
  font-size: 22rpx;
  margin-bottom: 4rpx;
}

.kline-section {
  background: white;
  margin-top: 16rpx;
}

.interval-tabs {
  display: flex;
  padding: 16rpx;
  border-bottom: 1rpx solid #eee;
}

.interval-tab {
  flex: 1;
  text-align: center;
  font-size: 24rpx;
  color: #666;
  padding: 8rpx 0;
  border-radius: 8rpx;
}

.interval-tab.active {
  background: #c83e3e;
  color: white;
}

.kline-box {
  padding: 16rpx;
  height: 600rpx;
}

.kline-canvas {
  width: 100%;
  height: 100%;
}

.orderbook {
  background: white;
  margin-top: 16rpx;
  padding: 24rpx;
}

.section-title {
  font-size: 28rpx;
  font-weight: 600;
  margin-bottom: 16rpx;
}

.orderbook-cols {
  display: flex;
  gap: 16rpx;
}

.asks, .bids {
  flex: 1;
}

.ob-row {
  display: flex;
  justify-content: space-between;
  font-size: 24rpx;
  padding: 6rpx 0;
  font-family: 'Courier New', monospace;
}

.asks .price { color: #2d8e3d; }
.bids .price { color: #c83e3e; }
.volume { color: #999; }
</style>
