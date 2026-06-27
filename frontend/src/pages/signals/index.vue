<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import Taro from '@tarojs/taro'
import { recentSignals, signalHistory } from '../../api/signals'
import { QuotesWS } from '../../api/ws'
import type { Signal } from '../../api/types'

const recentSignalsList = ref<Signal[]>([])
const history = ref<Signal[]>([])
const tab = ref<'recent' | 'history'>('recent')
const ws = new QuotesWS()

async function load() {
  try {
    recentSignalsList.value = await recentSignals()
    history.value = await signalHistory(50)
  } catch (e) {
    console.error(e)
  }
}

function severityClass(s: Signal['severity']): string {
  return `signal-${s}`
}

function severityLabel(s: Signal['severity']): string {
  return { info: 'INFO', warning: 'WARN', critical: 'CRIT' }[s]
}

function fmtTime(iso: string): string {
  const d = new Date(iso)
  const today = new Date()
  const sameDay = d.toDateString() === today.toDateString()
  if (sameDay) {
    return d.toTimeString().slice(0, 8)
  }
  return `${d.getMonth() + 1}/${d.getDate()} ${d.toTimeString().slice(0, 5)}`
}

onMounted(() => {
  load()
  setInterval(load, 30000)
})
</script>

<template>
  <view class="signals-page">
    <view class="header">
      <view class="title">信号中心</view>
    </view>

    <view class="tabs">
      <view
        :class="['tab', { active: tab === 'recent' }]"
        @tap="tab = 'recent'"
      >本次触发 ({{ recentSignalsList.length }})</view>
      <view
        :class="['tab', { active: tab === 'history' }]"
        @tap="tab = 'history'"
      >历史信号</view>
    </view>

    <view class="signal-list" v-if="tab === 'recent' && recentSignalsList.length">
      <view
        v-for="s in recentSignalsList"
        :key="`${s.timestamp}-${s.code}-${s.rule_id}`"
        :class="['signal-card', severityClass(s.severity)]"
      >
        <view class="signal-head">
          <text :class="['severity-tag', severityClass(s.severity)]">{{ severityLabel(s.severity) }}</text>
          <text class="signal-code">{{ s.code }} {{ s.name }}</text>
          <text class="signal-time">{{ fmtTime(s.timestamp) }}</text>
        </view>
        <view class="signal-title">{{ s.title }}</view>
        <view class="signal-detail">{{ s.detail }}</view>
      </view>
      <view class="empty" v-if="!recentSignalsList.length">
        <text>本次轮询未触发信号</text>
      </view>
    </view>

    <view class="signal-list" v-else-if="tab === 'history' && history.length">
      <view
        v-for="s in history"
        :key="`${s.timestamp}-${s.code}-${s.rule_id}`"
        :class="['signal-card', severityClass(s.severity)]"
      >
        <view class="signal-head">
          <text :class="['severity-tag', severityClass(s.severity)]">{{ severityLabel(s.severity) }}</text>
          <text class="signal-code">{{ s.code }} {{ s.name }}</text>
          <text class="signal-time">{{ fmtTime(s.timestamp) }}</text>
        </view>
        <view class="signal-title">{{ s.title }}</view>
        <view class="signal-detail">{{ s.detail }}</view>
      </view>
    </view>

    <view class="empty" v-else>
      <text>{{ tab === 'recent' ? '本次轮询未触发信号' : '暂无历史信号' }}</text>
    </view>

    <!-- Tab bar -->
    <view class="tab-bar">
      <view class="tab-item" @tap="Taro.navigateTo({ url: '/pages/index/index' })">行情</view>
      <view class="tab-item active">信号</view>
      <view class="tab-item" @tap="Taro.navigateTo({ url: '/pages/settings/index' })">设置</view>
    </view>
  </view>
</template>

<style scoped>
.signals-page {
  min-height: 100vh;
  background: #f5f5f5;
  padding-bottom: 120rpx;
}

.header {
  background: #c83e3e;
  color: white;
  padding: 32rpx 24rpx 24rpx;
}

.title {
  font-size: 40rpx;
  font-weight: bold;
}

.tabs {
  display: flex;
  background: white;
  border-bottom: 1rpx solid #eee;
}

.tab {
  flex: 1;
  text-align: center;
  padding: 24rpx 0;
  font-size: 28rpx;
  color: #666;
  border-bottom: 4rpx solid transparent;
}

.tab.active {
  color: #c83e3e;
  border-bottom-color: #c83e3e;
  font-weight: 600;
}

.signal-list {
  padding: 16rpx;
}

.signal-card {
  background: white;
  border-radius: 12rpx;
  padding: 20rpx;
  margin-bottom: 16rpx;
  border-left: 8rpx solid #ddd;
}

.signal-card.signal-critical {
  border-left-color: #c83e3e;
  background: linear-gradient(to right, #fff5f5, white);
}

.signal-card.signal-warning {
  border-left-color: #f59e0b;
  background: linear-gradient(to right, #fffaf0, white);
}

.signal-card.signal-info {
  border-left-color: #6b7280;
}

.signal-head {
  display: flex;
  align-items: center;
  margin-bottom: 8rpx;
  gap: 12rpx;
}

.severity-tag {
  font-size: 22rpx;
  padding: 2rpx 8rpx;
  border-radius: 4rpx;
  font-weight: bold;
}

.severity-tag.signal-critical { background: #c83e3e; color: white; }
.severity-tag.signal-warning { background: #f59e0b; color: white; }
.severity-tag.signal-info { background: #6b7280; color: white; }

.signal-code {
  font-size: 26rpx;
  font-weight: 600;
  flex: 1;
}

.signal-time {
  font-size: 22rpx;
  color: #999;
}

.signal-title {
  font-size: 28rpx;
  font-weight: 500;
  margin-bottom: 8rpx;
  color: #333;
}

.signal-detail {
  font-size: 24rpx;
  color: #666;
  line-height: 1.5;
}

.empty {
  padding: 80rpx 24rpx;
  text-align: center;
  color: #999;
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
