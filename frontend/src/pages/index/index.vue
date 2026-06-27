<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed } from 'vue'
import { useRouter } from '@tarojs/taro'  // may not work in H5
import Taro from '@tarojs/taro'
import { getSnapshot } from '../../api'
import { QuotesWS } from '../../api/ws'
import { fmtPrice, fmtPct, fmtMoney, fmtAge, changeColor } from '../../api'
import type { Snapshot, Quote } from '../../api/types'

const snapshot = ref<Snapshot | null>(null)
const loading = ref(true)
const ws = new QuotesWS()

const lastUpdate = computed(() => {
  if (!snapshot.value) return '-'
  return fmtAge(Math.max(0, Math.floor((Date.now() - new Date(snapshot.value.timestamp).getTime()) / 1000)))
})

async function refresh() {
  try {
    loading.value = true
    snapshot.value = await getSnapshot()
  } catch (e) {
    console.error(e)
  } finally {
    loading.value = false
  }
}

function goDetail(quote: Quote) {
  // H5: 用 history.pushState；小程序：Taro.navigateTo
  const url = `/pages/detail/index?code=${quote.code}`
  Taro.navigateTo({ url }).catch(() => {
    window.location.href = `#${url}`
  })
}

function onUpdate(snap: Snapshot) {
  snapshot.value = snap
}

onMounted(() => {
  refresh()
  ws.connect(onUpdate)
})

onUnmounted(() => {
  ws.disconnect()
})
</script>

<template>
  <view class="dashboard">
    <!-- 顶部状态栏 -->
    <view class="header">
      <view class="header-title">妈妈炒股</view>
      <view class="header-stats" v-if="snapshot">
        <text class="stat-num">{{ snapshot.n_codes }}</text>
        <text class="stat-label">只</text>
        <text class="stat-up">↑{{ snapshot.n_up }}</text>
        <text class="stat-down">↓{{ snapshot.n_down }}</text>
        <text class="stat-flat">平{{ snapshot.n_flat }}</text>
        <text class="stat-flow">主力 {{ fmtMoney(snapshot.total_main_net, 'yi') }}</text>
      </view>
      <view class="header-time">{{ lastUpdate }} · 实时</view>
    </view>

    <!-- 自选股列表 -->
    <view class="quote-list" v-if="snapshot && snapshot.quotes.length">
      <view
        v-for="q in snapshot.quotes"
        :key="q.code"
        class="quote-row"
        @tap="goDetail(q)"
      >
        <view class="quote-left">
          <view class="quote-name">{{ q.name }}</view>
          <view class="quote-code">{{ q.code }} · {{ q.market }}</view>
        </view>
        <view class="quote-mid">
          <view class="quote-price" :style="{ color: changeColor(q.change_pct) }">
            {{ fmtPrice(q.price) }}
          </view>
          <view class="quote-pct" :style="{ color: changeColor(q.change_pct) }">
            {{ fmtPct(q.change_pct) }}
          </view>
        </view>
        <view class="quote-right">
          <view class="quote-flow" v-if="q.main_net_inflow">
            {{ q.main_net_inflow.startsWith('-') ? '' : '+' }}{{ fmtMoney(q.main_net_inflow, 'yi') }}
          </view>
          <view class="quote-flow-label">主力</view>
        </view>
      </view>
    </view>

    <view class="empty" v-else-if="!loading">
      <text>暂无自选股</text>
      <text class="empty-hint">去「设置」添加股票</text>
    </view>

    <view class="loading" v-if="loading">
      <text>加载中...</text>
    </view>

    <!-- 底部 Tab -->
    <view class="tab-bar">
      <view class="tab-item active">行情</view>
      <view class="tab-item" @tap="Taro.navigateTo({ url: '/pages/signals/index' })">信号</view>
      <view class="tab-item" @tap="Taro.navigateTo({ url: '/pages/settings/index' })">设置</view>
    </view>
  </view>
</template>

<style scoped>
.dashboard {
  min-height: 100vh;
  padding-bottom: 120rpx;
  background: #f5f5f5;
}

.header {
  background: linear-gradient(135deg, #c83e3e, #a52828);
  color: white;
  padding: 32rpx 24rpx 24rpx;
}

.header-title {
  font-size: 40rpx;
  font-weight: bold;
  margin-bottom: 16rpx;
}

.header-stats {
  display: flex;
  align-items: baseline;
  gap: 12rpx;
  font-size: 24rpx;
  flex-wrap: wrap;
}

.stat-num { font-size: 48rpx; font-weight: bold; margin-right: 4rpx; }
.stat-label { font-size: 24rpx; opacity: 0.8; margin-right: 16rpx; }
.stat-up { color: #ff6b6b; margin-right: 12rpx; }
.stat-down { color: #51cf66; margin-right: 12rpx; }
.stat-flat { opacity: 0.8; margin-right: 12rpx; }
.stat-flow { margin-left: auto; opacity: 0.9; }

.header-time {
  font-size: 22rpx;
  opacity: 0.7;
  margin-top: 8rpx;
}

.quote-list {
  background: white;
}

.quote-row {
  display: flex;
  align-items: center;
  padding: 24rpx;
  border-bottom: 1rpx solid #eee;
}

.quote-row:active {
  background: #f8f8f8;
}

.quote-left {
  flex: 1;
}

.quote-name {
  font-size: 32rpx;
  font-weight: 600;
  margin-bottom: 4rpx;
}

.quote-code {
  font-size: 22rpx;
  color: #999;
}

.quote-mid {
  text-align: right;
  margin-right: 32rpx;
  min-width: 140rpx;
}

.quote-price {
  font-size: 36rpx;
  font-weight: bold;
  font-family: 'Courier New', monospace;
}

.quote-pct {
  font-size: 24rpx;
  margin-top: 4rpx;
  font-family: 'Courier New', monospace;
}

.quote-right {
  text-align: right;
  min-width: 160rpx;
}

.quote-flow {
  font-size: 26rpx;
  color: #ff6b6b;
  font-family: 'Courier New', monospace;
}

.quote-flow-label {
  font-size: 20rpx;
  color: #999;
  margin-top: 2rpx;
}

.empty, .loading {
  padding: 80rpx 24rpx;
  text-align: center;
  color: #999;
}

.empty-hint {
  display: block;
  font-size: 24rpx;
  color: #ccc;
  margin-top: 8rpx;
}

.tab-bar {
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  height: 100rpx;
  background: white;
  border-top: 1rpx solid #eee;
  display: flex;
}

.tab-item {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 26rpx;
  color: #999;
}

.tab-item.active {
  color: #c83e3e;
  font-weight: 600;
}
</style>
