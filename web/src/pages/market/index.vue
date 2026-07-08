<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed } from 'vue'
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
const dataAge = ref(0)
const activeTab = ref('gainers')

let refreshTimer: number | null = null
let ageTimer: number | null = null

async function load() {
  try {
    const [idx, g, l, sec, pf] = await Promise.all([
      getIndexes().catch(() => []),
      getGainers(20).catch(() => []),
      getLosers(20).catch(() => []),
      getSectors(20).catch(() => []),
      getPortfolio().catch(() => null),
    ])
    indexes.value = idx
    gainers.value = g
    losers.value = l
    sectors.value = sec
    portfolio.value = pf
    dataAge.value = 0
  } catch (e) {
    console.error(e)
  } finally {
    loading.value = false
  }
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

const dataDescription = computed(() => {
  if (dataAge.value < 30) return '实时'
  if (dataAge.value < 120) return `${dataAge.value}秒前`
  return `${Math.floor(dataAge.value / 60)}分钟前`
})

onMounted(() => {
  load()
  refreshTimer = window.setInterval(load, 30_000)
  ageTimer = window.setInterval(() => dataAge.value++, 1000)
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
        <span class="text-xs font-mono opacity-85">
          {{ dataDescription }} · 30秒刷新
        </span>
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
      <h2 class="text-sm font-bold text-muted-foreground mb-2 px-1">📈 大盘指数</h2>

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
              暂无数据
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
              暂无数据
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
              暂无数据
            </div>
          </Card>
        </TabsContent>
      </Tabs>
    </section>

    <!-- 加载占位 -->
    <div v-if="loading && indexes.length === 0" class="py-10 text-center text-sm text-muted-foreground">
      盘面加载中...
    </div>
  </div>
</template>