<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { listWatchlist, listGroups, addStock, removeStock } from '../../api/watchlist'
import { useTheme } from '../../composables/useTheme'
import { useWatchlistStore } from '../../stores/watchlist'
import { cacheStats, health } from '../../api/cache'
import type { WatchlistStock, WatchlistGroup, CacheStats, Health } from '../../api/types'

const watchlistStore = useWatchlistStore()

const watchlist = ref<WatchlistStock[]>([])
const groups = ref<WatchlistGroup[]>([])
const { themes, currentThemeId, currentTheme, setTheme } = useTheme()
const cache = ref<CacheStats | null>(null)
const healthInfo = ref<Health | null>(null)
const showAdd = ref(false)
const newCode = ref('')
const newGroup = ref('')
const newNote = ref('')
const adding = ref(false)
const removing = ref<string | null>(null)
const refreshing = ref(false)
const lastRefresh = ref<Date>(new Date())

// 分组管理
const showAddGroup = ref(false)
const newGroupName = ref('')
const newGroupDesc = ref('')
const addingGroup = ref(false)
const removingGroup = ref<string | null>(null)
const confirmDelete = ref<string | null>(null)

async function load() {
  try {
    const [w, g, c, h] = await Promise.all([
      listWatchlist(),
      listGroups(),
      cacheStats(),
      health()
    ])
    watchlist.value = w
    groups.value = g
    cache.value = c
    healthInfo.value = h
    lastRefresh.value = new Date()
  } catch (e) {
    console.error(e)
  }
}

async function refreshNow() {
  refreshing.value = true
  await load()
  refreshing.value = false
}

async function doAdd() {
  if (!newCode.value.trim() || !newGroup.value.trim()) {
    alert('⚠️ 请填写代码和分组')
    return
  }
  adding.value = true
  try {
    await addStock(newCode.value.trim(), newGroup.value.trim(), newNote.value.trim())
    newCode.value = ''
    newGroup.value = ''
    newNote.value = ''
    showAdd.value = false
    alert('✅ 已添加')
    load()
  } catch (e: any) {
    alert('❌ ' + (e.message || '添加失败'))
  } finally {
    adding.value = false
  }
}

async function doRemove(s: WatchlistStock) {
  if (!confirm(`从「${s.group}」删除 ${s.code} ${s.name}？`)) return
  removing.value = `${s.code}-${s.group}`
  try {
    await removeStock(s.code, s.group)
    alert('✅ 已删除')
    load()
  } catch (e: any) {
    alert('❌ ' + (e.message || '删除失败'))
  } finally {
    removing.value = null
  }
}

async function doAddGroup() {
  if (!newGroupName.value.trim()) {
    alert('⚠️ 请填写分组名称')
    return
  }
  addingGroup.value = true
  try {
    await watchlistStore.addGroup(newGroupName.value.trim(), newGroupDesc.value.trim() || undefined)
    newGroupName.value = ''
    newGroupDesc.value = ''
    showAddGroup.value = false
    await load()
  } catch (e: any) {
    alert('❌ 新建分组失败: ' + (e.message || e))
  } finally {
    addingGroup.value = false
  }
}

function clickDeleteGroup(name: string) {
  if (confirmDelete.value === name) {
    doRemoveGroup(name)
  } else {
    confirmDelete.value = name
  }
}

async function doRemoveGroup(name: string) {
  removingGroup.value = name
  try {
    await watchlistStore.removeGroup(name)
    confirmDelete.value = null
    await load()
  } catch (e: any) {
    alert('❌ 删除分组失败: ' + (e.message || e))
    confirmDelete.value = null
  } finally {
    removingGroup.value = null
  }
}

function fmtHitRate(r: number): string {
  return `${(r * 100).toFixed(1)}%`
}

