<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { apiGet } from '@/api/client'
import { fmtPrice, fmtPct, fmtWan } from '@/utils/format'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Separator } from '@/components/ui/separator'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { cn } from '@/lib/utils'

interface ThemeStock {
  code: string
  name: string
  price: string
  change_pct: string
  volume: number
  turnover_rate: string | null
  pe: string | null
  main_net_inflow: string | null
  subcategory: string
  level: string
  role: string
  growth_text: string
  growth_low: number | null
  growth_high: number | null
  core_driver: string
  highlight: string
  error?: string
}

interface ThemeDetail {
  id: string
  name: string
  description: string
  total_stocks: number
  subcategories: string[]
  stocks: unknown[]
}

type SortKey = 'change' | 'main_net' | 'growth'

const themeIcons: Record<string, string> = {
  semiconductor: '🔧',
  innovative_drug: '💊',
  humanoid_robot: '🤖',
  materials: '🧱',
  earnings_watch: '📊',
}

const router = useRouter()
const route = useRoute()
const themeId = computed(() => route.params.id as string)

const theme = ref<ThemeDetail | null>(null)
const stocks = ref<ThemeStock[]>([])
const loading = ref(true)
const loadingQuotes = ref(false)
const activeSub = ref('')
const sortBy = ref<SortKey>('change')
const sortDir = ref<'desc' | 'asc'>('desc')

const isEarnings = computed(() => themeId.value === 'earnings_watch')

async function loadTheme() {
  loading.value = true
  try {
    theme.value = await apiGet<ThemeDetail>(`/api/themes/${themeId.value}`)
  } catch {
    theme.value = null
  } finally {
    loading.value = false
  }
  await loadQuotes()
}

async function loadQuotes() {
  loadingQuotes.value = true
  try {
    const data = await apiGet<{ items: ThemeStock[]; total: number }>(
      `/api/themes/${themeId.value}/quotes?limit=200`
    )
    stocks.value = data.items
  } catch {
    stocks.value = []
  } finally {
    loadingQuotes.value = false
  }
}

onMounted(loadTheme)
watch(themeId, loadTheme)

// ---------- 过滤 + 排序 ----------

const subcategories = computed(() => {
  if (!theme.value?.subcategories?.length) return []
  return ['全部', ...theme.value.subcategories]
})

const filteredStocks = computed(() => {
  let result = stocks.value
  if (activeSub.value && activeSub.value !== '全部') {
    result = result.filter(
      (s) => s.subcategory === activeSub.value || s.level === activeSub.value
    )
  }
  return [...result].sort((a, b) => {
    let av = 0
    let bv = 0
    if (sortBy.value === 'change') {
      av = Number(a.change_pct) || 0
      bv = Number(b.change_pct) || 0
    } else if (sortBy.value === 'main_net') {
      av = Number(a.main_net_inflow) || 0
      bv = Number(b.main_net_inflow) || 0
    } else if (sortBy.value === 'growth') {
      av = a.growth_low ?? 0
      bv = b.growth_low ?? 0
    }
    return sortDir.value === 'desc' ? bv - av : av - bv
  })
})

// ---------- 概览统计 ----------

const summary = computed(() => {
  const total = stocks.value.length
  if (total === 0) return null
  const up = stocks.value.filter((s) => Number(s.change_pct) > 0).length
  const down = stocks.value.filter((s) => Number(s.change_pct) < 0).length
  const flat = total - up - down
  const avgPct =
    stocks.value.reduce((sum, s) => sum + (Number(s.change_pct) || 0), 0) / total
  const totalMain = stocks.value.reduce(
    (sum, s) => sum + (Number(s.main_net_inflow) || 0),
    0
  )
  return { total, up, down, flat, avgPct, totalMain }
})

// ---------- 子板块统计（按 subcategory/level 分组） ----------

interface SubStat {
  name: string
  count: number
  avgPct: number
}

const subStats = computed<SubStat[]>(() => {
  const map = new Map<string, { count: number; total: number }>()
  for (const s of stocks.value) {
    const key = s.subcategory || s.level || '其他'
    if (!map.has(key)) map.set(key, { count: 0, total: 0 })
    const e = map.get(key)!
    e.count++
    e.total += Number(s.change_pct) || 0
  }
  return Array.from(map.entries())
    .map(([name, v]) => ({ name, count: v.count, avgPct: v.total / v.count }))
    .sort((a, b) => b.avgPct - a.avgPct)
})

// ---------- 排序交互 ----------

function toggleSort(col: SortKey) {
  if (sortBy.value === col) {
    sortDir.value = sortDir.value === 'desc' ? 'asc' : 'desc'
  } else {
    sortBy.value = col
    sortDir.value = 'desc'
  }
}

function sortIcon(col: SortKey): string {
  if (sortBy.value !== col) return ''
  return sortDir.value === 'desc' ? '↓' : '↑'
}

// ---------- 颜色 / 导航 ----------

