<script setup lang="ts">
import { ref, onMounted } from 'vue'
import Taro from '@tarojs/taro'
import { listWatchlist, listGroups, addStock, removeStock, addGroup, cacheStats, health } from '../../api'
import type { WatchlistStock, WatchlistGroup, CacheStats, Health } from '../../api/types'

const watchlist = ref<WatchlistStock[]>([])
const groups = ref<WatchlistGroup[]>([])
const cache = ref<CacheStats | null>(null)
const healthInfo = ref<Health | null>(null)
const showAdd = ref(false)
const newCode = ref('')
const newGroup = ref('')
const newNote = ref('')

async function load() {
  try {
    watchlist.value = await listWatchlist()
    groups.value = await listGroups()
    cache.value = await cacheStats()
    healthInfo.value = await health()
  } catch (e) {
    console.error(e)
  }
}

async function doAdd() {
  if (!newCode.value || !newGroup.value) {
    Taro.showToast({ title: '请填写代码和分组', icon: 'none' })
    return
  }
  try {
    await addStock(newCode.value.trim(), newGroup.value.trim(), newNote.value.trim())
    newCode.value = ''
    newGroup.value = ''
    newNote.value = ''
    showAdd.value = false
    Taro.showToast({ title: '已添加', icon: 'success' })
    load()
  } catch (e: any) {
    Taro.showToast({ title: e.message || '添加失败', icon: 'none' })
  }
}

async function doRemove(s: WatchlistStock) {
  try {
    await Taro.showModal({
      title: '确认',
      content: `从 ${s.group} 删除 ${s.code} ${s.name}？`
    }).then(async (res) => {
      if (res.confirm) {
        await removeStock(s.code, s.group)
        Taro.showToast({ title: '已删除', icon: 'success' })
        load()
      }
    })
  } catch (e: any) {
    Taro.showToast({ title: e.message || '删除失败', icon: 'none' })
  }
}

function fmtHitRate(r: number): string {
  return `${(r * 100).toFixed(1)}%`
}

function fmtAge(s: number): string {
  if (s < 60) return `${Math.floor(s)}秒`
  if (s < 3600) return `${Math.floor(s / 60)}分`
  return `${Math.floor(s / 3600)}时${Math.floor((s % 3600) / 60)}分`
}

onMounted(() => {
  load()
  setInterval(load, 30000)
})
</script>

<template>
  <view class="settings-page">
    <view class="header">
      <view class="title">设置</view>
    </view>

    <!-- 服务状态 -->
    <view class="card" v-if="healthInfo">
      <view class="card-title">服务状态</view>
      <view class="card-row">
        <text class="label">数据源</text>
        <text class="value">{{ healthInfo.adapter_name }}</text>
      </view>
      <view class="card-row">
        <text class="label">运行</text>
        <text class="value">{{ Math.floor(healthInfo.uptime_seconds) }}秒</text>
      </view>
      <view class="card-row">
        <text class="label">最后轮询</text>
        <text class="value">
          <text v-if="healthInfo.last_snapshot_at">{{ healthInfo.last_snapshot_at.slice(11, 19) }}</text>
          <text v-else>-</text>
        </text>
      </view>
    </view>

    <!-- 缓存统计 -->
    <view class="card" v-if="cache">
      <view class="card-title">缓存状态</view>
      <view class="card-row">
        <text class="label">命中率</text>
        <text class="value">{{ fmtHitRate(cache.hit_rate) }}</text>
      </view>
      <view class="card-row">
        <text class="label">命中 / 未命中</text>
        <text class="value">{{ cache.hits }} / {{ cache.miss }}</text>
      </view>
      <view class="card-row">
        <text class="label">拉新成功 / 失败</text>
        <text class="value">{{ cache.fetch_ok }} / {{ cache.fetch_fail }}</text>
      </view>
      <view class="freshness-list" v-if="cache.freshness && cache.freshness.length">
        <view class="freshness-title">数据新鲜度</view>
        <view v-for="f in cache.freshness" :key="f.code" class="freshness-row">
          <text class="code">{{ f.code }} {{ f.name }}</text>
          <text class="age">{{ fmtAge(f.age_seconds) }}前</text>
        </view>
      </view>
    </view>

    <!-- 分组 -->
    <view class="card">
      <view class="card-title">分组 ({{ groups.length }})</view>
      <view v-for="g in groups" :key="g.name" class="group-row">
        <text class="group-name">{{ g.name }}</text>
        <text class="group-count">{{ g.n_stocks }} 只</text>
      </view>
    </view>

    <!-- 自选股 -->
    <view class="card">
      <view class="card-title">
        自选股 ({{ watchlist.length }})
        <view class="add-btn" @tap="showAdd = !showAdd">+ 添加</view>
      </view>

      <view v-if="showAdd" class="add-form">
        <input v-model="newCode" placeholder="股票代码 600519" class="input" />
        <input v-model="newGroup" placeholder="分组名 白酒" class="input" />
        <input v-model="newNote" placeholder="备注（可选）" class="input" />
        <button class="submit-btn" @tap="doAdd">保存</button>
      </view>

      <view v-for="s in watchlist" :key="`${s.code}-${s.group}`" class="stock-row">
        <view class="stock-info">
          <text class="stock-name">{{ s.name }}</text>
          <text class="stock-code">{{ s.code }} · {{ s.group }}</text>
        </view>
        <view class="del-btn" @tap="doRemove(s)">删除</view>
      </view>
    </view>

    <!-- Tab bar -->
    <view class="tab-bar">
      <view class="tab-item" @tap="Taro.navigateTo({ url: '/pages/index/index' })">行情</view>
      <view class="tab-item" @tap="Taro.navigateTo({ url: '/pages/signals/index' })">信号</view>
      <view class="tab-item active">设置</view>
    </view>
  </view>
