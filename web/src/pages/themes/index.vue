<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { apiGet } from '@/api/client'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'

interface Theme {
  id: string
  name: string
  description: string
  total_stocks: number
  subcategories: string[]
  source: string
}

const themeIcons: Record<string, string> = {
  semiconductor: '🔧',
  innovative_drug: '💊',
  humanoid_robot: '🤖',
  materials: '🧱',
  earnings_watch: '📊',
}

const router = useRouter()
const themes = ref<Theme[]>([])
const loading = ref(true)

onMounted(async () => {
  try {
    const data = await apiGet<{ items: Theme[]; total: number }>('/api/themes')
    themes.value = data.items
  } catch {
    themes.value = []
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="min-h-screen bg-background pb-6">
    <!-- 顶部头部 -->
    <header
      class="bg-gradient-to-br from-primary to-primary/80 text-primary-foreground px-4 py-4"
    >
      <h1 class="text-2xl font-bold">📦 主题观察</h1>
      <p class="text-sm opacity-85 mt-1">产业链全景 + 中报高增长观察</p>
    </header>

    <div class="p-3">
      <!-- 骨架屏 -->
      <div
        v-if="loading"
        class="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3"
      >
        <Card v-for="i in 4" :key="i">
          <CardContent class="p-4 space-y-3">
            <div class="flex items-center gap-3">
              <Skeleton class="size-10 rounded-lg" />
              <div class="space-y-1.5">
                <Skeleton class="h-4 w-20" />
                <Skeleton class="h-3 w-14" />
              </div>
            </div>
            <Skeleton class="h-3 w-full" />
            <Skeleton class="h-3 w-2/3" />
          </CardContent>
        </Card>
      </div>

      <!-- 主题卡片网格 -->
      <div
        v-else
        class="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3"
      >
        <Card
          v-for="t in themes"
          :key="t.id"
          class="cursor-pointer transition-all hover:shadow-md hover:border-primary/50"
          @click="router.push(`/themes/${t.id}`)"
        >
          <CardContent class="p-4">
            <div class="flex items-start gap-3">
              <span class="text-3xl leading-none flex-shrink-0">
                {{ themeIcons[t.id] || '📈' }}
              </span>
              <div class="min-w-0 flex-1">
                <div class="flex items-center justify-between gap-2">
                  <h3 class="text-base font-bold text-card-foreground truncate">
                    {{ t.name }}
                  </h3>
                  <span class="text-muted-foreground text-lg flex-shrink-0">›</span>
                </div>
                <p class="mt-1 text-xs text-muted-foreground line-clamp-2 leading-relaxed">
                  {{ t.description }}
                </p>
              </div>
            </div>

            <!-- 统计指标 -->
            <div class="mt-3 flex items-center gap-2">
              <Badge variant="secondary" class="text-xs">
                {{ t.total_stocks }} 只
              </Badge>
              <Badge
                v-if="t.subcategories && t.subcategories.length"
                variant="outline"
                class="text-xs text-muted-foreground"
              >
                {{ t.subcategories.length }} 个子板块
              </Badge>
            </div>
          </CardContent>
        </Card>
      </div>

      <!-- 空状态 -->
      <div
        v-if="!loading && themes.length === 0"
        class="py-16 text-center"
      >
        <span class="text-4xl">📂</span>
        <p class="mt-2 text-sm text-muted-foreground">暂无主题数据</p>
      </div>
    </div>
  </div>
</template>