function fmtAge(s: number): string {
  if (s < 60) return `${Math.floor(s)}秒`
  if (s < 3600) return `${Math.floor(s / 60)}分`
  if (s < 86400) return `${Math.floor(s / 3600)}时${Math.floor((s % 3600) / 60)}分`
  return `${Math.floor(s / 86400)}天`
}

function fmtLastRefresh(): string {
  const now = new Date()
  const diff = (now.getTime() - lastRefresh.value.getTime()) / 1000
  if (diff < 5) return '刚刚'
  if (diff < 60) return `${Math.floor(diff)}秒前`
  return `${Math.floor(diff / 60)}分钟前`
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
      <div class="header-row">
        <div class="title">设置</div>
        <button class="refresh-btn" @click="refreshNow" :disabled="refreshing">
          <span :class="['refresh-icon', { spinning: refreshing }]">↻</span>
          {{ refreshing ? '刷新中' : '刷新' }}
        </button>
      </div>
      <div class="subtitle">上次刷新 {{ fmtLastRefresh() }}</div>
    </header>

    <!-- 主题选择 -->
    <div class="card">
      <div class="card-title">
        🎨 主题
        <span class="theme-cur-name">{{ currentTheme().name }} · {{ currentTheme().nameEn }}</span>
      </div>
      <div class="theme-grid">
        <div
          v-for="t in themes"
          :key="t.id"
          :class="['theme-item', { active: currentThemeId === t.id }]"
          @click="setTheme(t.id)"
        >
          <div class="theme-preview">
            <span class="ts-c1" :style="{ background: t.colors.primary }"></span>
            <span class="ts-c2" :style="{ background: t.colors.up }"></span>
            <span class="ts-c3" :style="{ background: t.colors.down }"></span>
            <span class="ts-c4" :style="{ background: t.colors.gold }"></span>
          </div>
          <div class="theme-meta">
            <div class="theme-num">{{ t.number }}</div>
            <div class="theme-name">{{ t.name }}</div>
          </div>
        </div>
      </div>
    </div>

    <div class="card" v-if="healthInfo">
      <div class="card-title">🩺 服务状态</div>
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
      <div class="card-title">📦 缓存状态</div>
      <div class="card-row">
        <span class="label">命中率</span>
        <span class="value" :style="{ color: Number(cache.hit_rate) >= 0.8 ? 'var(--color-down)' : 'var(--color-primary)' }">
          {{ fmtHitRate(cache.hit_rate) }}
        </span>
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
      <div class="card-title">
        📂 分组 ({{ groups.length }})
        <span class="add-btn" @click="showAddGroup = !showAddGroup">
          {{ showAddGroup ? '✕ 取消' : '+ 新建' }}
        </span>
      </div>

      <div v-if="showAddGroup" class="add-form">
        <input v-model="newGroupName" placeholder="分组名称（如 白酒）" class="input" />
        <input v-model="newGroupDesc" placeholder="描述（可选）" class="input" />
        <button class="submit-btn" @click="doAddGroup" :disabled="addingGroup">
          {{ addingGroup ? '创建中...' : '创建分组' }}
        </button>
      </div>

      <div v-if="!groups.length" class="empty-hint-card">还没有分组</div>
      <div v-for="g in groups" :key="g.name" class="group-row">
        <div class="group-info">
          <span class="group-name">{{ g.name }}</span>
          <span class="group-desc" v-if="g.description">{{ g.description }}</span>
        </div>
        <div class="group-right">
          <span class="group-count">{{ g.n_stocks }} 只</span>
          <button
            :class="['group-del-btn', { confirming: confirmDelete === g.name }]"
            @click="clickDeleteGroup(g.name)"
            :disabled="removingGroup === g.name"
          >
            {{ removingGroup === g.name ? '删除中' : confirmDelete === g.name ? '确认删除？' : '删除' }}
          </button>
        </div>
      </div>
    </div>

    <div class="card">
      <div class="card-title">
        ⭐ 自选股 ({{ watchlist.length }})
        <span class="add-btn" @click="showAdd = !showAdd">
          {{ showAdd ? '✕ 取消' : '+ 添加' }}
        </span>
      </div>

      <div v-if="showAdd" class="add-form">
        <input v-model="newCode" placeholder="股票代码（如 600519）" class="input" inputmode="numeric" maxlength="6" />
        <input v-model="newGroup" placeholder="分组名（如 白酒，新分组会自动创建）" class="input" />
        <input v-model="newNote" placeholder="备注（可选）" class="input" />
        <button class="submit-btn" @click="doAdd" :disabled="adding">
          {{ adding ? '添加中...' : '保存' }}
        </button>
      </div>

      <div v-if="!watchlist.length" class="empty-hint-card">
        还没有自选股，点击「+ 添加」开始
      </div>

      <div
        v-for="s in watchlist"
        :key="`${s.code}-${s.group}`"
        class="stock-row"
      >
        <div class="stock-info">
          <div class="stock-name">{{ s.name }}</div>
          <div class="stock-code">{{ s.code }} · {{ s.group }}<span v-if="s.note"> · {{ s.note }}</span></div>
        </div>
        <button
          class="del-btn"
          @click="doRemove(s)"
          :disabled="removing === `${s.code}-${s.group}`"
        >
          {{ removing === `${s.code}-${s.group}` ? '删除中' : '删除' }}
        </button>
      </div>
    </div>

    <div class="footer-tip">
      数据来源：东方财富 + 腾讯财经 · 由 Mac mini 本地服务提供
    </div>
  </div>
</template>

<style scoped>
.settings-page {
  min-height: 100vh;
  background: var(--color-bg);
  padding-bottom: 24px;
}

.header {
  background: var(--color-primary);
  color: white;
  padding: 18px 16px 14px;
}

.header-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 4px;
}