</template>

<style scoped>
.settings-page {
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

.card {
  background: white;
  margin: 16rpx;
  padding: 24rpx;
  border-radius: 12rpx;
}

.card-title {
  font-size: 30rpx;
  font-weight: 600;
  margin-bottom: 16rpx;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.card-row {
  display: flex;
  justify-content: space-between;
  padding: 8rpx 0;
  font-size: 26rpx;
}

.card-row .label { color: #999; }
.card-row .value { color: #333; font-family: 'Courier New', monospace; }

.add-btn {
  background: #c83e3e;
  color: white;
  padding: 8rpx 16rpx;
  border-radius: 8rpx;
  font-size: 24rpx;
}

.freshness-list {
  margin-top: 16rpx;
  border-top: 1rpx solid #eee;
  padding-top: 16rpx;
}

.freshness-title {
  font-size: 24rpx;
  color: #999;
  margin-bottom: 8rpx;
}

.freshness-row {
  display: flex;
  justify-content: space-between;
  font-size: 24rpx;
  padding: 4rpx 0;
}

.freshness-row .code { color: #333; }
.freshness-row .age { color: #666; font-family: 'Courier New', monospace; }

.group-row {
  display: flex;
  justify-content: space-between;
  padding: 12rpx 0;
  border-bottom: 1rpx solid #f5f5f5;
}

.group-name { font-size: 28rpx; }
.group-count { font-size: 24rpx; color: #999; }

.add-form {
  background: #f8f8f8;
  padding: 16rpx;
  border-radius: 8rpx;
  margin-bottom: 16rpx;
}

.input {
  display: block;
  background: white;
  padding: 12rpx;
  border-radius: 6rpx;
  font-size: 26rpx;
  margin-bottom: 8rpx;
  width: 100%;
  box-sizing: border-box;
}

.submit-btn {
  background: #c83e3e;
  color: white;
  padding: 12rpx;
  border-radius: 8rpx;
  font-size: 26rpx;
  width: 100%;
  border: none;
  margin-top: 8rpx;
}

.stock-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12rpx 0;
  border-bottom: 1rpx solid #f5f5f5;
}

.stock-info {
  flex: 1;
}

.stock-name {
  font-size: 28rpx;
  font-weight: 500;
  margin-right: 12rpx;
}

.stock-code {
  font-size: 22rpx;
  color: #999;
}

.del-btn {
  color: #c83e3e;
  font-size: 24rpx;
  padding: 8rpx 16rpx;
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
