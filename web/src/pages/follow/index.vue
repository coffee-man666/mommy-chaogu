<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { RouterLink } from 'vue-router'
import { apiGet, toApiError, type ApiError } from '@/api/client'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import ErrorState from '@/components/ErrorState.vue'
import { changeColor, fmtPct, fmtPrice } from '@/utils/format'

interface Theme {
  id: string
  name: string
  description: string
  total_stocks: number
  subcategories: string[]
  source: string
}

interface WatchlistGroup {
  name: string
  description: string
  n_stocks: number
}

const router = useRouter()
const themes = ref<Theme[]>([])
const groups = ref<WatchlistGroup[]>([])
const loading = ref(true)
const error = ref<ApiError | null>(null)

// 关注状态存储在 localStorage（轻量，P3 可迁移到后端）
const FOLLOW_KEY = 'mommy-followed-themes'
const followedIds = ref<Set<string>>(new Set())

function loadFollowed() {
  try {
    const raw = localStorage.getItem(FOLLOW_KEY)
    if (raw) followedIds.value = new Set(JSON.parse(raw))
  } catch {
    // ignore
  }
}

function saveFollowed() {
  localStorage.setItem(FOLLOW_KEY, JSON.stringify([...followedIds.value]))
}

function toggleFollow(id: string) {
  if (followedIds.value.has(id)) {
    followedIds.value.delete(id)
  } else {
    followedIds.value.add(id)
  }
  followedIds.value = new Set(followedIds.value) // trigger reactivity
  saveFollowed()
}

const followedThemes = computed(() => themes.value.filter(t => followedIds.value.has(t.id)))
const availableThemes = computed(() => themes.value.filter(t => !followedIds.value.has(t.id)))

const themeIcons: Record<string, string> = {
  semiconductor: '🔧',
  innovative_drug: '💊',
  humanoid_robot: '🤖',
  materials: '🧱',
  earnings_watch: '📊',
}

async function load() {
  loading.value = true
  error.value = null
  try {
    const [themeData, groupData] = await Promise.all([
      apiGet<{ items: Theme[]; total: number }>('/api/themes'),
      apiGet<{ items: WatchlistGroup[]; total: number }>('/api/watchlist/groups').catch(() => ({ items: [], total: 0 })),
    ])
    themes.value = themeData.items
    groups.value = groupData.items
  } catch (e) {
    error.value = toApiError(e)
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  loadFollowed()
  load()
})
</script>

<template>
  <div class="mx-auto max-w-4xl px-4 py-4 pb-24 md:pb-8">
    <h1 class="mb-4 text-xl font-bold">关注</h1>

    <!-- Loading -->
    <div v-if="loading" class="space-y-3">
      <div v-for="i in 3" :key="i" class="h-24 animate-pulse rounded-xl bg-muted" />
    </div>

    <!-- Error -->
    <ErrorState v-else-if="error && themes.length === 0" :message="error?.friendly" @retry="load" />

    <div v-else class="space-y-6">
      <!-- 已关注主题 -->
      <section>
        <h2 class="mb-3 text-sm font-semibold text-muted-foreground">已关注主题</h2>
        <div v-if="followedThemes.length === 0" class="rounded-xl border border-dashed p-6 text-center text-sm text-muted-foreground">
          还没有关注的主题，从下方选几个吧
        </div>
        <div v-else class="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Card
            v-for="t in followedThemes"
            :key="t.id"
            class="transition-[border-color,box-shadow] hover:border-primary/50 hover:shadow-md"
          >
            <CardContent class="p-4">
              <div class="flex items-start gap-3">
                <span class="text-2xl leading-none">{{ themeIcons[t.id] || '📈' }}</span>
                <div class="min-w-0 flex-1">
                  <div class="flex items-center justify-between">
                    <RouterLink
                      :to="`/themes/${t.id}`"
                      class="text-sm font-bold truncate hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
                    >
                      {{ t.name }}
                    </RouterLink>
                    <button
                      class="ml-2 shrink-0 rounded px-2 py-0.5 text-xs text-orange-500 transition-colors hover:bg-orange-50"
                      @click="toggleFollow(t.id)"
                    >
                      取消关注
                    </button>
                  </div>
                  <p class="mt-0.5 text-xs text-muted-foreground line-clamp-1">{{ t.description }}</p>
                  <Badge variant="secondary" class="mt-2 text-xs">{{ t.total_stocks }}只</Badge>
                </div>
              </div>
            </CardContent>
          </Card>
        </div>
      </section>

      <!-- 自选分组 -->
      <section v-if="groups.length > 0">
        <h2 class="mb-3 text-sm font-semibold text-muted-foreground">自选分组</h2>
        <div class="flex flex-wrap gap-2">
          <RouterLink
            v-for="g in groups"
            :key="g.name"
            to="/"
            class="flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-sm transition-colors hover:bg-accent"
          >
            <span class="font-medium">{{ g.name }}</span>
            <span class="text-xs text-muted-foreground">{{ g.n_stocks }}只</span>
          </RouterLink>
        </div>
      </section>

      <!-- 可关注主题 -->
      <section v-if="availableThemes.length > 0">
        <h2 class="mb-3 text-sm font-semibold text-muted-foreground">发现更多主题</h2>
        <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Card
            v-for="t in availableThemes"
            :key="t.id"
            class="opacity-75 transition-[opacity,border-color] hover:opacity-100 hover:border-primary/50"
          >
            <CardContent class="p-4">
              <div class="flex items-start gap-3">
                <span class="text-2xl leading-none">{{ themeIcons[t.id] || '📈' }}</span>
                <div class="min-w-0 flex-1">
                  <div class="flex items-center justify-between">
                    <RouterLink
                      :to="`/themes/${t.id}`"
                      class="text-sm font-bold truncate hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
                    >
                      {{ t.name }}
                    </RouterLink>
                    <button
                      class="ml-2 shrink-0 rounded bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary transition-colors hover:bg-primary/20"
                      @click="toggleFollow(t.id)"
                    >
                      + 关注
                    </button>
                  </div>
                  <p class="mt-0.5 text-xs text-muted-foreground line-clamp-1">{{ t.description }}</p>
                  <Badge variant="secondary" class="mt-2 text-xs">{{ t.total_stocks }}只</Badge>
                </div>
              </div>
            </CardContent>
          </Card>
        </div>
      </section>
    </div>
  </div>
</template>
