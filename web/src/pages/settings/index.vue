<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import {
  apiGet,
  apiPost,
  apiDelete,
} from '@/api/client'
import { getSetupStatus } from '@/api/setup'
import type { SetupStatus } from '@/api/setup'
import { useTheme } from '@/composables/useTheme'
import { useWatchlistStore } from '@/stores/watchlist'
import {
  getPreferences,
  updatePreferences,
  resetPreferences,
  STYLE_PRESETS,
  HOLDING_PERIOD_OPTIONS,
  DRAWDOWN_OPTIONS,
  NOTIFY_SEVERITY_OPTIONS,
  type Preferences,
  type PreferencesUpdate,
  type TradingStyle,
  type HoldingPeriod,
  type DrawdownSensitivity,
  type NotifySeverity,
} from '@/api/preferences'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Separator } from '@/components/ui/separator'
import StockSearch from '@/components/StockSearch.vue'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog'
import type { WatchlistStock, WatchlistGroup, CacheStats, Health } from '@/api/types'

const { currentMode, toggle: toggleTheme } = useTheme()
const watchlistStore = useWatchlistStore()

// ---------- 交易偏好（服务端持有） ----------
const prefs = ref<Preferences | null>(null)
const prefsSaving = ref(false)
const confirmResetPrefs = ref(false)
const newWindowStart = ref('09:30')
const newWindowEnd = ref('15:00')

async function applyPrefsPatch(patch: PreferencesUpdate) {
  prefsSaving.value = true
  try {
    prefs.value = await updatePreferences(patch)
  } catch (e: any) {
    alert('保存偏好失败: ' + (e?.message || e))
  } finally {
    prefsSaving.value = false
  }
}

function selectStyle(style: TradingStyle) {
  if (prefs.value?.style === style) return
  applyPrefsPatch({ style })
}

function setHoldingPeriod(v: unknown) {
  applyPrefsPatch({ holding_period: v as HoldingPeriod })
}

function setDrawdownSensitivity(v: unknown) {
  applyPrefsPatch({ drawdown_sensitivity: v as DrawdownSensitivity })
}

function setNotifyMinSeverity(v: unknown) {
  applyPrefsPatch({ notify_min_severity: v as NotifySeverity })
}

function addReminderWindow() {
  if (!prefs.value || !newWindowStart.value || !newWindowEnd.value) return
  applyPrefsPatch({
    reminder_windows: [
      ...prefs.value.reminder_windows,
      { start: newWindowStart.value, end: newWindowEnd.value },
    ],
  })
}

function removeReminderWindow(index: number) {
  if (!prefs.value) return
  applyPrefsPatch({
    reminder_windows: prefs.value.reminder_windows.filter((_, i) => i !== index),
  })
}

async function resetPrefs() {
  if (!confirmResetPrefs.value) {
    confirmResetPrefs.value = true
    return
  }
  prefsSaving.value = true
  try {
    prefs.value = await resetPreferences()
  } catch (e: any) {
    alert('恢复默认失败: ' + (e?.message || e))
  } finally {
    prefsSaving.value = false
    confirmResetPrefs.value = false
  }
}

const watchlist = ref<WatchlistStock[]>([])
const groups = ref<WatchlistGroup[]>([])
const cache = ref<CacheStats | null>(null)
const healthInfo = ref<Health | null>(null)
const setupStatus = ref<SetupStatus | null>(null)
const loading = ref(true)
const refreshing = ref(false)
const lastRefresh = ref(new Date())

// ---------- 添加自选股 ----------
const showAddStock = ref(false)
const addingStock = ref(false)
const stockForm = ref({ code: '', group: '', note: '' })

function resetStockForm() {
  stockForm.value = { code: '', group: '', note: '' }
}

async function submitAddStock() {
  if (!stockForm.value.code.trim() || !stockForm.value.group.trim()) return
  addingStock.value = true
  try {
    await apiPost('/api/watchlist/stocks', {
      code: stockForm.value.code.trim(),
      group: stockForm.value.group.trim(),
      note: stockForm.value.note.trim() || undefined,
    })
    showAddStock.value = false
    resetStockForm()
    await load()
  } catch (e: any) {
    alert('添加失败: ' + (e?.message || e))
  } finally {
    addingStock.value = false
  }
}

async function removeStock(s: WatchlistStock) {
  if (!confirm(`从「${s.group}」删除 ${s.code} ${s.name}？`)) return
  try {
    await apiDelete(`/api/watchlist/stocks/${s.code}?group=${encodeURIComponent(s.group)}`)
    await load()
  } catch (e: any) {
    alert('删除失败: ' + (e?.message || e))
  }
}

