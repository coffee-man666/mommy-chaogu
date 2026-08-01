<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { RouterLink } from 'vue-router'
import { Send, TrendingUp, Wallet, AlertTriangle, ChevronRight, RefreshCw, Star, UserRound } from 'lucide-vue-next'
import {
  getOverview,
  type OverviewResponse,
  type BlockStatus,
} from '@/api/overview'
import { fmtPrice, fmtPct, fmtWan, changeColor } from '@/utils/format'
import { toApiError } from '@/api/client'
import ErrorState from '@/components/ErrorState.vue'

const router = useRouter()

const data = ref<OverviewResponse | null>(null)
const loading = ref(true)
const refreshing = ref(false)
const error = ref('')
const aiInput = ref('')

let pollTimer: ReturnType<typeof setInterval> | null = null

async function loadData(silent = false) {
  if (silent) {
    refreshing.value = true
  } else {
    loading.value = true
  }
  error.value = ''
  try {
    data.value = await getOverview()
  } catch (e) {
    const apiErr = toApiError(e, '加载今日概览')
    error.value = apiErr.friendly
  } finally {
    loading.value = false
    refreshing.value = false
  }
}

function sendAI() {
  const q = aiInput.value.trim()
  if (!q) return
  router.push({ path: '/chat', query: { q } })
}

function blockLabel(block: BlockStatus): string {
  if (block.status === 'ok') return ''
  if (block.status === 'stale') return '数据可能过期'
  return '数据不可用'
}

function basketAsOf(value: string | null): string {
  if (!value) return '暂无时间'
  return new Intl.DateTimeFormat('zh-CN', { hour: '2-digit', minute: '2-digit' }).format(new Date(value))
}

onMounted(() => {
  loadData()
  // 30 秒轮询刷新
  pollTimer = setInterval(() => loadData(true), 30_000)
})

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
})
</script>