.title {
  font-size: 24px;
  font-weight: bold;
}

.refresh-btn {
  background: rgba(255, 255, 255, 0.2);
  color: white;
  border: 1px solid rgba(255, 255, 255, 0.3);
  padding: 6px 14px;
  border-radius: 16px;
  font-size: 13px;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 4px;
}

.refresh-btn:disabled {
  opacity: 0.6;
}

.refresh-btn:active {
  background: rgba(255, 255, 255, 0.3);
}

.refresh-icon {
  display: inline-block;
  font-size: 16px;
  line-height: 1;
}

.spinning {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.subtitle {
  font-size: 12px;
  opacity: 0.85;
}

.card {
  background: white;
  margin: 12px;
  padding: 16px;
  border-radius: 10px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.05);
}

.card-title {
  font-size: 16px;
  font-weight: 700;
  margin-bottom: 12px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.card-row {
  display: flex;
  justify-content: space-between;
  padding: 5px 0;
  font-size: 14px;
}

.card-row .label { color: #999; }
.card-row .value { color: #333; font-family: 'Courier New', monospace; font-weight: 600; }

.add-btn {
  background: var(--color-primary);
  color: white;
  padding: 5px 12px;
  border-radius: 14px;
  font-size: 13px;
  cursor: pointer;
  user-select: none;
  font-weight: 600;
}

.add-btn:active {
  background: var(--color-primary-dark);
}

.empty-hint-card {
  text-align: center;
  padding: 16px;
  color: #999;
  font-size: 13px;
}

.freshness-list {
  margin-top: 12px;
  border-top: 1px solid #f0f0f0;
  padding-top: 12px;
}

.freshness-title {
  font-size: 13px;
  color: #999;
  margin-bottom: 8px;
  font-weight: 600;
}

.freshness-row {
  display: flex;
  justify-content: space-between;
  font-size: 13px;
  padding: 4px 0;
}

.freshness-row .code { color: #333; }
.freshness-row .age {
  color: #666;
  font-family: 'Courier New', monospace;
  font-weight: 600;
}

.group-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 0;
  border-bottom: 1px solid var(--color-bg);
}

.group-row:last-child { border-bottom: none; }

.group-info {
  flex: 1;
  min-width: 0;
}

.group-name { font-size: 15px; font-weight: 500; }

.group-desc {
  display: block;
  font-size: 12px;
  color: #999;
  margin-top: 2px;
}

.group-right {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.group-count {
  font-size: 12px;
  color: #999;
  background: var(--color-bg);
  padding: 2px 8px;
  border-radius: 10px;
}

.group-del-btn {
  color: var(--color-primary);
  font-size: 12px;
  padding: 4px 10px;
  cursor: pointer;
  background: white;
  border: 1px solid var(--color-primary);
  border-radius: 12px;
  font-weight: 600;
  white-space: nowrap;
}

.group-del-btn:active:not(:disabled) {
  background: var(--color-primary);
  color: white;
}

.group-del-btn.confirming {
  background: #c83e3e;
  border-color: #c83e3e;
  color: white;
}

.group-del-btn:disabled {
  opacity: 0.6;
}

.add-form {
  background: #f8f8f8;
  padding: 12px;
  border-radius: 8px;
  margin-bottom: 12px;
}

.input {
  display: block;
  background: white;
  padding: 10px;
  border-radius: 6px;
  font-size: 14px;
  margin-bottom: 8px;
  width: 100%;
  border: 1px solid #ddd;
  font-family: inherit;
  box-sizing: border-box;
}

.input:focus {
  outline: none;
  border-color: var(--color-primary);
}

.submit-btn {
  background: var(--color-primary);
  color: white;
  padding: 10px;
  border-radius: 6px;
  font-size: 14px;
  width: 100%;
  border: none;
  margin-top: 4px;
  cursor: pointer;
  font-weight: 600;
}

.submit-btn:disabled {
  opacity: 0.6;
}

.submit-btn:active:not(:disabled) {
  background: var(--color-primary-dark);
}

.stock-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 0;
  border-bottom: 1px solid var(--color-bg);
}

.stock-row:last-child { border-bottom: none; }

.stock-info {
  flex: 1;
  min-width: 0;
}

.stock-name {
  font-size: 15px;
  font-weight: 600;
  margin-bottom: 2px;
}

.stock-code {
  font-size: 12px;
  color: #999;
}

.del-btn {
  color: var(--color-primary);
  font-size: 13px;
  padding: 6px 14px;
  cursor: pointer;
  background: white;
  border: 1px solid var(--color-primary);
  border-radius: 14px;
  font-weight: 600;
}

.del-btn:active:not(:disabled) {
  background: var(--color-primary);
  color: white;
}

.del-btn:disabled {
  opacity: 0.6;
}

.footer-tip {
  text-align: center;
  color: var(--color-text-muted);
  font-size: 12px;
  padding: 24px 16px;
  line-height: 1.6;
}

/* 主题选择 */
.theme-cur-name {
  font-size: 12px;
  font-weight: normal;
  color: var(--color-text-muted);
}

.theme-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}

.theme-item {
  border: 2px solid var(--color-border);
  border-radius: 8px;
  padding: 8px;
  cursor: pointer;
  user-select: none;
  background: var(--color-card);
}

.theme-item.active {
  border-color: var(--color-primary);
  background: var(--color-bg);
}

.theme-item:active {
  transform: scale(0.98);
}

.theme-preview {
  display: flex;
  gap: 3px;
  margin-bottom: 6px;
}

.ts-c1, .ts-c2, .ts-c3, .ts-c4 {
  flex: 1;
  height: 24px;
  border-radius: 4px;
}

.theme-meta {
  display: flex;
  align-items: baseline;
  gap: 6px;
}

.theme-num {
  font-size: 11px;
  color: var(--color-text-muted);
  font-family: 'Courier New', monospace;
  font-weight: 700;
}

.theme-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text);
}
</style>
