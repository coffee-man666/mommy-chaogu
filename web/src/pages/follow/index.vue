<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { ArrowDown, ArrowUp, Eye, EyeOff, Star } from 'lucide-vue-next'
import {
  getBaskets,
  updateBasketPreference,
  type Basket,
} from '@/api/baskets'
import { toApiError, type ApiError } from '@/api/client'
import ErrorState from '@/components/ErrorState.vue'

const LEGACY_FOLLOW_KEY = 'mommy-followed-themes'
const baskets = ref<Basket[]>([])
const loading = ref(true)
const error = ref<ApiError | null>(null)
const savingId = ref('')
const reasonDrafts = reactive<Record<string, string>>({})

const visibleBaskets = computed(() => baskets.value.filter(item => !item.hidden))
const followedBaskets = computed(() => visibleBaskets.value.filter(item => item.followed))
const availableBaskets = computed(() => visibleBaskets.value.filter(item => !item.followed))
const hiddenBaskets = computed(() => baskets.value.filter(item => item.hidden))

function sortBaskets() {
  baskets.value.sort((a, b) => a.sort_order - b.sort_order || a.name.localeCompare(b.name))
}

function replaceBasket(updated: Basket) {
  const index = baskets.value.findIndex(item => item.id === updated.id)
  if (index >= 0) baskets.value[index] = updated
  reasonDrafts[updated.id] = updated.reason
  sortBaskets()
}

async function migrateLegacyFollowState(items: Basket[]) {
  const raw = localStorage.getItem(LEGACY_FOLLOW_KEY)
  if (raw === null) return items
  try {
    const legacyIds = new Set<string>(JSON.parse(raw))
    const migrated = await Promise.all(
      items
        .filter(item => item.kind === 'theme')
        .map(item => updateBasketPreference(item.id, { followed: legacyIds.has(item.source_id) })),
    )
    const byId = new Map(migrated.map(item => [item.id, item]))
    localStorage.removeItem(LEGACY_FOLLOW_KEY)
    return items.map(item => byId.get(item.id) ?? item)
  } catch {
    return items
  }
}

async function load() {
  loading.value = true
  error.value = null
  try {
    baskets.value = await migrateLegacyFollowState(await getBaskets())
    for (const item of baskets.value) reasonDrafts[item.id] = item.reason
    sortBaskets()
  } catch (e) {
    error.value = toApiError(e, '加载关注篮子')
  } finally {
    loading.value = false
  }
}

async function update(item: Basket, change: Parameters<typeof updateBasketPreference>[1]) {
  savingId.value = item.id
  error.value = null
  try {
    replaceBasket(await updateBasketPreference(item.id, change))
  } catch (e) {
    error.value = toApiError(e, '保存关注偏好')
  } finally {
    savingId.value = ''
  }
}

async function move(item: Basket, direction: -1 | 1) {
  const items = followedBaskets.value
  const index = items.findIndex(candidate => candidate.id === item.id)
  const other = items[index + direction]
  if (!other) return
  savingId.value = item.id
  try {
    const [updatedItem, updatedOther] = await Promise.all([
      updateBasketPreference(item.id, { sort_order: other.sort_order }),
      updateBasketPreference(other.id, { sort_order: item.sort_order }),
    ])
    replaceBasket(updatedItem)
    replaceBasket(updatedOther)
  } catch (e) {
    error.value = toApiError(e, '调整篮子顺序')
    await load()
  } finally {
    savingId.value = ''
  }
}

onMounted(load)
</script>