<template>
  <div class="mx-auto max-w-4xl px-4 py-4 pb-24 md:pb-8">
    <!-- Header -->
    <div class="mb-4 flex items-center justify-between">
      <h1 class="text-xl font-bold">今日</h1>
      <div class="flex items-center gap-2">
        <!-- Mobile: My entry via avatar -->
        <RouterLink
          to="/my"
          class="flex size-8 items-center justify-center rounded-full bg-accent text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary md:hidden"
          aria-label="我的设置"
        >
          <UserRound class="size-4" aria-hidden="true" />
        </RouterLink>
        <button
          class="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary disabled:opacity-50"
          :disabled="refreshing"
          @click="loadData()"
        >
          <RefreshCw class="size-4" :class="{ 'animate-spin': refreshing }" aria-hidden="true" />
          刷新
        </button>
      </div>
    </div>

    <!-- Loading skeleton -->
    <div v-if="loading" class="space-y-4">
      <div class="h-20 animate-pulse rounded-xl bg-muted" />
      <div class="h-40 animate-pulse rounded-xl bg-muted" />
      <div class="h-32 animate-pulse rounded-xl bg-muted" />
    </div>

    <!-- Error -->
    <ErrorState v-else-if="error && !data" :message="error" @retry="loadData()" />

    <!-- Content -->
    <div v-else-if="data" class="space-y-4">
      <!-- 1. 紧凑指数条 -->
      <section class="rounded-xl border bg-card p-4">
        <div
          v-if="data.indexes.block.status === 'unavailable'"
          class="py-4 text-center text-sm text-muted-foreground"
        >
          {{ data.indexes.block.message || '指数数据暂时不可用' }}
        </div>
        <div v-else class="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <div
            v-for="idx in data.indexes.indexes"
            :key="idx.name"
            class="flex flex-col gap-0.5"
          >
            <span class="text-xs text-muted-foreground">{{ idx.name }}</span>
            <span class="font-mono text-sm font-semibold" :style="{ color: changeColor(idx.change_pct) }">
              {{ fmtPrice(idx.price) }}
            </span>
            <span class="font-mono text-xs" :style="{ color: changeColor(idx.change_pct) }">
              {{ fmtPct(idx.change_pct) }}
            </span>
          </div>
        </div>
      </section>

      <!-- 2. 关注主题/篮子 -->
      <section class="rounded-xl border bg-card p-4">
        <div class="mb-3 flex items-center justify-between">
          <h2 class="text-sm font-semibold text-muted-foreground">关注篮子</h2>
          <RouterLink
            class="flex items-center gap-1 rounded text-xs text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
            to="/follow"
          >
            <Star class="size-3" aria-hidden="true" />
            管理
          </RouterLink>
        </div>
        <div
          v-if="data.themes.items.length === 0"
          class="py-3 text-center text-sm text-muted-foreground"
        >
          {{ data.themes.block.message || '还没有关注篮子' }}
        </div>
        <div v-else class="grid grid-cols-2 gap-2">
          <RouterLink
            v-for="basket in data.themes.items"
            :key="basket.id"
            :to="`/baskets/${encodeURIComponent(basket.id)}`"
            class="min-w-0 rounded-lg border p-2.5 transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
          >
            <div class="flex items-center justify-between gap-2">
              <span class="truncate text-sm font-medium">{{ basket.name }}</span>
              <span class="shrink-0 font-mono text-sm font-semibold" :style="{ color: changeColor(basket.change_pct) }">
                {{ fmtPct(basket.change_pct) }}
              </span>
            </div>
            <p v-if="basket.leader" class="mt-1 truncate text-xs text-muted-foreground">
              领涨 {{ basket.leader.name }}
              <span :style="{ color: changeColor(basket.leader.change_pct) }">{{ fmtPct(basket.leader.change_pct) }}</span>
            </p>
            <p v-if="basket.laggard" class="truncate text-xs text-muted-foreground">
              领跌 {{ basket.laggard.name }}
              <span :style="{ color: changeColor(basket.laggard.change_pct) }">{{ fmtPct(basket.laggard.change_pct) }}</span>
            </p>
            <p v-if="basket.anomaly" class="mt-1 truncate text-xs text-orange-600 dark:text-orange-300">
              {{ basket.anomaly }}
            </p>
            <p v-else-if="basket.reason" class="mt-1 truncate text-xs text-muted-foreground">{{ basket.reason }}</p>
            <p class="mt-1 text-[11px] text-muted-foreground">
              {{ basket.total_stocks }}只 ·
              <span v-if="basket.status === 'stale'">旧数据 · </span>
              <span v-else-if="basket.status === 'unavailable'">行情不可用 · </span>
              {{ basketAsOf(basket.as_of) }}
            </p>
          </RouterLink>
        </div>
      </section>

      <!-- 3. 自选股 -->
      <section class="rounded-xl border bg-card p-4">
        <div class="mb-3 flex items-center justify-between">
          <div class="flex items-center gap-2">
            <h2 class="text-sm font-semibold">自选股</h2>
            <span v-if="data.watchlist.total > 0" class="text-xs text-muted-foreground">
              {{ data.watchlist.n_up }}红 {{ data.watchlist.n_down }}绿
            </span>
          </div>
          <span v-if="blockLabel(data.watchlist.block)" class="text-xs text-orange-500">
            {{ blockLabel(data.watchlist.block) }}
          </span>
        </div>

        <div v-if="data.watchlist.items.length === 0" class="py-4 text-center text-sm text-muted-foreground">
          暂无自选股
        </div>

        <!-- 桌面紧凑表格 -->
        <table v-else class="hidden w-full text-sm md:table">
          <thead>
            <tr class="border-b text-xs text-muted-foreground">
              <th class="py-1.5 text-left font-normal">名称</th>
              <th class="py-1.5 text-right font-normal">现价</th>
              <th class="py-1.5 text-right font-normal">涨跌</th>
              <th class="py-1.5 text-right font-normal">分组</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="item in data.watchlist.items"
              :key="item.code"
              class="border-b last:border-0 transition-colors hover:bg-accent/50"
            >
              <td class="py-1.5">
                <RouterLink
                  :to="`/detail/${item.code}`"
                  class="font-medium hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
                >
                  {{ item.name || item.code }}
                </RouterLink>
                <span class="ml-1 text-xs text-muted-foreground">{{ item.code }}</span>
              </td>
              <td class="py-1.5 text-right font-mono">{{ fmtPrice(item.price) }}</td>
              <td
                class="py-1.5 text-right font-mono font-medium"
                :style="{ color: changeColor(item.change_pct) }"
              >
                {{ fmtPct(item.change_pct) }}
              </td>
              <td class="py-1.5 text-right text-xs text-muted-foreground">{{ item.group }}</td>
            </tr>
          </tbody>
        </table>

        <!-- 移动端卡片 -->
        <div class="grid grid-cols-2 gap-2 md:hidden">
          <RouterLink
            v-for="item in data.watchlist.items"
            :key="item.code"
            :to="`/detail/${item.code}`"
            class="flex flex-col gap-0.5 rounded-lg border p-2.5 text-left transition-colors hover:bg-accent/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
          >
            <span class="truncate text-sm font-medium">{{ item.name || item.code }}</span>
            <span class="font-mono text-sm" :style="{ color: changeColor(item.change_pct) }">
              {{ fmtPrice(item.price) }}
            </span>
            <span class="font-mono text-xs" :style="{ color: changeColor(item.change_pct) }">
              {{ fmtPct(item.change_pct) }}
            </span>
          </RouterLink>
        </div>
      </section>

      <!-- 4. 持仓提醒 -->
      <section class="rounded-xl border bg-card p-4">
        <div class="mb-3 flex items-center gap-2">
          <Wallet class="size-4 text-muted-foreground" aria-hidden="true" />
          <h2 class="text-sm font-semibold">持仓</h2>
          <span v-if="data.portfolio.n_positions > 0" class="text-xs text-muted-foreground">
            {{ data.portfolio.n_positions }}只
          </span>
        </div>

        <div v-if="data.portfolio.n_positions === 0" class="py-2 text-sm text-muted-foreground">
          暂无持仓
        </div>
        <div v-else-if="data.portfolio.alerts.length === 0" class="py-2 text-sm text-muted-foreground">
          暂无需要处理的变化
        </div>
        <div v-else class="space-y-2">
          <RouterLink
            v-for="alert in data.portfolio.alerts"
            :key="alert.code"
            :to="`/detail/${alert.code}`"
            class="flex w-full items-center justify-between rounded-lg border p-2.5 text-left transition-colors hover:bg-accent/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
          >
            <div class="flex items-center gap-2">
              <AlertTriangle
                class="size-4"
                :style="{ color: changeColor(alert.unrealized_pnl_pct ?? '0') }"
                aria-hidden="true"
              />
              <div>
                <span class="text-sm font-medium">{{ alert.name || alert.code }}</span>
                <span class="ml-1 text-xs text-muted-foreground">{{ alert.shares }}股</span>
              </div>
            </div>
            <span class="font-mono text-sm font-medium" :style="{ color: changeColor(alert.unrealized_pnl_pct ?? '0') }">
              {{ fmtPct(alert.unrealized_pnl_pct) }}
            </span>
          </RouterLink>
        </div>

        <!-- 持仓总盈亏 -->
        <div v-if="data.portfolio.n_positions > 0" class="mt-3 border-t pt-2">
          <div class="flex items-center justify-between text-xs">
            <span class="text-muted-foreground">总浮盈浮亏</span>
            <span
              class="font-mono font-medium"
              :style="{ color: changeColor(data.portfolio.total_unrealized_pnl_pct ?? '0') }"
            >
              {{ fmtWan(data.portfolio.total_unrealized_pnl) }}
              <span v-if="data.portfolio.total_unrealized_pnl_pct">
                ({{ fmtPct(data.portfolio.total_unrealized_pnl_pct) }})
              </span>
            </span>
          </div>
        </div>
      </section>

      <!-- 5. 信号摘要 -->
      <section v-if="data.signals.summary" class="rounded-xl border bg-card p-4">
        <RouterLink
          to="/signals"
          class="flex w-full items-center justify-between focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
        >
          <div class="flex items-center gap-2">
            <TrendingUp class="size-4 text-muted-foreground" aria-hidden="true" />
            <span class="text-sm font-medium">最近信号</span>
            <span class="text-xs text-muted-foreground">{{ data.signals.summary.n_recent }}条</span>
          </div>
          <div class="flex items-center gap-2">
            <span v-if="data.signals.summary.n_critical > 0" class="rounded bg-red-100 px-1.5 py-0.5 text-xs font-medium text-red-700">
              {{ data.signals.summary.n_critical }}严重
            </span>
            <span v-if="data.signals.summary.n_warning > 0" class="rounded bg-orange-100 px-1.5 py-0.5 text-xs font-medium text-orange-700">
              {{ data.signals.summary.n_warning }}警告
            </span>
            <ChevronRight class="size-4 text-muted-foreground" aria-hidden="true" />
          </div>
        </RouterLink>
        <p v-if="data.signals.summary.latest_title" class="mt-2 text-xs text-muted-foreground">
          最新：{{ data.signals.summary.latest_title }}
        </p>
      </section>

      <!-- 6. 问 AI 输入条 -->
      <section class="sticky bottom-20 z-30 md:bottom-4">
        <form
          class="flex items-center gap-2 rounded-xl border bg-card p-2 shadow-lg focus-within:ring-2 focus-within:ring-primary/40"
          @submit.prevent="sendAI"
        >
          <input
            v-model="aiInput"
            type="text"
            placeholder="问 AI：解释今天的盘面…"
            class="flex-1 bg-transparent px-2 text-sm outline-none placeholder:text-muted-foreground"
            aria-label="问 AI"
          >
          <button
            type="submit"
            class="flex size-8 items-center justify-center rounded-lg bg-primary text-primary-foreground transition-opacity hover:opacity-90 disabled:opacity-50"
            :disabled="!aiInput.trim()"
            aria-label="发送"
          >
            <Send class="size-4" aria-hidden="true" />
          </button>
        </form>
      </section>
    </div>
  </div>
</template>
