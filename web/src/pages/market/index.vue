<script setup lang="ts">
import { ref, reactive, onMounted, onUnmounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { getIndexes, getGainers, getLosers, getSectors } from '@/api/market'
import { getPortfolio } from '@/api/portfolio'
import { fmtPrice, fmtPct, fmtWan, pnlColor, pnlSign } from '@/utils/format'
import type { IndexQuote, RankingQuote, SectorQuote, PortfolioSummary } from '@/api/types'
import { Card, CardContent } from '@/components/ui/card'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'

const router = useRouter()

const indexes = ref<IndexQuote[]>([])
const gainers = ref<RankingQuote[]>([])
const losers = ref<RankingQuote[]>([])
const sectors = ref<SectorQuote[]>([])
const portfolio = ref<PortfolioSummary | null>(null)

const loading = ref(true)
const activeTab = ref('gainers')
const ageNow = ref(Date.now())

type ResourceKey = 'indexes' | 'gainers' | 'losers' | 'sectors' | 'portfolio'
interface ResourceStatus {
  error: boolean
  updatedAt: number | null
}

const resourceStatus = reactive<Record<ResourceKey, ResourceStatus>>({
  indexes: { error: false, updatedAt: null },
  gainers: { error: false, updatedAt: null },
  losers: { error: false, updatedAt: null },
  sectors: { error: false, updatedAt: null },
  portfolio: { error: false, updatedAt: null },
})

let refreshTimer: number | null = null
let ageTimer: number | null = null

async function refreshResource<T>(
  key: ResourceKey,
  request: () => Promise<T>,
  apply: (value: T) => void,
) {
  try {
    const value = await request()
    apply(value)
    resourceStatus[key].error = false
    resourceStatus[key].updatedAt = Date.now()
  } catch {
    resourceStatus[key].error = true
  }
}

async function load() {
  loading.value = true
  await Promise.all([
    refreshResource('indexes', getIndexes, (value) => { indexes.value = value }),
    refreshResource('gainers', () => getGainers(20), (value) => { gainers.value = value }),
    refreshResource('losers', () => getLosers(20), (value) => { losers.value = value }),
    refreshResource('sectors', () => getSectors(20), (value) => { sectors.value = value }),
    refreshResource('portfolio', getPortfolio, (value) => { portfolio.value = value }),
  ])
  ageNow.value = Date.now()
  loading.value = false
}

function goDetail(code: string) {
  router.push({ name: 'detail', params: { code } })
}

function isUp(pct: string | number | null | undefined): boolean {
  return Number(pct) > 0
}

function isDown(pct: string | number | null | undefined): boolean {
  return Number(pct) < 0
}

function pctClass(pct: string | number | null | undefined): string {
  const n = Number(pct)
  if (isNaN(n) || n === 0) return 'text-muted-foreground'
  return n > 0 ? 'text-up' : 'text-down'
}

const errorCount = computed(() =>
  Object.values(resourceStatus).filter((status) => status.error).length,
)

const pageStatusText = computed(() => {
  if (errorCount.value >= 5) return '离线'
  if (errorCount.value > 0) return `${5 - errorCount.value}/5 数据源正常`
  if (Object.values(resourceStatus).some((status) => status.updatedAt == null)) return '加载中…'
  return '全部数据源正常'
})

const activeRankingKey = computed<ResourceKey>(() => {
  if (activeTab.value === 'losers') return 'losers'
  if (activeTab.value === 'sectors') return 'sectors'
  return 'gainers'
})

function resourceStatusText(key: ResourceKey): string {
  const status = resourceStatus[key]
  if (status.updatedAt == null) return status.error ? '加载失败' : '加载中…'

  const age = Math.max(0, Math.floor((ageNow.value - status.updatedAt) / 1000))
  let freshness = '实时'
  if (age >= 120) freshness = `${Math.floor(age / 60)}分钟前`
  else if (age >= 30) freshness = `${age}秒前`

  return status.error ? `刷新失败 · ${freshness}` : freshness
}

function resourceStatusClass(key: ResourceKey): string {
  const status = resourceStatus[key]
  if (!status.error) return 'text-muted-foreground'
  return status.updatedAt == null ? 'text-destructive' : 'text-yellow-600 dark:text-yellow-300'
}

onMounted(() => {
  load()
  refreshTimer = window.setInterval(load, 30_000)
  ageTimer = window.setInterval(() => { ageNow.value = Date.now() }, 1000)
})

onUnmounted(() => {
  if (refreshTimer) clearInterval(refreshTimer)
  if (ageTimer) clearInterval(ageTimer)
})
</script>

<template>
  <div class="min-h-screen bg-background pb-6">
    <!-- 顶部头部 -->
    <header
      class="bg-gradient-to-br from-primary to-primary/80 text-primary-foreground px-4 pt-4 pb-0"
    >
      <div class="flex items-baseline justify-between mb-3">
        <h1 class="text-2xl font-bold">📊 盘面</h1>
        <div class="flex items-center gap-1.5">
          <span class="inline-block w-2 h-2 rounded-full" :class="loading ? 'animate-pulse bg-yellow-500' : errorCount >= 5 ? 'bg-red-500' : errorCount > 0 ? 'bg-yellow-500' : 'bg-green-500'" />
          <span class="text-xs font-mono opacity-85">
            {{ pageStatusText }} · 30秒刷新
          </span>
        </div>
      </div>

      <!-- 持仓快览条 -->
      <div
        v-if="portfolio && portfolio.n_positions > 0"
        class="flex items-center justify-between rounded-xl bg-white/10 px-3 py-2.5 mb-3 cursor-pointer transition-colors hover:bg-white/20"
        @click="router.push('/portfolio')"
      >
        <div class="flex items-center gap-1.5">
          <span class="text-base">💰</span>
          <span class="text-sm">持仓</span>
          <Badge variant="secondary" class="text-xs">{{ portfolio.n_positions }}</Badge>
          <span
            v-if="resourceStatus.portfolio.error"
            class="text-xs text-yellow-200"
          >
            {{ resourceStatusText('portfolio') }}
          </span>
        </div>
        <div class="flex items-center gap-2">
          <span class="text-sm font-bold font-mono text-primary-foreground">
            {{ fmtWan(portfolio.total_market_value) }}
          </span>
          <span
            class="text-sm font-semibold font-mono"
            :style="{ color: pnlColor(portfolio.total_unrealized_pnl) }"
          >
            {{ pnlSign(portfolio.total_unrealized_pnl)
            }}{{ fmtWan(portfolio.total_unrealized_pnl) }}
            ({{ fmtPct(portfolio.total_unrealized_pnl_pct || '0') }})
          </span>
          <span class="text-lg text-white/50">›</span>
        </div>
      </div>
    </header>

    <!-- 大盘指数卡片 -->
    <section class="p-3">
      <div class="mb-2 flex items-center justify-between px-1">
        <h2 class="text-sm font-bold text-muted-foreground">📈 大盘指数</h2>
        <span class="text-xs font-mono" :class="resourceStatusClass('indexes')">
          {{ resourceStatusText('indexes') }}
        </span>
      </div>

      <!-- Skeleton 加载态 -->
      <div v-if="loading && indexes.length === 0" class="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
        <Card v-for="i in 4" :key="i">
          <CardContent class="p-3 space-y-2">
            <Skeleton class="h-3 w-16" />
            <Skeleton class="h-6 w-24" />
            <Skeleton class="h-4 w-20" />
          </CardContent>
        </Card>
      </div>

      <div v-else class="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
        <Card
          v-for="idx in indexes.slice(0, 6)"
          :key="idx.code"
          class="overflow-hidden border-l-4"
          :class="isUp(idx.change_pct) ? 'border-l-up' : isDown(idx.change_pct) ? 'border-l-down' : 'border-l-border'"
        >
          <CardContent class="p-3">
            <p class="text-xs text-muted-foreground mb-1">{{ idx.name }}</p>
            <p class="text-lg font-bold font-mono text-card-foreground">
              {{ fmtPrice(idx.price) }}
            </p>
            <p class="text-sm font-bold font-mono" :class="pctClass(idx.change_pct)">
              {{ fmtPct(idx.change_pct) }}
            </p>
          </CardContent>
        </Card>
      </div>

      <!-- 额外指数行（超过6个时） -->
      <div
        v-if="indexes.length > 6"
        class="mt-3 rounded-lg border border-border p-2"
      >
        <div
          v-for="idx in indexes.slice(6)"
          :key="idx.code"
          class="flex items-center justify-between py-1.5 text-xs"
        >
          <span class="text-muted-foreground">{{ idx.name }}</span>
          <div class="flex items-center gap-4">
            <span class="font-mono font-semibold text-card-foreground">{{ fmtPrice(idx.price) }}</span>
            <span class="font-mono font-bold w-16 text-right" :class="pctClass(idx.change_pct)">
              {{ fmtPct(idx.change_pct) }}
            </span>
          </div>
        </div>
      </div>
    </section>

    <!-- Tab 切换：涨幅 / 跌幅 / 板块 -->
    <section class="px-3">
      <Tabs v-model="activeTab" default-value="gainers" class="w-full">
        <TabsList class="grid w-full grid-cols-3">
          <TabsTrigger value="gainers" class="text-xs">🔥 涨幅榜</TabsTrigger>
          <TabsTrigger value="losers" class="text-xs">💧 跌幅榜</TabsTrigger>
          <TabsTrigger value="sectors" class="text-xs">🏭 板块榜</TabsTrigger>
        </TabsList>

        <div class="mt-2 text-right text-xs font-mono" :class="resourceStatusClass(activeRankingKey)">
          {{ resourceStatusText(activeRankingKey) }}
        </div>

        <!-- 涨幅榜 -->
        <TabsContent value="gainers">
          <Card>
            <Table>
              <TableHeader>
                <TableRow class="bg-muted/50">
                  <TableHead class="w-10 text-center text-xs">#</TableHead>
                  <TableHead class="text-xs">名称</TableHead>
                  <TableHead class="text-right text-xs">最新</TableHead>
                  <TableHead class="text-right text-xs">涨幅</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                <TableRow
                  v-for="(item, i) in gainers"
                  :key="item.code"
                  class="cursor-pointer transition-colors hover:bg-muted/30"
                  @click="goDetail(item.code)"
                >
                  <TableCell class="text-center">
                    <span
                      :class="[
                        'font-mono font-bold text-sm',
                        i < 3
                          ? 'inline-flex items-center justify-center w-5 h-5 rounded-full bg-primary/10 text-primary'
                          : 'text-muted-foreground',
                      ]"
                    >
                      {{ i + 1 }}
                    </span>
                  </TableCell>
                  <TableCell>
                    <div class="font-semibold text-sm text-card-foreground truncate max-w-[100px]">
                      {{ item.name }}
                    </div>
                    <div class="text-[10px] text-muted-foreground">{{ item.code }}</div>
                  </TableCell>
                  <TableCell class="text-right font-mono font-semibold text-sm">
                    {{ fmtPrice(item.price) }}
                  </TableCell>
                  <TableCell class="text-right font-mono font-bold text-sm text-up">
                    {{ fmtPct(item.change_pct) }}
                  </TableCell>
                </TableRow>
              </TableBody>
            </Table>
            <div v-if="!loading && gainers.length === 0" class="py-8 text-center text-sm text-muted-foreground">
              {{ resourceStatus.gainers.error ? '涨幅榜加载失败' : '暂无数据' }}
            </div>
          </Card>
        </TabsContent>

        <!-- 跌幅榜 -->
        <TabsContent value="losers">
          <Card>
            <Table>
              <TableHeader>
                <TableRow class="bg-muted/50">
                  <TableHead class="w-10 text-center text-xs">#</TableHead>
                  <TableHead class="text-xs">名称</TableHead>
                  <TableHead class="text-right text-xs">最新</TableHead>
                  <TableHead class="text-right text-xs">跌幅</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                <TableRow
                  v-for="(item, i) in losers"
                  :key="item.code"
                  class="cursor-pointer transition-colors hover:bg-muted/30"
                  @click="goDetail(item.code)"
                >
                  <TableCell class="text-center">
                    <span
                      :class="[
                        'font-mono font-bold text-sm',
                        i < 3
                          ? 'inline-flex items-center justify-center w-5 h-5 rounded-full bg-down/10 text-down'
                          : 'text-muted-foreground',
                      ]"
                    >
                      {{ i + 1 }}
                    </span>
                  </TableCell>
                  <TableCell>
                    <div class="font-semibold text-sm text-card-foreground truncate max-w-[100px]">
                      {{ item.name }}
                    </div>
                    <div class="text-[10px] text-muted-foreground">{{ item.code }}</div>
                  </TableCell>
                  <TableCell class="text-right font-mono font-semibold text-sm">
                    {{ fmtPrice(item.price) }}
                  </TableCell>
                  <TableCell class="text-right font-mono font-bold text-sm text-down">
                    {{ fmtPct(item.change_pct) }}
                  </TableCell>
                </TableRow>
              </TableBody>
            </Table>
            <div v-if="!loading && losers.length === 0" class="py-8 text-center text-sm text-muted-foreground">
              {{ resourceStatus.losers.error ? '跌幅榜加载失败' : '暂无数据' }}
            </div>
          </Card>
        </TabsContent>

        <!-- 板块榜 -->
        <TabsContent value="sectors">
          <Card>
            <Table>
              <TableHeader>
                <TableRow class="bg-muted/50">
                  <TableHead class="w-10 text-center text-xs">#</TableHead>
                  <TableHead class="text-xs">板块</TableHead>
                  <TableHead class="text-right text-xs">点位</TableHead>
                  <TableHead class="text-right text-xs">涨幅</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                <TableRow
                  v-for="(item, i) in sectors"
                  :key="item.code"
                  class="transition-colors hover:bg-muted/30"
                >
                  <TableCell class="text-center">
                    <span
                      :class="[
                        'font-mono font-bold text-sm',
                        i < 3
                          ? 'inline-flex items-center justify-center w-5 h-5 rounded-full bg-primary/10 text-primary'
                          : 'text-muted-foreground',
                      ]"
                    >
                      {{ i + 1 }}
                    </span>
                  </TableCell>
                  <TableCell>
                    <div class="font-semibold text-sm text-card-foreground truncate max-w-[100px]">
                      {{ item.name }}
                    </div>
                    <div class="text-[10px] text-muted-foreground">{{ item.code }}</div>
                  </TableCell>
                  <TableCell class="text-right font-mono font-semibold text-sm">
                    {{ fmtPrice(item.price) }}
                  </TableCell>
                  <TableCell class="text-right font-mono font-bold text-sm" :class="pctClass(item.change_pct)">
                    {{ fmtPct(item.change_pct) }}
                  </TableCell>
                </TableRow>
              </TableBody>
            </Table>
            <div v-if="!loading && sectors.length === 0" class="py-8 text-center text-sm text-muted-foreground">
              {{ resourceStatus.sectors.error ? '板块榜加载失败' : '暂无数据' }}
            </div>
          </Card>
        </TabsContent>
      </Tabs>
    </section>

    <!-- 加载占位 -->
    <div v-if="loading && indexes.length === 0" class="py-10 text-center text-sm text-muted-foreground">
      盘面加载中…
    </div>
  </div>
</template>
