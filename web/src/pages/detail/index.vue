<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed, nextTick, watch } from 'vue'
import { useRouter } from 'vue-router'
import { apiGet } from '@/api/client'
import { fmtPrice, fmtPct, fmtWan, fmtMoney, fmtAge } from '@/utils/format'
import type { Quote, Bar, MoneyFlowResponse } from '@/api/types'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import {
  Table,
  TableBody,
  TableRow,
  TableCell,
} from '@/components/ui/table'
import { Separator } from '@/components/ui/separator'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'

const props = defineProps<{ code: string }>()
const router = useRouter()

// ---------- 状态 ----------
const quote = ref<Quote | null>(null)
const quoteLoading = ref(true)
const bars = ref<Bar[]>([])
const klineChart = ref<any>(null)
const interval = ref<string>('1d')

const flowToday = ref<MoneyFlowResponse | null>(null)
const flowHistory = ref<MoneyFlowResponse | null>(null)
const flowTab = ref<string>('today')
const flowDays = ref(30)
const flowLoading = ref(false)

const codeInput = ref('')

let refreshTimer: number | null = null

const intervals = [
  { key: '5m', label: '5分' },
  { key: '15m', label: '15分' },
  { key: '30m', label: '30分' },
  { key: '60m', label: '60分' },
  { key: '1d', label: '日K' },
  { key: '1w', label: '周K' },
  { key: '1M', label: '月K' },
]

// ---------- 工具函数 ----------

/** 涨跌方向 → Tailwind class（红涨绿跌） */
function dirClass(val: string | number | null | undefined): string {
  if (val == null) return ''
  const n = Number(val)
  if (isNaN(n) || n === 0) return 'text-muted-foreground'
  return n > 0 ? 'text-up' : 'text-down'
}

/** 正值加 + 号 */
function dirSign(val: string | number | null | undefined): string {
  if (val == null) return ''
  return Number(val) >= 0 ? '+' : ''
}

/** 相对昨收的方向 class */
function dirClassRef(val: string | number | null | undefined, ref: string | number | null | undefined): string {
  if (val == null || ref == null) return ''
  const n = Number(val)
  const r = Number(ref)
  if (isNaN(n) || isNaN(r)) return ''
  const diff = n - r
  if (diff === 0) return 'text-muted-foreground'
  return diff > 0 ? 'text-up' : 'text-down'
}

/** 万/亿金额格式化 */
function fmtFlowWan(s: string | null | undefined): string {
  if (!s) return '-'
  const n = Number(s)
  if (isNaN(n)) return String(s)
  return fmtWan(n)
}

// ---------- 数据加载 ----------

async function loadQuote() {
  quoteLoading.value = true
  try {
    quote.value = await apiGet<Quote>(`/api/quotes/${props.code}`)
  } catch (e) {
    console.error(e)
  } finally {
    quoteLoading.value = false
  }
}

async function loadBars() {
  try {
    const isDayOrAbove = interval.value === '1d' || interval.value === '1w' || interval.value === '1M'
    const limit = isDayOrAbove ? 250 : 200
    bars.value = await apiGet<Bar[]>(
      `/api/quotes/${props.code}/bars?interval=${interval.value}&limit=${limit}&adjustment=forward`
    )
    await nextTick()
    drawKLine()
  } catch (e) {
    console.error(e)
  }
}

async function loadFlow() {
  flowLoading.value = true
  try {
    const [today, hist] = await Promise.all([
      apiGet<MoneyFlowResponse>(`/api/quotes/${props.code}/money_flow/today`).catch(() => null),
      apiGet<MoneyFlowResponse>(
        `/api/quotes/${props.code}/money_flow/history?days=${flowDays.value}`
      ).catch(() => null),
    ])
    if (today) flowToday.value = today
    if (hist) flowHistory.value = hist
  } finally {
    flowLoading.value = false
  }
}

async function changeFlowDays(d: number) {
  flowDays.value = d
  try {
    flowHistory.value = await apiGet<MoneyFlowResponse>(
      `/api/quotes/${props.code}/money_flow/history?days=${d}`
    )
  } catch (e) {
    console.error(e)
  }
}

