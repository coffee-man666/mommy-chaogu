<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { apiGet } from '@/api/client'
import { cn } from '@/lib/utils'
import { Card, CardContent } from '@/components/ui/card'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import type { Signal } from '@/api/types'

const router = useRouter()

const recentSignals = ref<Signal[]>([])
const history = ref<Signal[]>([])
const loading = ref(true)
const recentError = ref(false)
const historyError = ref(false)
const activeTab = ref('recent')

let timer: number | null = null

async function load() {
  const [recentResult, historyResult] = await Promise.allSettled([
    apiGet<Signal[]>('/api/signals/recent'),
    apiGet<Signal[]>('/api/signals/history?limit=50'),
  ])

  if (recentResult.status === 'fulfilled') {
    recentSignals.value = recentResult.value
    recentError.value = false
  } else {
    recentError.value = true
  }

  if (historyResult.status === 'fulfilled') {
    history.value = historyResult.value
    historyError.value = false
  } else {
    historyError.value = true
  }

  loading.value = false
}

function isStockCode(code: string): boolean {
  return /^\d{6}$/.test(code)
}

function goDetail(s: Signal) {
  if (isStockCode(s.code)) {
    router.push({ name: 'detail', params: { code: s.code } })
  }
}

function fmtTime(iso: string): string {
  const d = new Date(iso)
  if (isNaN(d.getTime())) return iso
  const now = new Date()
  if (d.toDateString() === now.toDateString()) {
    return d.toTimeString().slice(0, 8)
  }
  return `${d.getMonth() + 1}/${d.getDate()} ${d.toTimeString().slice(0, 5)}`
}

const severityConfig: Record<
  Signal['severity'],
  { icon: string; label: string; badge: string; border: string }
> = {
  critical: {
    icon: '🚨',
    label: 'CRIT',
    badge: 'bg-destructive text-white',
    border: 'border-l-destructive',
  },
  warning: {
    icon: '⚠️',
    label: 'WARN',
    badge: 'bg-yellow-500 text-white',
    border: 'border-l-yellow-500',
  },
  info: {
    icon: 'ℹ️',
    label: 'INFO',
    badge: 'bg-blue-500 text-white',
    border: 'border-l-blue-500',
  },
}

const currentList = computed(() =>
  activeTab.value === 'recent' ? recentSignals.value : history.value,
)
const currentError = computed(() =>
  activeTab.value === 'recent' ? recentError.value : historyError.value,
)
const errorCount = computed(
  () => Number(recentError.value) + Number(historyError.value),
)

onMounted(() => {
  load()
  timer = window.setInterval(load, 30_000)
})

onUnmounted(() => {
  if (timer) clearInterval(timer)
})
</script>