// ---------- 分组管理 ----------
const showAddGroup = ref(false)
const addingGroup = ref(false)
const groupForm = ref({ name: '', description: '' })
const confirmDeleteGroup = ref<string | null>(null)
const removingGroup = ref<string | null>(null)

function resetGroupForm() {
  groupForm.value = { name: '', description: '' }
}

async function submitAddGroup() {
  if (!groupForm.value.name.trim()) return
  addingGroup.value = true
  try {
    await watchlistStore.addGroup(
      groupForm.value.name.trim(),
      groupForm.value.description.trim() || undefined,
    )
    showAddGroup.value = false
    resetGroupForm()
    await load()
  } catch (e: any) {
    alert('新建分组失败: ' + (e?.message || e))
  } finally {
    addingGroup.value = false
  }
}

function clickDeleteGroup(name: string) {
  if (confirmDeleteGroup.value === name) {
    doRemoveGroup(name)
  } else {
    confirmDeleteGroup.value = name
  }
}

async function doRemoveGroup(name: string) {
  removingGroup.value = name
  try {
    await watchlistStore.removeGroup(name)
    confirmDeleteGroup.value = null
    await load()
  } catch (e: any) {
    alert('删除分组失败: ' + (e?.message || e))
    confirmDeleteGroup.value = null
  } finally {
    removingGroup.value = null
  }
}

// ---------- 格式化 ----------
function fmtHitRate(r: number): string {
  return `${(r * 100).toFixed(1)}%`
}

function fmtUptime(s: number): string {
  if (s < 60) return `${Math.floor(s)}秒`
  if (s < 3600) return `${Math.floor(s / 60)}分钟`
  if (s < 86400) return `${Math.floor(s / 3600)}小时${Math.floor((s % 3600) / 60)}分`
  return `${Math.floor(s / 86400)}天`
}

function fmtAge(s: number): string {
  if (s < 60) return `${Math.floor(s)}秒前`
  if (s < 3600) return `${Math.floor(s / 60)}分钟前`
  if (s < 86400) return `${Math.floor(s / 3600)}小时前`
  return `${Math.floor(s / 86400)}天前`
}

function fmtLastRefresh(): string {
  const diff = (Date.now() - lastRefresh.value.getTime()) / 1000
  if (diff < 5) return '刚刚'
  if (diff < 60) return `${Math.floor(diff)}秒前`
  return `${Math.floor(diff / 60)}分钟前`
}

const lastPollTime = computed(() => {
  if (!healthInfo.value?.last_snapshot_at) return '-'
  return healthInfo.value.last_snapshot_at.slice(11, 19)
})

const freshnessPreview = computed(() => {
  const entries = cache.value?.freshness ?? []
  return [...entries].sort((a, b) => a.age_seconds - b.age_seconds).slice(0, 5)
})

const hiddenFreshnessCount = computed(() => {
  return Math.max(0, (cache.value?.freshness.length ?? 0) - freshnessPreview.value.length)
})

// ---------- 生命周期 ----------
let timer: number | null = null

async function load() {
  try {
    const [w, g, c, h, s, p] = await Promise.all([
      apiGet<WatchlistStock[]>('/api/watchlist').catch(() => [] as WatchlistStock[]),
      apiGet<WatchlistGroup[]>('/api/watchlist/groups').catch(() => [] as WatchlistGroup[]),
      apiGet<CacheStats>('/api/cache/stats').catch(() => null),
      apiGet<Health>('/api/health').catch(() => null),
      getSetupStatus().catch(() => null),
      getPreferences().catch(() => null),
    ])
    watchlist.value = w
    groups.value = g
    cache.value = c
    healthInfo.value = h
    setupStatus.value = s
    prefs.value = p
    lastRefresh.value = new Date()
  } catch (e) {
    console.error(e)
  } finally {
    loading.value = false
  }
}

async function refreshNow() {
  refreshing.value = true
  await load()
  refreshing.value = false
}

onMounted(() => {
  load()
  timer = window.setInterval(load, 30_000)
})

onUnmounted(() => {
  if (timer) clearInterval(timer)
})
</script>

