<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { apiGet, apiPost, apiDelete, getApiToken, setApiToken } from '@/api/client'
import { useTheme } from '@/composables/useTheme'
import { useWatchlistStore } from '@/stores/watchlist'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Separator } from '@/components/ui/separator'
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

const watchlist = ref<WatchlistStock[]>([])
const groups = ref<WatchlistGroup[]>([])
const cache = ref<CacheStats | null>(null)
const healthInfo = ref<Health | null>(null)
const loading = ref(true)
const refreshing = ref(false)
const lastRefresh = ref(new Date())
const apiToken = ref(getApiToken())
const tokenSaved = ref(false)

async function saveApiToken() {
  setApiToken(apiToken.value)
  tokenSaved.value = true
  window.setTimeout(() => (tokenSaved.value = false), 2000)
  await load()
}

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

// ---------- 生命周期 ----------
let timer: number | null = null

async function load() {
  try {
    const [w, g, c, h] = await Promise.all([
      apiGet<WatchlistStock[]>('/api/watchlist').catch(() => [] as WatchlistStock[]),
      apiGet<WatchlistGroup[]>('/api/watchlist/groups').catch(() => [] as WatchlistGroup[]),
      apiGet<CacheStats>('/api/cache/stats').catch(() => null),
      apiGet<Health>('/api/health').catch(() => null),
    ])
    watchlist.value = w
    groups.value = g
    cache.value = c
    healthInfo.value = h
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
      <h1 class="text-xl font-bold tracking-tight">⚙️ 设置</h1>
      <div class="flex items-center gap-2">
        <span class="text-xs text-muted-foreground">上次刷新 {{ fmtLastRefresh() }}</span>
        <Button variant="outline" size="sm" :disabled="refreshing" @click="refreshNow">
          <span :class="{ 'animate-spin': refreshing }">↻</span>
          {{ refreshing ? '刷新中' : '刷新' }}
        </Button>
      </div>
    </div>

    <!-- 主题切换 -->
    <Card>
      <CardHeader>
        <CardTitle class="text-base">🎨 主题</CardTitle>
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

    <!-- 访问令牌 -->
    <Card>
      <CardHeader>
        <CardTitle class="text-base">🔐 访问令牌</CardTitle>
        <CardDescription>
          仅保存在当前浏览器会话，关闭标签页后自动清除
        </CardDescription>
      </CardHeader>
      <Separator />
      <CardContent class="space-y-3 pt-4">
        <Input
          v-model="apiToken"
          type="password"
          autocomplete="current-password"
          placeholder="MOMMY_API_TOKEN（本机无认证时可留空）"
          aria-label="Web 访问令牌"
          @keyup.enter="saveApiToken"
        />
        <div class="flex items-center justify-between">
          <span class="text-xs text-muted-foreground">
            {{ tokenSaved ? '已保存并重新连接' : '令牌不会写入项目文件' }}
          </span>
          <Button size="sm" @click="saveApiToken">保存令牌</Button>
        </div>
      </CardContent>
    </Card>

    <!-- 服务状态 -->
    <Card v-if="healthInfo">
      <CardHeader>
        <CardTitle class="text-base">🩺 服务状态</CardTitle>
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
        <CardTitle class="text-base">📦 缓存状态</CardTitle>
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
        <template v-if="cache.freshness && cache.freshness.length">
          <Separator class="my-2" />
          <p class="text-xs font-semibold text-muted-foreground">数据新鲜度</p>
          <div
            v-for="f in cache.freshness"
            :key="f.code"
            class="flex items-center justify-between text-sm"
          >
            <span class="truncate">{{ f.code }} {{ f.name }}</span>
            <span class="ml-2 shrink-0 font-mono font-semibold text-muted-foreground">
              {{ fmtAge(f.age_seconds) }}
            </span>
          </div>
        </template>
      </CardContent>
    </Card>

    <!-- 分组管理 -->
    <Card>
      <CardHeader class="flex flex-row items-center justify-between">
        <div class="flex items-center gap-2">
          <CardTitle class="text-base">📂 分组</CardTitle>
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
          <CardTitle class="text-base">⭐ 自选股</CardTitle>
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
          <div class="min-w-0 flex-1">
            <p class="font-semibold">{{ s.name }}</p>
            <p class="text-xs text-muted-foreground">
              {{ s.code }} · {{ s.group }}<span v-if="s.note"> · {{ s.note }}</span>
            </p>
          </div>
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
          <DialogDescription>填写股票代码、分组和备注</DialogDescription>
        </DialogHeader>
        <div class="space-y-3">
          <Input
            v-model="stockForm.code"
            placeholder="股票代码（如 600519）"
            inputmode="numeric"
            maxlength="6"
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
