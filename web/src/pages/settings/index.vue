<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { listWatchlist, listGroups, addStock, removeStock } from '../../api/watchlist'
import { cacheStats, health } from '../../api/cache'
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
  if (!newCode.value.trim() || !newGroup.value.trim()) {
    alert('请填写代码和分组')
    return
  }
  try {
    await addStock(newCode.value.trim(), newGroup.value.trim(), newNote.value.trim())
    newCode.value = ''
    newGroup.value = ''
    newNote.value = ''
    showAdd.value = false
    alert('已添加')
    load()
  } catch (e: any) {
    alert(e.message || '添加失败')
  }
}

async function doRemove(s: WatchlistStock) {
  if (!confirm(`从 ${s.group} 删除 ${s.code} ${s.name}？`)) return
  try {
    await removeStock(s.code, s.group)
    alert('已删除')
    load()
  } catch (e: any) {
    alert(e.message || '删除失败')
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

let timer: number | null = null

onMounted(() => {
  load()
  timer = window.setInterval(load, 30000)
})

onUnmounted(() => {
  if (timer) clearInterval(timer)
})
</script>

<template>
  <div class="settings-page">
    <header class="header">
      <div class="title">设置</div>
    </header>

    <div class="card" v-if="healthInfo">
      <div class="card-title">服务状态</div>
      <div class="card-row">
        <span class="label">数据源</span>
        <span class="value">{{ healthInfo.adapter_name }}</span>
      </div>
      <div class="card-row">
        <span class="label">运行</span>
        <span class="value">{{ Math.floor(healthInfo.uptime_seconds) }}秒</span>
      </div>
      <div class="card-row">
        <span class="label">最后轮询</span>
        <span class="value">
          <span v-if="healthInfo.last_snapshot_at">{{ healthInfo.last_snapshot_at.slice(11, 19) }}</span>
          <span v-else>-</span>
        </span>
      </div>
    </div>

    <div class="card" v-if="cache">
      <div class="card-title">缓存状态</div>
      <div class="card-row">
        <span class="label">命中率</span>
        <span class="value">{{ fmtHitRate(cache.hit_rate) }}</span>
      </div>
      <div class="card-row">
        <span class="label">命中 / 未命中</span>
        <span class="value">{{ cache.hits }} / {{ cache.miss }}</span>
      </div>
      <div class="card-row">
        <span class="label">拉新成功 / 失败</span>
        <span class="value">{{ cache.fetch_ok }} / {{ cache.fetch_fail }}</span>
      </div>
      <div class="freshness-list" v-if="cache.freshness && cache.freshness.length">
        <div class="freshness-title">数据新鲜度</div>
        <div v-for="f in cache.freshness" :key="f.code" class="freshness-row">
          <span class="code">{{ f.code }} {{ f.name }}</span>
          <span class="age">{{ fmtAge(f.age_seconds) }}前</span>
        </div>
      </div>
    </div>

    <div class="card">
      <div class="card-title">分组 ({{ groups.length }})</div>
      <div v-for="g in groups" :key="g.name" class="group-row">
        <span class="group-name">{{ g.name }}</span>
        <span class="group-count">{{ g.n_stocks }} 只</span>
      </div>
    </div>

    <div class="card">
      <div class="card-title">
        自选股 ({{ watchlist.length }})
        <span class="add-btn" @click="showAdd = !showAdd">+ 添加</span>
      </div>

      <div v-if="showAdd" class="add-form">
        <input v-model="newCode" placeholder="股票代码 600519" class="input" />
        <input v-model="newGroup" placeholder="分组名 白酒" class="input" />
        <input v-model="newNote" placeholder="备注（可选）" class="input" />
        <button class="submit-btn" @click="doAdd">保存</button>
      </div>

      <div v-for="s in watchlist" :key="`${s.code}-${s.group}`" class="stock-row">
        <div class="stock-info">
          <span class="stock-name">{{ s.name }}</span>
          <span class="stock-code">{{ s.code }} · {{ s.group }}</span>
        </div>
        <span class="del-btn" @click="doRemove(s)">删除</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.settings-page {
  min-height: 100vh;
  background: #f5f5f5;
}

.header {
  background: #c83e3e;
  color: white;
  padding: 20px 16px 16px;
}

.title {
  font-size: 24px;
  font-weight: bold;
}

.card {
  background: white;
  margin: 10px;
  padding: 16px;
  border-radius: 8px;
}

.card-title {
  font-size: 16px;
  font-weight: 600;
  margin-bottom: 12px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.card-row {
  display: flex;
  justify-content: space-between;
  padding: 4px 0;
  font-size: 14px;
}

.card-row .label { color: #999; }
.card-row .value { color: #333; font-family: 'Courier New', monospace; }

.add-btn {
  background: #c83e3e;
  color: white;
  padding: 4px 10px;
  border-radius: 6px;
  font-size: 13px;
  cursor: pointer;
  user-select: none;
}

.freshness-list {
  margin-top: 12px;
  border-top: 1px solid #eee;
  padding-top: 12px;
}

.freshness-title {
  font-size: 13px;
  color: #999;
  margin-bottom: 6px;
}

.freshness-row {
  display: flex;
  justify-content: space-between;
  font-size: 13px;
  padding: 2px 0;
}

.freshness-row .code { color: #333; }
.freshness-row .age { color: #666; font-family: 'Courier New', monospace; }

.group-row {
  display: flex;
  justify-content: space-between;
  padding: 8px 0;
  border-bottom: 1px solid #f5f5f5;
}

.group-name { font-size: 15px; }
.group-count { font-size: 13px; color: #999; }

.add-form {
  background: #f8f8f8;
  padding: 12px;
  border-radius: 6px;
  margin-bottom: 12px;
}

.input {
  display: block;
  background: white;
  padding: 8px;
  border-radius: 4px;
  font-size: 14px;
  margin-bottom: 6px;
  width: 100%;
  border: 1px solid #ddd;
  font-family: inherit;
  box-sizing: border-box;
}

.submit-btn {
  background: #c83e3e;
  color: white;
  padding: 8px;
  border-radius: 6px;
  font-size: 14px;
  width: 100%;
  border: none;
  margin-top: 4px;
  cursor: pointer;
}

.stock-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 0;
  border-bottom: 1px solid #f5f5f5;
}

.stock-info {
  flex: 1;
}

.stock-name {
  font-size: 15px;
  font-weight: 500;
  margin-right: 8px;
}

.stock-code {
  font-size: 12px;
  color: #999;
}

.del-btn {
  color: #c83e3e;
  font-size: 13px;
  padding: 4px 10px;
  cursor: pointer;
}
</style>