<template>
  <div class="mx-auto max-w-4xl px-4 py-4 pb-24 md:pb-8">
    <div class="mb-4">
      <h1 class="text-xl font-bold">关注</h1>
      <p class="mt-1 text-sm text-muted-foreground">主题和自选分组统一成篮子；这里的顺序会直接用于今日首页。</p>
    </div>

    <div v-if="loading" class="space-y-3" aria-label="正在加载关注篮子">
      <div v-for="i in 3" :key="i" class="h-28 animate-pulse rounded-xl bg-muted" />
    </div>

    <ErrorState v-else-if="error && baskets.length === 0" :message="error.friendly" @retry="load" />

    <div v-else class="space-y-6">
      <p v-if="error" role="alert" class="rounded-lg bg-destructive/10 px-3 py-2 text-sm text-destructive">
        {{ error.friendly }}
      </p>

      <section aria-labelledby="followed-heading">
        <div class="mb-3 flex items-center justify-between">
          <h2 id="followed-heading" class="text-sm font-semibold text-muted-foreground">今日关注</h2>
          <span class="text-xs text-muted-foreground">首页展示前 4 项</span>
        </div>
        <div v-if="followedBaskets.length === 0" class="rounded-xl border border-dashed p-6 text-center text-sm text-muted-foreground">
          还没有关注篮子，从下方选择即可
        </div>
        <ul v-else class="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <li
            v-for="(item, index) in followedBaskets"
            :key="item.id"
            class="rounded-xl border bg-card p-4"
          >
            <div class="flex items-start justify-between gap-3">
              <div class="min-w-0">
                <div class="flex items-center gap-2">
                  <Star class="size-4 shrink-0 text-amber-500" aria-hidden="true" />
                  <RouterLink
                    :to="`/baskets/${encodeURIComponent(item.id)}`"
                    class="truncate font-semibold hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
                  >
                    {{ item.name }}
                  </RouterLink>
                  <span class="rounded bg-muted px-1.5 py-0.5 text-[11px] text-muted-foreground">
                    {{ item.kind === 'theme' ? '内置主题' : '自定义' }}
                  </span>
                </div>
                <p class="mt-1 line-clamp-1 text-xs text-muted-foreground">{{ item.description || `${item.total_stocks} 只成分股` }}</p>
              </div>
              <div class="flex shrink-0 gap-1">
                <button
                  class="flex size-9 items-center justify-center rounded-md hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary disabled:opacity-30"
                  :disabled="index === 0 || savingId === item.id"
                  :aria-label="`上移${item.name}`"
                  @click="move(item, -1)"
                >
                  <ArrowUp class="size-4" aria-hidden="true" />
                </button>
                <button
                  class="flex size-9 items-center justify-center rounded-md hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary disabled:opacity-30"
                  :disabled="index === followedBaskets.length - 1 || savingId === item.id"
                  :aria-label="`下移${item.name}`"
                  @click="move(item, 1)"
                >
                  <ArrowDown class="size-4" aria-hidden="true" />
                </button>
              </div>
            </div>
            <div class="mt-3 flex gap-2">
              <label :for="`reason-${item.id}`" class="sr-only">{{ item.name }}关注理由</label>
              <input
                :id="`reason-${item.id}`"
                v-model="reasonDrafts[item.id]"
                class="h-9 min-w-0 flex-1 rounded-md border bg-transparent px-3 text-sm outline-none placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-primary"
                maxlength="200"
                placeholder="写一句关注理由（可选）"
                @keyup.enter="update(item, { reason: reasonDrafts[item.id] })"
              >
              <button
                class="h-9 rounded-md border px-3 text-sm hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary disabled:opacity-50"
                :disabled="savingId === item.id || reasonDrafts[item.id] === item.reason"
                @click="update(item, { reason: reasonDrafts[item.id] })"
              >
                保存
              </button>
            </div>
            <div class="mt-2 flex gap-2 text-xs">
              <button
                class="min-h-9 rounded-md px-2 text-muted-foreground hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
                @click="update(item, { followed: false })"
              >取消关注</button>
              <button
                class="flex min-h-9 items-center gap-1 rounded-md px-2 text-muted-foreground hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
                @click="update(item, { hidden: true })"
              ><EyeOff class="size-3.5" aria-hidden="true" />隐藏</button>
            </div>
          </li>
        </ul>
      </section>

      <section v-if="availableBaskets.length" aria-labelledby="available-heading">
        <h2 id="available-heading" class="mb-3 text-sm font-semibold text-muted-foreground">更多篮子</h2>
        <ul class="grid grid-cols-1 gap-2 sm:grid-cols-2">
          <li v-for="item in availableBaskets" :key="item.id" class="flex items-center justify-between rounded-xl border p-3">
            <div class="min-w-0">
              <RouterLink
                :to="`/baskets/${encodeURIComponent(item.id)}`"
                class="font-medium hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
              >{{ item.name }}</RouterLink>
              <p class="text-xs text-muted-foreground">{{ item.total_stocks }}只 · {{ item.kind === 'theme' ? '内置主题' : '自定义' }}</p>
            </div>
            <button
              class="min-h-11 shrink-0 rounded-lg bg-primary/10 px-3 text-sm font-medium text-primary hover:bg-primary/20 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
              @click="update(item, { followed: true })"
            >关注</button>
          </li>
        </ul>
      </section>

      <section v-if="hiddenBaskets.length" aria-labelledby="hidden-heading">
        <h2 id="hidden-heading" class="mb-2 text-sm font-semibold text-muted-foreground">已隐藏</h2>
        <div class="flex flex-wrap gap-2">
          <button
            v-for="item in hiddenBaskets"
            :key="item.id"
            class="flex min-h-11 items-center gap-1 rounded-lg border px-3 text-sm text-muted-foreground hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
            @click="update(item, { hidden: false })"
          ><Eye class="size-4" aria-hidden="true" />恢复 {{ item.name }}</button>
        </div>
      </section>
    </div>
  </div>
</template>