// ---------- K 线 ----------

async function drawKLine() {
  try {
    const isFirstInit = !klineChart.value
    if (isFirstInit) {
      const klinecharts = await import('klinecharts')
      const el = document.getElementById('kline') as HTMLElement
      if (!el) return
      klineChart.value = klinecharts.init(el)
    }
    const chart = klineChart.value

    chart.setStyles({
      grid: {
        show: true,
        horizontal: { show: true, color: '#eee' },
        vertical: { show: true, color: '#eee' },
      },
      candle: {
        bar: {
          upColor: 'var(--color-up)',
          downColor: 'var(--color-down)',
          noChangeColor: '#999',
        },
      },
      indicator: {
        tooltip: { text: { color: '#333' } },
      },
    })

    if (isFirstInit) {
      chart.createIndicator('MA', false, { id: 'candle_pane' })
      chart.createIndicator('VOL')
    }

    const dataList = bars.value.map((b) => ({
      timestamp: new Date(b.timestamp).getTime(),
      open: Number(b.open),
      high: Number(b.high),
      low: Number(b.low),
      close: Number(b.close),
      volume: Number(b.volume),
    }))
    chart.applyNewData(dataList)
  } catch (e) {
    console.error('drawKLine failed', e)
  }
}

function changeInterval(key: string) {
  interval.value = key
  loadBars()
}

// ---------- 回车跳转 ----------

function onCodeEnter() {
  const c = codeInput.value.trim()
  if (!c) return
  router.push({ name: 'detail', params: { code: c } })
}

function goBack() {
  router.back()
}

// ---------- SVG 资金流图 ----------

const SVG_W = 360
const SVG_H_TODAY = 160
const SVG_H_HISTORY = 200
const PAD_L = 4
const PAD_R = 4
const PAD_T = 10
const PAD_B = 20

const todayFlowPoints = computed(() => {
  const items = flowToday.value?.items
  if (!items?.length) return ''
  const W = SVG_W - PAD_L - PAD_R
  const H = SVG_H_TODAY - PAD_T - PAD_B
  const vals = items.map((i) => Number(i.main_net) || 0)
  const maxAbs = Math.max(...vals.map(Math.abs), 1)
  const n = items.length
  const stepX = W / Math.max(n - 1, 1)
  return items
    .map((item, i) => {
      const val = Number(item.main_net) || 0
      const x = PAD_L + i * stepX
      const y = PAD_T + H / 2 - (val / maxAbs) * (H / 2 - 4)
      return `${x.toFixed(1)},${y.toFixed(1)}`
    })
    .join(' ')
})

const todayFlowArea = computed(() => {
  const items = flowToday.value?.items
  if (!items?.length) return ''
  const pts = todayFlowPoints.value
  if (!pts) return ''
  const W = SVG_W - PAD_L - PAD_R
  const stepX = W / Math.max(items.length - 1, 1)
  const lastX = PAD_L + (items.length - 1) * stepX
  const midY = PAD_T + (SVG_H_TODAY - PAD_T - PAD_B) / 2
  return `${PAD_L},${midY} ${pts} ${lastX},${midY}`
})

const todayTimeLabels = computed(() => {
  const items = flowToday.value?.items
  if (!items?.length) return []
  return [
    items[0]?.timestamp?.slice(11, 16) || '',
    items[Math.floor(items.length / 2)]?.timestamp?.slice(11, 16) || '',
    items[items.length - 1]?.timestamp?.slice(11, 16) || '',
  ]
})