function pctClass(pct: string | number | null | undefined): string {
  const n = Number(pct)
  if (isNaN(n) || n === 0) return 'text-muted-foreground'
  return n > 0 ? 'text-up' : 'text-down'
}

function growthVariant(low: number | null): 'default' | 'secondary' | 'outline' {
  if (low == null) return 'outline'
  if (low >= 200) return 'default'
  if (low >= 50) return 'secondary'
  return 'outline'
}

function goDetail(code: string) {
  if (/^\d{6}$/.test(code)) router.push({ name: 'detail', params: { code } })
}
</script>

<template>
  <div class="min-h-screen bg-background pb-6">
    <!-- 顶部头部 -->
    <header
      class="bg-gradient-to-br from-primary to-primary/80 text-primary-foreground px-4 py-3"
    >
      <Button
        variant="ghost"
        size="sm"
        class="text-primary-foreground hover:bg-white/10 mb-1 -ml-2"
        @click="router.push('/themes')"
      >
        ← 主题
      </Button>
      <h1 class="text-xl font-bold">
        {{ themeIcons[themeId] || '📈' }}
        {{ theme?.name || (loading ? '加载中…' : '主题不存在') }}
      </h1>
      <p v-if="theme" class="mt-1 text-xs opacity-85 leading-relaxed">
        {{ theme.description }}
      </p>
    </header>

    <div class="p-3 space-y-3">
      <!-- 加载骨架 -->
      <template v-if="loading">
        <Card>
          <CardContent class="p-4 flex gap-6">
            <Skeleton v-for="i in 4" :key="i" class="h-12 w-20" />
          </CardContent>
        </Card>
        <Skeleton class="h-24 w-full" />
      </template>

      <template v-else-if="theme">
        <!-- 概览栏 -->
        <Card v-if="summary">
          <CardContent class="p-4">
            <div class="flex flex-wrap items-center gap-x-8 gap-y-3">
              <div class="flex flex-col gap-0.5">
                <span class="text-xs text-muted-foreground">总数</span>
                <span class="text-lg font-bold font-mono text-card-foreground">
                  {{ summary.total }}
                </span>
              </div>
              <Separator orientation="vertical" class="!h-10" />
              <div class="flex flex-col gap-0.5">
                <span class="text-xs text-muted-foreground">涨/跌/平</span>
                <span class="text-lg font-bold font-mono">
                  <span class="text-up">{{ summary.up }}</span>
                  <span class="text-muted-foreground mx-0.5">/</span>
                  <span class="text-down">{{ summary.down }}</span>
                  <span class="text-muted-foreground mx-0.5">/</span>
                  <span class="text-muted-foreground">{{ summary.flat }}</span>
                </span>
              </div>
              <Separator orientation="vertical" class="!h-10" />
              <div class="flex flex-col gap-0.5">
                <span class="text-xs text-muted-foreground">均价</span>
                <span
                  class="text-lg font-bold font-mono"
                  :class="pctClass(summary.avgPct)"
                >
                  {{ fmtPct(summary.avgPct.toFixed(2)) }}
                </span>
              </div>
              <Separator orientation="vertical" class="!h-10" />
              <div class="flex flex-col gap-0.5">
                <span class="text-xs text-muted-foreground">主力合计</span>
                <span
                  class="text-lg font-bold font-mono"
                  :class="pctClass(summary.totalMain)"
                >
                  {{ fmtWan(summary.totalMain) }}
                </span>
              </div>
            </div>
          </CardContent>
        </Card>

        <!-- 子板块统计 filter chips -->
        <div v-if="subStats.length > 1" class="flex gap-2 overflow-x-auto pb-1">
          <button
            class="flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs whitespace-nowrap transition-colors"
            :class="
              activeSub === '' || activeSub === '全部'
                ? 'border-primary bg-primary/10 text-primary font-semibold'
                : 'border-border bg-card text-muted-foreground hover:border-primary/40'
            "
            @click="activeSub = ''"
          >
            <span class="font-semibold">全部</span>
            <span class="opacity-70">{{ stocks.length }}</span>
          </button>
          <button
            v-for="s in subStats"
            :key="s.name"
            class="flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs whitespace-nowrap transition-colors"
            :class="
              activeSub === s.name
                ? 'border-primary bg-primary/10 text-primary font-semibold'
                : 'border-border bg-card text-muted-foreground hover:border-primary/40'
            "
            @click="activeSub = activeSub === s.name ? '' : s.name"
          >
            <span class="font-semibold">{{ s.name }}</span>
            <span class="opacity-70">{{ s.count }}</span>
            <span class="font-mono font-bold" :class="pctClass(s.avgPct)">
              {{ fmtPct(s.avgPct.toFixed(2)) }}
            </span>
          </button>
        </div>

        <!-- 成分股表格 -->
        <Card>
          <!-- 加载中 -->
          <div v-if="loadingQuotes" class="py-10 text-center text-sm text-muted-foreground">
            拉取行情中…
          </div>

          <!-- 空状态 -->
          <div
            v-else-if="filteredStocks.length === 0"
            class="py-10 text-center"
          >
            <span class="text-3xl">📭</span>
            <p class="mt-1 text-sm text-muted-foreground">暂无数据</p>
          </div>

          <!-- 表格 -->
          <Table v-else>
            <TableHeader>
              <TableRow class="bg-muted/50">
                <TableHead class="text-xs">代码 / 名称</TableHead>
                <TableHead
                  class="text-xs cursor-pointer select-none hover:text-primary whitespace-nowrap"
                  @click="toggleSort('change')"
                >
                  涨跌{{ sortIcon('change') }}
                </TableHead>
                <TableHead
                  class="text-xs cursor-pointer select-none hover:text-primary whitespace-nowrap"
                  @click="toggleSort('main_net')"
                >
                  主力{{ sortIcon('main_net') }}
                </TableHead>
                <TableHead
                  v-if="isEarnings"
                  class="text-xs cursor-pointer select-none hover:text-primary whitespace-nowrap"
                  @click="toggleSort('growth')"
                >
                  预期增速{{ sortIcon('growth') }}
                </TableHead>
                <TableHead class="text-xs">分类</TableHead>
                <TableHead class="text-xs text-right">PE</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              <TableRow
                v-for="s in filteredStocks"
                :key="s.code"
                class="cursor-pointer transition-colors hover:bg-muted/30"
                @click="goDetail(s.code)"
              >
                <!-- 代码/名称 -->
                <TableCell class="py-2.5">
                  <div class="flex items-baseline gap-1.5">
                    <span class="font-mono text-[11px] text-muted-foreground">{{ s.code }}</span>
                    <span class="font-semibold text-sm text-card-foreground">{{ s.name }}</span>
                  </div>
                  <div v-if="s.role" class="text-[11px] text-muted-foreground mt-0.5">
                    {{ s.role }}
                  </div>
                  <div v-if="s.highlight" class="text-[11px] text-amber-600 dark:text-amber-500 mt-0.5">
                    ★ {{ s.highlight }}
                  </div>
                </TableCell>

                <!-- 价格 + 涨跌幅 -->
                <TableCell class="py-2.5 whitespace-nowrap">
                  <div class="font-mono font-semibold text-sm" :class="pctClass(s.change_pct)">
                    {{ fmtPrice(s.price) }}
                  </div>
                  <div
                    class="text-xs font-mono font-semibold mt-0.5"
                    :class="pctClass(s.change_pct)"
                  >
                    {{ fmtPct(s.change_pct) }}
                  </div>
                </TableCell>

                <!-- 主力净流入 -->
                <TableCell class="py-2.5 whitespace-nowrap">
                  <span
                    v-if="s.main_net_inflow"
                    class="font-mono text-sm font-semibold"
                    :class="pctClass(s.main_net_inflow)"
                  >
                    {{ fmtWan(s.main_net_inflow) }}
                  </span>
                  <span v-else class="text-muted-foreground">-</span>
                </TableCell>

                <!-- 中报预期增速 -->
                <TableCell v-if="isEarnings" class="py-2.5">
                  <Badge
                    v-if="s.growth_text"
                    :variant="growthVariant(s.growth_low)"
                    :class="
                      cn(
                        'font-bold',
                        (s.growth_low ?? 0) >= 200 && 'text-up bg-up/10 border-transparent',
                        (s.growth_low ?? 0) >= 50 && (s.growth_low ?? 0) < 200 && 'text-amber-600 bg-amber-500/10 border-transparent dark:text-amber-500'
                      )
                    "
                  >
                    {{ s.growth_text }}
                  </Badge>
                  <span v-else class="text-muted-foreground">-</span>
                  <div v-if="s.core_driver" class="text-[11px] text-muted-foreground mt-0.5">
                    {{ s.core_driver }}
                  </div>
                </TableCell>

                <!-- 分类 -->
                <TableCell class="py-2.5">
                  <Badge
                    v-if="s.subcategory || s.level"
                    variant="outline"
                    class="text-[11px] text-muted-foreground"
                  >
                    {{ s.subcategory || s.level }}
                  </Badge>
                  <span v-else class="text-muted-foreground">-</span>
                </TableCell>

                <!-- PE -->
                <TableCell class="py-2.5 text-right">
                  <span v-if="s.pe" class="font-mono text-xs text-muted-foreground">
                    {{ Number(s.pe).toFixed(1) }}
                  </span>
                  <span v-else class="text-muted-foreground">-</span>
                </TableCell>
              </TableRow>
            </TableBody>
          </Table>
        </Card>
      </template>

      <!-- 主题不存在 -->
      <div v-else class="py-16 text-center">
        <span class="text-4xl">❌</span>
        <p class="mt-2 text-sm text-muted-foreground">主题不存在</p>
        <Button variant="outline" size="sm" class="mt-3" @click="router.push('/themes')">
          返回主题列表
        </Button>
      </div>
    </div>
  </div>
</template>