<template>
  <div class="mx-auto w-full max-w-4xl space-y-4 p-4 lg:p-6">
    <!-- 页头 -->
    <div class="flex items-center justify-between">
      <h1 class="text-xl font-bold tracking-tight">🔔 信号中心</h1>
      <div class="flex items-center gap-2">
        <span class="font-mono text-xs text-muted-foreground">30秒刷新</span>
        <span v-if="errorCount > 0" class="text-xs text-destructive" aria-live="polite">
          ⚠ {{ errorCount === 2 ? '数据加载失败' : '部分数据加载失败' }}
        </span>
      </div>
    </div>

    <Tabs v-model="activeTab" default-value="recent" class="w-full">
      <TabsList class="grid w-full grid-cols-2">
        <TabsTrigger value="recent">
          本次触发
          <Badge variant="secondary" class="ml-1 font-mono text-[10px]">
            {{ recentSignals.length }}
          </Badge>
        </TabsTrigger>
        <TabsTrigger value="history">
          历史信号
          <Badge variant="secondary" class="ml-1 font-mono text-[10px]">
            {{ history.length }}
          </Badge>
        </TabsTrigger>
      </TabsList>

      <div
        v-if="!loading && currentError && currentList.length"
        class="rounded-md border border-yellow-500/40 bg-yellow-500/10 px-3 py-2 text-sm text-yellow-700 dark:text-yellow-300"
        role="status"
      >
        刷新失败，正在显示上次成功数据
      </div>

      <!-- 本次触发 -->
      <TabsContent value="recent" class="space-y-3">
        <!-- 加载骨架 -->
        <template v-if="loading">
          <Card v-for="i in 3" :key="i">
            <CardContent class="space-y-3">
              <div class="flex items-center gap-2">
                <Skeleton class="h-5 w-14" />
                <Skeleton class="h-4 w-32" />
                <Skeleton class="h-4 w-16" />
              </div>
              <Skeleton class="h-5 w-3/4" />
              <Skeleton class="h-4 w-full" />
            </CardContent>
          </Card>
        </template>

        <!-- 信号卡片 -->
        <template v-else-if="recentSignals.length">
          <Card
            v-for="s in recentSignals"
            :key="`${s.timestamp}-${s.code}-${s.rule_id}`"
            class="cursor-pointer border-l-4 transition-transform active:scale-[0.98] focus-visible:ring-2 focus-visible:ring-primary outline-none"
            tabindex="0"
            :class="severityConfig[s.severity].border"
            @click="goDetail(s)"
            @keydown.enter="goDetail(s)"
          >
            <CardContent class="space-y-2">
              <!-- 头部：严重度 + 代码 + 时间 -->
              <div class="flex flex-wrap items-center gap-2">
                <Badge
                  :class="cn('text-[10px] font-bold tracking-wide', severityConfig[s.severity].badge)"
                >
                  {{ severityConfig[s.severity].icon }} {{ severityConfig[s.severity].label }}
                </Badge>
                <span class="flex-1 truncate font-semibold text-card-foreground">
                  <span v-if="s.code">{{ s.code }}</span>
                  <span v-if="s.code && s.name"> </span>
                  <span v-if="s.name">{{ s.name }}</span>
                </span>
                <span class="font-mono text-xs text-muted-foreground">
                  {{ fmtTime(s.timestamp) }}
                </span>
              </div>
              <!-- 标题 -->
              <p class="font-semibold leading-snug text-card-foreground">{{ s.title }}</p>
              <!-- 详情 -->
              <p class="text-sm leading-relaxed text-muted-foreground">{{ s.detail }}</p>
              <!-- 跳转提示 -->
              <p v-if="isStockCode(s.code)" class="text-xs font-semibold text-primary">
                点击查看 K 线 ›
              </p>
            </CardContent>
          </Card>
        </template>

        <!-- 空状态 -->
        <Card v-else>
          <CardContent class="flex flex-col items-center gap-2 py-16 text-center">
            <template v-if="recentError">
              <span class="text-5xl">⚠️</span>
              <p class="text-base font-semibold text-destructive">数据加载失败</p>
              <p class="text-sm text-muted-foreground">行情服务暂时不可用，请稍后重试</p>
            </template>
            <template v-else>
              <span class="text-5xl">🌤️</span>
              <p class="text-base font-semibold text-muted-foreground">本次轮询未触发信号</p>
              <p class="text-sm text-muted-foreground">行情平稳，妈妈放心 ✨</p>
            </template>
          </CardContent>
        </Card>
      </TabsContent>

      <!-- 历史信号 -->
      <TabsContent value="history" class="space-y-3">
        <!-- 加载骨架 -->
        <template v-if="loading">
          <Card v-for="i in 3" :key="i">
            <CardContent class="space-y-3">
              <div class="flex items-center gap-2">
                <Skeleton class="h-5 w-14" />
                <Skeleton class="h-4 w-32" />
                <Skeleton class="h-4 w-16" />
              </div>
              <Skeleton class="h-5 w-3/4" />
              <Skeleton class="h-4 w-full" />
            </CardContent>
          </Card>
        </template>

        <!-- 信号卡片 -->
        <template v-else-if="history.length">
          <Card
            v-for="s in history"
            :key="`${s.timestamp}-${s.code}-${s.rule_id}`"
            class="cursor-pointer border-l-4 transition-transform active:scale-[0.98]"
            :class="severityConfig[s.severity].border"
            @click="goDetail(s)"
          >
            <CardContent class="space-y-2">
              <!-- 头部 -->
              <div class="flex flex-wrap items-center gap-2">
                <Badge
                  :class="cn('text-[10px] font-bold tracking-wide', severityConfig[s.severity].badge)"
                >
                  {{ severityConfig[s.severity].icon }} {{ severityConfig[s.severity].label }}
                </Badge>
                <span class="flex-1 truncate font-semibold text-card-foreground">
                  <span v-if="s.code">{{ s.code }}</span>
                  <span v-if="s.code && s.name"> </span>
                  <span v-if="s.name">{{ s.name }}</span>
                </span>
                <span class="font-mono text-xs text-muted-foreground">
                  {{ fmtTime(s.timestamp) }}
                </span>
              </div>
              <!-- 标题 -->
              <p class="font-semibold leading-snug text-card-foreground">{{ s.title }}</p>
              <!-- 详情 -->
              <p class="text-sm leading-relaxed text-muted-foreground">{{ s.detail }}</p>
            </CardContent>
          </Card>
        </template>

        <!-- 空状态 -->
        <Card v-else>
          <CardContent class="flex flex-col items-center gap-2 py-16 text-center">
            <template v-if="historyError">
              <span class="text-5xl">⚠️</span>
              <p class="text-base font-semibold text-destructive">历史信号加载失败</p>
              <p class="text-sm text-muted-foreground">信号服务暂时不可用，请稍后重试</p>
            </template>
            <template v-else>
              <span class="text-5xl">📭</span>
              <p class="text-base font-semibold text-muted-foreground">暂无历史信号</p>
            </template>
          </CardContent>
        </Card>
      </TabsContent>
    </Tabs>

    <!-- 刷新按钮 -->
    <div v-if="!loading && currentList.length" class="flex justify-center">
      <Button variant="ghost" size="sm" @click="load">↻ 刷新</Button>
    </div>
  </div>
</template>