const historyBars = computed(() => {
  const items = flowHistory.value?.items
  if (!items?.length) return []
  const W = SVG_W - PAD_L - PAD_R
  const H = SVG_H_HISTORY - PAD_T - PAD_B
  const vals = items.map((i) => Number(i.main_net) || 0)
  const maxAbs = Math.max(...vals.map(Math.abs), 1)
  const barW = Math.min(24, (W / items.length) * 0.6)
  const gap = W / items.length
  const midY = PAD_T + H / 2
  return items.map((item, i) => {
    const v = Number(item.main_net) || 0
    const x = PAD_L + i * gap + (gap - barW) / 2
    const barH = (Math.abs(v) / maxAbs) * (H / 2 - 4)
    const y = v >= 0 ? midY - barH : midY
    return {
      x: x.toFixed(1),
      y: y.toFixed(1),
      w: barW.toFixed(1),
      h: barH.toFixed(1),
      color: v >= 0 ? 'var(--color-up)' : 'var(--color-down)',
      date: item.date?.slice(5) || '',
      val: fmtFlowWan(item.main_net),
      labelY: (v >= 0 ? Number(y.toFixed(1)) - 4 : Number(y.toFixed(1)) + Number(barH.toFixed(1)) + 12),
    }
  })
})

const historyMidY = computed(() => PAD_T + (SVG_H_HISTORY - PAD_T - PAD_B) / 2)

/** 当前 Tab 对应的累计数据 */
const activeCumulative = computed(() =>
  flowTab.value === 'today' ? flowToday.value?.cumulative : flowHistory.value?.cumulative
)

// ---------- 生命周期 ----------

watch(
  () => props.code,
  async () => {
    quote.value = null
    bars.value = []
    flowToday.value = null
    flowHistory.value = null
    codeInput.value = ''
    await loadQuote()
    await loadBars()
    loadFlow()
  }
)

onMounted(async () => {
  await loadQuote()
  await loadBars()
  loadFlow()
  refreshTimer = window.setInterval(loadQuote, 10_000)
})

onUnmounted(() => {
  if (refreshTimer) clearInterval(refreshTimer)
  if (klineChart.value) {
    klineChart.value.dispose()
    klineChart.value = null
  }
})
</script>