<template>
  <div class="mx-auto w-full max-w-3xl space-y-4 p-4 lg:p-6">
    <!-- 页头 -->
    <div class="flex items-center justify-between">
      <h1 class="text-xl font-bold tracking-tight">👤 我的</h1>
      <div class="flex items-center gap-2">
        <span class="text-xs text-muted-foreground">上次刷新 {{ fmtLastRefresh() }}</span>
        <Button variant="outline" size="sm" :disabled="refreshing" @click="refreshNow">
          <span :class="{ 'animate-spin': refreshing }">↻</span>
          {{ refreshing ? '刷新中' : '刷新' }}
        </Button>
      </div>
    </div>

    <!-- 主题切换（始终可见） -->
    <Card>
      <CardHeader>
        <CardTitle as="h2" class="text-base">🎨 主题</CardTitle>
        <CardDescription>深色 / 浅色模式切换</CardDescription>
      </CardHeader>
      <Separator />
      <CardContent class="flex items-center justify-between pt-4">
        <div class="flex items-center gap-2">
          <span class="text-sm font-medium">
            {{ currentMode === 'dark' ? '🌙 深色模式' : '☀️ 浅色模式' }}
          </span>
        </div>
        <Button variant="outline" size="sm" @click="toggleTheme">
          {{ currentMode === 'dark' ? '☀️ 切换到浅色' : '🌙 切换到深色' }}
        </Button>
      </CardContent>
    </Card>

    <!-- 交易偏好（服务端持有） -->
    <Card>
      <CardHeader>
        <CardTitle as="h2" class="text-base">🎯 交易偏好</CardTitle>
        <CardDescription>
          影响今日排序、AI 回答侧重点、默认回测参数与微信提醒；行情数值不随风格改变
        </CardDescription>
      </CardHeader>
      <Separator />
      <CardContent v-if="prefs" class="space-y-4 pt-4">
        <!-- 交易风格 -->
        <div class="space-y-2">
          <button
            v-for="s in STYLE_PRESETS"
            :key="s.id"
            class="flex w-full items-center gap-3 rounded-lg border p-3 text-left transition-colors hover:bg-accent/50"
            :class="prefs.style === s.id ? 'border-primary bg-primary/5' : ''"
            :disabled="prefsSaving"
            @click="selectStyle(s.id)"
          >
            <span class="text-2xl">{{ s.emoji }}</span>
            <div class="min-w-0 flex-1">
              <span class="block text-sm font-semibold">{{ s.label }}</span>
              <span class="block text-xs text-muted-foreground">{{ s.description }}</span>
            </div>
            <span
              v-if="prefs.style === s.id"
              class="size-2 shrink-0 rounded-full bg-primary"
              aria-hidden="true"
            />
          </button>
        </div>

        <Separator />

        <!-- 持有周期 / 回撤敏感度 / 提醒级别 -->
        <div class="space-y-3 text-sm">
          <div class="flex items-center justify-between gap-3">
            <span class="text-muted-foreground">持有周期</span>
            <Select
              :model-value="prefs.holding_period"
              :disabled="prefsSaving"
              @update:model-value="setHoldingPeriod"
            >
              <SelectTrigger class="h-8 w-40">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem v-for="o in HOLDING_PERIOD_OPTIONS" :key="o.id" :value="o.id">
                  {{ o.label }}
                </SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div class="flex items-center justify-between gap-3">
            <span class="text-muted-foreground">回撤敏感度</span>
            <Select
              :model-value="prefs.drawdown_sensitivity"
              :disabled="prefsSaving"
              @update:model-value="setDrawdownSensitivity"
            >
              <SelectTrigger class="h-8 w-40">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem v-for="o in DRAWDOWN_OPTIONS" :key="o.id" :value="o.id">
                  {{ o.label }}
                </SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div class="flex items-center justify-between gap-3">
            <span class="text-muted-foreground">微信提醒最低级别</span>
            <Select
              :model-value="prefs.notify_min_severity"
              :disabled="prefsSaving"
              @update:model-value="setNotifyMinSeverity"
            >
              <SelectTrigger class="h-8 w-40">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem v-for="o in NOTIFY_SEVERITY_OPTIONS" :key="o.id" :value="o.id">
                  {{ o.label }}
                </SelectItem>
              </SelectContent>
            </Select>
          </div>
          <p class="text-xs text-muted-foreground">
            按当前偏好，默认持有约 {{ prefs.default_hold_days }} 天（用于默认回测参数）
          </p>
        </div>

        <Separator />

        <!-- 提醒时段 -->
        <div class="space-y-2">
          <div class="flex items-center justify-between">
            <span class="text-sm text-muted-foreground">提醒时段</span>
            <span v-if="!prefs.reminder_windows.length" class="text-xs text-muted-foreground">
              全天可提醒
            </span>
          </div>
          <div
            v-for="(w, i) in prefs.reminder_windows"
            :key="`${w.start}-${w.end}-${i}`"
            class="flex items-center gap-2"
          >
            <input
              type="time"
              :value="w.start"
              :disabled="prefsSaving"
              class="h-8 flex-1 rounded-md border bg-background px-2 font-mono text-sm"
              @change="applyPrefsPatch({
                reminder_windows: prefs!.reminder_windows.map((item, j) =>
                  j === i ? { ...item, start: ($event.target as HTMLInputElement).value } : item,
                ),
              })"
            />
            <span class="text-xs text-muted-foreground">至</span>
            <input
              type="time"
              :value="w.end"
              :disabled="prefsSaving"
              class="h-8 flex-1 rounded-md border bg-background px-2 font-mono text-sm"
              @change="applyPrefsPatch({
                reminder_windows: prefs!.reminder_windows.map((item, j) =>
                  j === i ? { ...item, end: ($event.target as HTMLInputElement).value } : item,
                ),
              })"
            />
            <Button
              variant="outline"
              size="sm"
              class="h-8 px-2 text-xs hover:text-destructive"
              :disabled="prefsSaving"
              @click="removeReminderWindow(i)"
            >
              删除
            </Button>
          </div>
          <div class="flex items-center gap-2">
            <input
              v-model="newWindowStart"
              type="time"
              :disabled="prefsSaving"
              class="h-8 flex-1 rounded-md border bg-background px-2 font-mono text-sm"
            />
            <span class="text-xs text-muted-foreground">至</span>
            <input
              v-model="newWindowEnd"
              type="time"
              :disabled="prefsSaving"
              class="h-8 flex-1 rounded-md border bg-background px-2 font-mono text-sm"
            />
            <Button
              variant="outline"
              size="sm"
              class="h-8 px-2 text-xs"
              :disabled="prefsSaving || !newWindowStart || !newWindowEnd"
              @click="addReminderWindow"
            >
              添加
            </Button>
          </div>
        </div>

        <Separator />

        <div class="flex items-center justify-between">
          <span class="text-xs text-muted-foreground">
            <template v-if="prefs.updated_at">
              更新于 {{ new Date(prefs.updated_at).toLocaleString('zh-CN') }}
            </template>
          </span>
          <Button
            :variant="confirmResetPrefs ? 'destructive' : 'outline'"
            size="sm"
            :disabled="prefsSaving"
            @click="resetPrefs"
          >
            {{ confirmResetPrefs ? '确认恢复默认？' : '恢复默认' }}
          </Button>
        </div>
      </CardContent>
      <CardContent v-else class="pt-4">
        <p class="py-3 text-center text-sm text-muted-foreground">偏好设置暂不可用</p>
      </CardContent>
    </Card>

    <!-- 配置状态中心 -->
    <Card v-if="setupStatus">
      <CardHeader>
        <CardTitle as="h2" class="text-base">⚙️ 配置状态</CardTitle>
        <CardDescription>数据、AI 与微信通道状态</CardDescription>
      </CardHeader>
      <Separator />
      <CardContent class="space-y-3 pt-4">
        <!-- Data row -->
        <div class="flex items-center justify-between text-sm">
          <span class="text-muted-foreground">数据服务</span>
          <div class="flex items-center gap-2">
            <Badge :variant="setupStatus.data_ok ? 'secondary' : 'destructive'" class="text-xs">
              {{ setupStatus.data_ok ? '正常' : '异常' }}
            </Badge>
          </div>
        </div>
        <!-- AI row -->
        <div class="flex flex-wrap items-center justify-between gap-2 text-sm">
          <span class="min-w-0 flex-1 text-muted-foreground">
            AI 助手
            <span v-if="setupStatus.llm_configured" class="ml-1 font-mono text-xs">
              {{ setupStatus.provider }} / {{ setupStatus.model }}
            </span>
          </span>
          <div class="flex shrink-0 items-center gap-2">
            <Badge :variant="setupStatus.llm_configured ? 'secondary' : 'destructive'" class="text-xs">
              {{ setupStatus.llm_configured ? '已配置' : '未配置' }}
            </Badge>
            <Button as-child variant="outline" size="sm" class="h-7 text-xs">
              <RouterLink :to="{ path: '/setup', query: { step: 'ai', returnTo: '/my' } }">
                重新配置 AI
              </RouterLink>
            </Button>
          </div>
        </div>
        <!-- Weixin row -->
        <div class="flex flex-wrap items-center justify-between gap-2 text-sm">
          <span class="min-w-0 flex-1 text-muted-foreground">微信通道</span>
          <div class="flex shrink-0 items-center gap-2">
            <Badge
              :variant="setupStatus.weixin.connected ? 'secondary' : 'outline'"
              class="text-xs"
            >
              {{ setupStatus.weixin.connected
                ? setupStatus.weixin.online ? '在线' : '已连接·离线'
                : '未连接' }}
            </Badge>
            <Button as-child variant="outline" size="sm" class="h-7 text-xs">
              <RouterLink :to="{ path: '/setup', query: { step: 'weixin', returnTo: '/my' } }">
                {{ setupStatus.weixin.connected ? '重新连接微信' : '连接微信' }}
              </RouterLink>
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>

    <!-- 服务状态 -->
    <Card v-if="healthInfo">
      <CardHeader>
        <CardTitle as="h2" class="text-base">🩺 服务状态</CardTitle>
      </CardHeader>
      <Separator />
      <CardContent class="space-y-2 pt-4">
        <div class="flex items-center justify-between text-sm">
          <span class="text-muted-foreground">数据源</span>
          <span class="font-mono font-semibold">{{ healthInfo.adapter_name }}</span>
        </div>
        <div class="flex items-center justify-between text-sm">
          <span class="text-muted-foreground">运行时长</span>
          <span class="font-mono font-semibold">{{ fmtUptime(healthInfo.uptime_seconds) }}</span>
        </div>
        <div class="flex items-center justify-between text-sm">
          <span class="text-muted-foreground">最后轮询</span>
          <span class="font-mono font-semibold">{{ lastPollTime }}</span>
        </div>
      </CardContent>
    </Card>

    <!-- 缓存状态 -->
    <Card v-if="cache">
      <CardHeader>
        <CardTitle as="h2" class="text-base">📦 缓存状态</CardTitle>
      </CardHeader>
      <Separator />
      <CardContent class="space-y-2 pt-4">
        <div class="flex items-center justify-between text-sm">
          <span class="text-muted-foreground">命中率</span>
          <span
            class="font-mono font-bold"
            :class="Number(cache.hit_rate) >= 0.8 ? 'text-down' : 'text-destructive'"
          >
            {{ fmtHitRate(cache.hit_rate) }}
          </span>
        </div>
        <div class="flex items-center justify-between text-sm">
          <span class="text-muted-foreground">命中 / 未命中</span>
          <span class="font-mono font-semibold">{{ cache.hits }} / {{ cache.miss }}</span>
        </div>
        <div class="flex items-center justify-between text-sm">
          <span class="text-muted-foreground">拉新成功 / 失败</span>
          <span class="font-mono font-semibold">{{ cache.fetch_ok }} / {{ cache.fetch_fail }}</span>
        </div>
        <template v-if="freshnessPreview.length">
          <Separator class="my-2" />
          <p class="text-xs font-semibold text-muted-foreground">数据新鲜度</p>
          <div
            v-for="f in freshnessPreview"
            :key="f.code"
            class="flex items-center justify-between text-sm"
          >
            <span class="truncate">{{ f.code }} {{ f.name }}</span>
            <span class="ml-2 shrink-0 font-mono font-semibold text-muted-foreground">
              {{ fmtAge(f.age_seconds) }}
            </span>
          </div>
          <p v-if="hiddenFreshnessCount" class="text-xs text-muted-foreground">
            仅显示最新 5 条，另有 {{ hiddenFreshnessCount }} 条缓存记录
          </p>
        </template>
      </CardContent>
    </Card>

    <!-- 分组管理 -->
    <Card>
      <CardHeader class="flex flex-row items-center justify-between">
        <div class="flex items-center gap-2">
          <CardTitle as="h2" class="text-base">📂 分组</CardTitle>
          <Badge variant="secondary" class="font-mono">{{ groups.length }}</Badge>
        </div>
        <Button variant="outline" size="sm" @click="showAddGroup = true">
          + 新建
        </Button>
      </CardHeader>
      <Separator />
      <CardContent class="pt-4">
        <div
          v-if="!groups.length"
          class="py-6 text-center text-sm text-muted-foreground"
        >
          还没有分组
        </div>
        <div
          v-for="g in groups"
          :key="g.name"
          class="flex items-center justify-between border-b border-border py-3 last:border-b-0"
        >
          <div class="min-w-0 flex-1">
            <span class="font-medium">{{ g.name }}</span>
            <span v-if="g.description" class="ml-2 text-xs text-muted-foreground">
              {{ g.description }}
            </span>
          </div>
          <div class="flex shrink-0 items-center gap-2">
            <Badge variant="secondary" class="font-mono text-xs">{{ g.n_stocks }} 只</Badge>
            <Button
              :variant="confirmDeleteGroup === g.name ? 'destructive' : 'outline'"
              size="sm"
              class="h-7 px-2 text-xs"
              :disabled="removingGroup === g.name"
              @click="clickDeleteGroup(g.name)"
            >
              {{ removingGroup === g.name ? '删除中' : confirmDeleteGroup === g.name ? '确认删除？' : '删除' }}
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>

    <!-- 自选股 -->
    <Card>
      <CardHeader class="flex flex-row items-center justify-between">
        <div class="flex items-center gap-2">
          <CardTitle as="h2" class="text-base">⭐ 自选股</CardTitle>
          <Badge variant="secondary" class="font-mono">{{ watchlist.length }}</Badge>
        </div>
        <Button variant="outline" size="sm" @click="showAddStock = true">
          + 添加
        </Button>
      </CardHeader>
      <Separator />
      <CardContent class="pt-4">
        <div
          v-if="!watchlist.length"
          class="py-6 text-center text-sm text-muted-foreground"
        >
          还没有自选股，点击「+ 添加」开始
        </div>
        <div
          v-for="s in watchlist"
          :key="`${s.code}-${s.group}`"
          class="flex items-center justify-between border-b border-border py-3 last:border-b-0"
        >
          <RouterLink :to="`/detail/${s.code}`" class="min-w-0 flex-1 rounded-sm hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary">
            <p class="font-semibold">{{ s.name }}</p>
            <p class="text-xs text-muted-foreground">
              {{ s.code }} · {{ s.group }}<span v-if="s.note"> · {{ s.note }}</span>
            </p>
          </RouterLink>
          <Button
            variant="outline"
            size="sm"
            class="h-7 px-3 text-xs hover:text-destructive"
            @click="removeStock(s)"
          >
            删除
          </Button>
        </div>
      </CardContent>
    </Card>

    <p class="pb-4 text-center text-xs text-muted-foreground">
      数据来源：东方财富 + 腾讯财经 · 由 Mac mini 本地服务提供
    </p>

    <!-- 新建分组 Dialog -->
    <Dialog :open="showAddGroup" @update:open="(v: boolean) => (showAddGroup = v)">
      <DialogContent class="max-w-md">
        <DialogHeader>
          <DialogTitle>新建分组</DialogTitle>
          <DialogDescription>输入分组名称和描述（可选）</DialogDescription>
        </DialogHeader>
        <div class="space-y-3">
          <Input v-model="groupForm.name" placeholder="分组名称（如 白酒）" />
          <Input v-model="groupForm.description" placeholder="描述（可选）" />
        </div>
        <DialogFooter>
          <Button variant="outline" @click="showAddGroup = false">取消</Button>
          <Button :disabled="addingGroup || !groupForm.name.trim()" @click="submitAddGroup">
            {{ addingGroup ? '创建中…' : '创建分组' }}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>

    <!-- 添加自选股 Dialog -->
    <Dialog :open="showAddStock" @update:open="(v: boolean) => (showAddStock = v)">
      <DialogContent class="max-w-md">
        <DialogHeader>
          <DialogTitle>添加自选股</DialogTitle>
          <DialogDescription>搜索股票名称或代码，再选择分组</DialogDescription>
        </DialogHeader>
        <div class="space-y-3">
          <StockSearch
            v-model="stockForm.code"
            placeholder="搜索名称或代码（如 贵州茅台）"
          />
          <Select v-model="stockForm.group">
            <SelectTrigger>
              <SelectValue placeholder="选择分组（或直接输入新分组名）" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem
                v-for="g in groups"
                :key="g.name"
                :value="g.name"
              >
                {{ g.name }}
              </SelectItem>
            </SelectContent>
          </Select>
          <Input
            v-model="stockForm.group"
            placeholder="或输入新分组名"
          />
          <Input v-model="stockForm.note" placeholder="备注（可选）" />
        </div>
        <DialogFooter>
          <Button variant="outline" @click="showAddStock = false">取消</Button>
          <Button
            :disabled="addingStock || !stockForm.code.trim() || !stockForm.group.trim()"
            @click="submitAddStock"
          >
            {{ addingStock ? '添加中…' : '保存' }}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  </div>
</template>