<template>
  <div class="min-h-screen bg-background pb-8">
    <!-- 顶部栏：返回 + 代码输入 -->
    <header class="flex items-center gap-2 bg-primary px-3 py-3 text-primary-foreground">
      <Button
        variant="ghost"
        size="sm"
        class="text-primary-foreground hover:bg-primary-foreground/20"
        @click="goBack"
      >
        ‹ 返回
      </Button>
      <Input
        v-model="codeInput"
        placeholder="输入代码回车跳转"
        inputmode="numeric"
        maxlength="6"
        class="h-8 w-40 border-primary-foreground/30 bg-primary-foreground/15 text-primary-foreground placeholder:text-primary-foreground/60"
        @keyup.enter="onCodeEnter"
      />
    </header>

    <div class="mx-auto max-w-3xl space-y-4 p-3">
      <!-- ============ 实时报价卡片 ============ -->
      <Card>
        <CardHeader class="pb-2">
          <div class="flex items-center justify-between">
            <div class="flex items-center gap-2">
              <CardTitle class="text-lg">{{ quote?.name || code }}</CardTitle>
              <Badge variant="secondary" class="font-mono">{{ code }}</Badge>
            </div>
            <span v-if="quote" class="text-xs text-muted-foreground">
              {{ fmtAge(quote.data_age_seconds) }}
            </span>
          </div>
        </CardHeader>
        <CardContent class="space-y-4">
          <!-- 加载骨架 -->
          <template v-if="quoteLoading && !quote">
            <div class="flex items-baseline gap-3">
              <Skeleton class="h-10 w-32" />
              <Skeleton class="h-6 w-20" />
            </div>
            <Skeleton class="h-20 w-full" />
          </template>

          <template v-else-if="quote">
            <!-- 现价 + 涨跌 -->
            <div class="flex items-baseline gap-3">
              <span :class="cn('font-mono text-4xl font-bold', dirClass(quote.change_pct))">
                {{ fmtPrice(quote.price) }}
              </span>
              <span :class="cn('font-mono text-xl font-semibold', dirClass(quote.change_pct))">
                {{ dirSign(quote.change_pct) }}{{ fmtPrice(quote.change) }}
                ({{ fmtPct(quote.change_pct) }})
              </span>
            </div>

            <Separator />

            <!-- 明细表格 -->
            <Table>
              <TableBody>
                <TableRow>
                  <TableCell class="w-1/4 py-2 text-xs text-muted-foreground">今开</TableCell>
                  <TableCell class="w-1/4 py-2 text-right font-mono text-sm">{{ fmtPrice(quote.open) }}</TableCell>
                  <TableCell class="w-1/4 py-2 text-xs text-muted-foreground">昨收</TableCell>
                  <TableCell class="w-1/4 py-2 text-right font-mono text-sm">{{ fmtPrice(quote.prev_close) }}</TableCell>
                </TableRow>
                <TableRow>
                  <TableCell class="py-2 text-xs text-muted-foreground">最高</TableCell>
                  <TableCell :class="cn('py-2 text-right font-mono text-sm', dirClassRef(quote.high, quote.prev_close))">{{ fmtPrice(quote.high) }}</TableCell>
                  <TableCell class="py-2 text-xs text-muted-foreground">最低</TableCell>
                  <TableCell :class="cn('py-2 text-right font-mono text-sm', dirClassRef(quote.low, quote.prev_close))">{{ fmtPrice(quote.low) }}</TableCell>
                </TableRow>
                <TableRow>
                  <TableCell class="py-2 text-xs text-muted-foreground">成交量</TableCell>
                  <TableCell class="py-2 text-right font-mono text-sm">{{ Number(quote.volume).toLocaleString() }}</TableCell>
                  <TableCell class="py-2 text-xs text-muted-foreground">成交额</TableCell>
                  <TableCell class="py-2 text-right font-mono text-sm">{{ fmtMoney(quote.turnover, 'yi') }}</TableCell>
                </TableRow>
                <TableRow>
                  <TableCell class="py-2 text-xs text-muted-foreground">换手</TableCell>
                  <TableCell class="py-2 text-right font-mono text-sm">{{ quote.turnover_rate ? `${quote.turnover_rate}%` : '-' }}</TableCell>
                  <TableCell class="py-2 text-xs text-muted-foreground">量比</TableCell>
                  <TableCell class="py-2 text-right font-mono text-sm">{{ quote.volume_ratio || '-' }}</TableCell>
                </TableRow>
                <TableRow>
                  <TableCell class="py-2 text-xs text-muted-foreground">PE</TableCell>
                  <TableCell class="py-2 text-right font-mono text-sm">{{ quote.pe || '-' }}</TableCell>
                  <TableCell class="py-2 text-xs text-muted-foreground">主力净流入</TableCell>
                  <TableCell :class="cn('py-2 text-right font-mono text-sm font-semibold', dirClass(quote.main_net_inflow))">
                    {{ dirSign(quote.main_net_inflow) }}{{ fmtMoney(quote.main_net_inflow, 'yi') }}
                  </TableCell>
                </TableRow>
              </TableBody>
            </Table>
          </template>
        </CardContent>
      </Card>

      <!-- ============ K 线图 ============ -->
      <Card>
        <CardHeader class="pb-2">
          <CardTitle class="text-base">K 线图</CardTitle>
        </CardHeader>
        <CardContent>
          <Tabs v-model="interval" class="w-full">
            <TabsList class="grid w-full grid-cols-7">
              <TabsTrigger
                v-for="i in intervals"
                :key="i.key"
                :value="i.key"
                class="text-xs"
                @click="changeInterval(i.key)"
              >
                {{ i.label }}
              </TabsTrigger>
            </TabsList>
          </Tabs>
          <div id="kline" class="mt-3 h-[360px] w-full"></div>
        </CardContent>
      </Card>

      <!-- ============ 资金流向 ============ -->
      <Card>
        <CardHeader class="pb-2">
          <CardTitle class="text-base">资金流向</CardTitle>
        </CardHeader>
        <CardContent class="space-y-4">
          <Tabs v-model="flowTab">
            <TabsList>
              <TabsTrigger value="today" class="text-sm">日内</TabsTrigger>
              <TabsTrigger value="history" class="text-sm">历史</TabsTrigger>
            </TabsList>

            <!-- ===== 日内 ===== -->
            <TabsContent value="today" class="space-y-4">
              <!-- 累计汇总 -->
              <div v-if="flowToday?.cumulative" class="grid grid-cols-5 gap-1">
                <div class="rounded-md bg-muted/60 p-2 text-center">
                  <div class="mb-1 text-[10px] text-muted-foreground">主力净流入</div>
                  <div :class="cn('font-mono text-xs font-bold', dirClass(flowToday.cumulative.main_net))">
                    {{ dirSign(flowToday.cumulative.main_net) }}{{ fmtFlowWan(flowToday.cumulative.main_net) }}
                  </div>
                </div>
                <div class="rounded-md bg-muted/40 p-2 text-center">
                  <div class="mb-1 text-[10px] text-muted-foreground">超大单</div>
                  <div :class="cn('font-mono text-xs font-bold', dirClass(flowToday.cumulative.super_net))">
                    {{ dirSign(flowToday.cumulative.super_net) }}{{ fmtFlowWan(flowToday.cumulative.super_net) }}
                  </div>
                </div>
                <div class="rounded-md bg-muted/40 p-2 text-center">
                  <div class="mb-1 text-[10px] text-muted-foreground">大单</div>
                  <div :class="cn('font-mono text-xs font-bold', dirClass(flowToday.cumulative.big_net))">
                    {{ dirSign(flowToday.cumulative.big_net) }}{{ fmtFlowWan(flowToday.cumulative.big_net) }}
                  </div>
                </div>
                <div class="rounded-md bg-muted/40 p-2 text-center">
                  <div class="mb-1 text-[10px] text-muted-foreground">中单</div>
                  <div :class="cn('font-mono text-xs font-bold', dirClass(flowToday.cumulative.medium_net))">
                    {{ dirSign(flowToday.cumulative.medium_net) }}{{ fmtFlowWan(flowToday.cumulative.medium_net) }}
                  </div>
                </div>
                <div class="rounded-md bg-muted/40 p-2 text-center">
                  <div class="mb-1 text-[10px] text-muted-foreground">小单</div>
                  <div :class="cn('font-mono text-xs font-bold', dirClass(flowToday.cumulative.small_net))">
                    {{ dirSign(flowToday.cumulative.small_net) }}{{ fmtFlowWan(flowToday.cumulative.small_net) }}
                  </div>
                </div>
              </div>

              <!-- 日内分时折线 -->
              <div v-if="flowToday && flowToday.items.length">
                <div :class="dirClass(flowToday.cumulative?.main_net)">
                  <svg
                    :viewBox="`0 0 ${SVG_W} ${SVG_H_TODAY}`"
                    class="block w-full"
                    preserveAspectRatio="xMidYMid meet"
                  >
                    <line :x1="PAD_L" :y1="SVG_H_TODAY / 2" :x2="SVG_W - PAD_R" :y2="SVG_H_TODAY / 2" stroke="#eee" stroke-width="1" />
                    <polygon :points="todayFlowArea" fill="currentColor" fill-opacity="0.12" />
                    <polyline :points="todayFlowPoints" stroke="currentColor" stroke-width="1.5" fill="none" />
                  </svg>
                </div>
                <div class="flex justify-between px-1 pt-1 font-mono text-[10px] text-muted-foreground">
                  <span v-for="(t, i) in todayTimeLabels" :key="i">{{ t }}</span>
                </div>
              </div>
              <div v-else-if="!flowLoading" class="py-6 text-center text-sm text-muted-foreground">
                暂无日内数据（非盘中时段）
              </div>
            </TabsContent>

            <!-- ===== 历史 ===== -->
            <TabsContent value="history" class="space-y-4">
              <!-- 累计汇总 -->
              <div v-if="flowHistory?.cumulative" class="grid grid-cols-5 gap-1">
                <div class="rounded-md bg-muted/60 p-2 text-center">
                  <div class="mb-1 text-[10px] text-muted-foreground">主力净流入</div>
                  <div :class="cn('font-mono text-xs font-bold', dirClass(flowHistory.cumulative.main_net))">
                    {{ dirSign(flowHistory.cumulative.main_net) }}{{ fmtFlowWan(flowHistory.cumulative.main_net) }}
                  </div>
                </div>
                <div class="rounded-md bg-muted/40 p-2 text-center">
                  <div class="mb-1 text-[10px] text-muted-foreground">超大单</div>
                  <div :class="cn('font-mono text-xs font-bold', dirClass(flowHistory.cumulative.super_net))">
                    {{ dirSign(flowHistory.cumulative.super_net) }}{{ fmtFlowWan(flowHistory.cumulative.super_net) }}
                  </div>
                </div>
                <div class="rounded-md bg-muted/40 p-2 text-center">
                  <div class="mb-1 text-[10px] text-muted-foreground">大单</div>
                  <div :class="cn('font-mono text-xs font-bold', dirClass(flowHistory.cumulative.big_net))">
                    {{ dirSign(flowHistory.cumulative.big_net) }}{{ fmtFlowWan(flowHistory.cumulative.big_net) }}
                  </div>
                </div>
                <div class="rounded-md bg-muted/40 p-2 text-center">
                  <div class="mb-1 text-[10px] text-muted-foreground">中单</div>
                  <div :class="cn('font-mono text-xs font-bold', dirClass(flowHistory.cumulative.medium_net))">
                    {{ dirSign(flowHistory.cumulative.medium_net) }}{{ fmtFlowWan(flowHistory.cumulative.medium_net) }}
                  </div>
                </div>
                <div class="rounded-md bg-muted/40 p-2 text-center">
                  <div class="mb-1 text-[10px] text-muted-foreground">小单</div>
                  <div :class="cn('font-mono text-xs font-bold', dirClass(flowHistory.cumulative.small_net))">
                    {{ dirSign(flowHistory.cumulative.small_net) }}{{ fmtFlowWan(flowHistory.cumulative.small_net) }}
                  </div>
                </div>
              </div>

              <!-- 天数选择 -->
              <div class="flex gap-2">
                <Button
                  v-for="d in [7, 30, 90]"
                  :key="d"
                  :variant="flowDays === d ? 'default' : 'outline'"
                  size="sm"
                  class="h-7 rounded-full px-3 text-xs"
                  @click="changeFlowDays(d)"
                >
                  {{ d }}天
                </Button>
              </div>

              <!-- 历史柱状图 -->
              <div v-if="flowHistory && flowHistory.items.length">
                <svg
                  :viewBox="`0 0 ${SVG_W} ${SVG_H_HISTORY}`"
                  class="block w-full"
                  preserveAspectRatio="xMidYMid meet"
                >
                  <line
                    :x1="PAD_L" :y1="historyMidY"
                    :x2="SVG_W - PAD_R" :y2="historyMidY"
                    stroke="#ddd" stroke-width="1" stroke-dasharray="3,3"
                  />
                  <template v-for="(b, i) in historyBars" :key="i">
                    <rect :x="b.x" :y="b.y" :width="b.w" :height="b.h" :fill="b.color" rx="2" />
                    <text
                      :x="Number(b.x) + Number(b.w) / 2"
                      :y="b.labelY"
                      text-anchor="middle" font-size="8" fill="#999"
                    >{{ b.val }}</text>
                    <text
                      :x="Number(b.x) + Number(b.w) / 2"
                      :y="SVG_H_HISTORY - 6"
                      text-anchor="middle" font-size="8" fill="#aaa"
                    >{{ b.date }}</text>
                  </template>
                </svg>
              </div>
              <div v-else-if="!flowLoading" class="py-6 text-center text-sm text-muted-foreground">
                暂无历史数据
              </div>
            </TabsContent>
          </Tabs>
        </CardContent>
      </Card>
    </div>
  </div>
</template>
