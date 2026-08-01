<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { useRoute, RouterLink } from 'vue-router'
import { AlertTriangle, ArrowLeft, Clock3 } from 'lucide-vue-next'
import { getBasket, updateBasketMemberWeight, type BasketDetail, type BasketMember } from '@/api/baskets'
import { toApiError } from '@/api/client'
import ErrorState from '@/components/ErrorState.vue'
import { changeColor, fmtPct } from '@/utils/format'

const route = useRoute()
const basket = ref<BasketDetail | null>(null)
const loading = ref(true)
const error = ref('')
const actionError = ref('')
const savingCode = ref('')
const weightDrafts = reactive<Record<string, string>>({})
const basketId = computed(() => String(route.params.id || ''))

function formatTime(value: string | null): string {
  if (!value) return '暂无行情时间'
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
  }).format(new Date(value))
}

async function load() {
  loading.value = true
  error.value = ''
  actionError.value = ''
  try {
    basket.value = await getBasket(basketId.value)
    for (const member of basket.value.members) weightDrafts[member.code] = member.weight ?? ''
  } catch (e) {
    error.value = toApiError(e, '加载篮子详情').friendly
    basket.value = null
  } finally {
    loading.value = false
  }
}

async function saveWeight(member: BasketMember) {
  const raw = weightDrafts[member.code].trim()
  const value = raw === '' ? null : raw
  const numeric = value === null ? null : Number(value)
  if (numeric !== null && (!Number.isFinite(numeric) || numeric < 0 || numeric > 100)) {
    actionError.value = '权重需要是 0 到 100 之间的数字'
    return
  }
  savingCode.value = member.code
  actionError.value = ''
  try {
    const updated = await updateBasketMemberWeight(basketId.value, member.code, value)
    member.weight = updated.weight
    weightDrafts[member.code] = updated.weight ?? ''
  } catch (e) {
    actionError.value = toApiError(e, '保存成分权重').friendly
  } finally {
    savingCode.value = ''
  }
}

watch(basketId, load, { immediate: true })
</script>

<template>
  <div class="mx-auto max-w-4xl px-4 py-4 pb-24 md:pb-8">
    <RouterLink
      to="/follow"
      class="mb-3 inline-flex min-h-11 items-center gap-1 rounded-lg text-sm text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
    >
      <ArrowLeft class="size-4" aria-hidden="true" />返回关注
    </RouterLink>

    <div v-if="loading" class="space-y-3" aria-label="正在加载篮子详情">
      <div class="h-36 animate-pulse rounded-xl bg-muted" />
      <div class="h-64 animate-pulse rounded-xl bg-muted" />
    </div>
    <ErrorState v-else-if="error" :message="error" @retry="load" />

    <div v-else-if="basket" class="space-y-4">
      <p v-if="actionError" role="alert" class="rounded-lg bg-destructive/10 px-3 py-2 text-sm text-destructive">
        {{ actionError }}
      </p>
      <section class="rounded-xl border bg-card p-4">
        <div class="flex items-start justify-between gap-4">
          <div class="min-w-0">
            <div class="flex items-center gap-2">
              <h1 class="truncate text-xl font-bold">{{ basket.name }}</h1>
              <span class="rounded bg-muted px-1.5 py-0.5 text-xs text-muted-foreground">
                {{ basket.kind === 'theme' ? '内置主题' : '自定义篮子' }}
              </span>
            </div>
            <p class="mt-1 text-sm text-muted-foreground">{{ basket.description || `${basket.total_stocks} 只成分股` }}</p>
            <p v-if="basket.reason" class="mt-2 text-sm">关注理由：{{ basket.reason }}</p>
          </div>
          <div class="shrink-0 text-right">
            <p class="font-mono text-xl font-bold" :style="{ color: changeColor(basket.change_pct) }">
              {{ fmtPct(basket.change_pct) }}
            </p>
            <p class="mt-1 flex items-center justify-end gap-1 text-xs text-muted-foreground">
              <Clock3 class="size-3" aria-hidden="true" />{{ formatTime(basket.as_of) }}
            </p>
          </div>
        </div>

        <div v-if="basket.leader || basket.laggard" class="mt-4 grid grid-cols-2 gap-3 border-t pt-3 text-sm">
          <div>
            <p class="text-xs text-muted-foreground">领涨</p>
            <RouterLink
              v-if="basket.leader"
              :to="`/detail/${basket.leader.code}`"
              class="mt-1 flex items-center justify-between rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
            >
              <span class="truncate">{{ basket.leader.name }}</span>
              <span class="font-mono" :style="{ color: changeColor(basket.leader.change_pct) }">{{ fmtPct(basket.leader.change_pct) }}</span>
            </RouterLink>
          </div>
          <div>
            <p class="text-xs text-muted-foreground">领跌</p>
            <RouterLink
              v-if="basket.laggard"
              :to="`/detail/${basket.laggard.code}`"
              class="mt-1 flex items-center justify-between rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
            >
              <span class="truncate">{{ basket.laggard.name }}</span>
              <span class="font-mono" :style="{ color: changeColor(basket.laggard.change_pct) }">{{ fmtPct(basket.laggard.change_pct) }}</span>
            </RouterLink>
          </div>
        </div>

        <p v-if="basket.anomaly" class="mt-3 flex items-center gap-2 rounded-lg bg-orange-500/10 px-3 py-2 text-sm text-orange-700 dark:text-orange-300">
          <AlertTriangle class="size-4 shrink-0" aria-hidden="true" />{{ basket.anomaly }}
        </p>
        <p v-else-if="basket.message" class="mt-3 text-xs text-muted-foreground">{{ basket.message }}</p>
      </section>

      <section class="rounded-xl border bg-card p-4">
        <div class="mb-3 flex items-center justify-between">
          <h2 class="text-sm font-semibold">成分股</h2>
          <span class="text-xs text-muted-foreground">{{ basket.members.length }}只 · 全部填写后按权重计算</span>
        </div>
        <p v-if="basket.members.length === 0" class="py-6 text-center text-sm text-muted-foreground">篮子还是空的</p>
        <ul v-else class="divide-y">
          <li v-for="member in basket.members" :key="member.code" class="flex items-center justify-between gap-3 py-2.5">
            <div class="min-w-0">
              <RouterLink
                :to="`/detail/${member.code}`"
                class="font-medium hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
              >{{ member.name || member.code }}</RouterLink>
              <span class="ml-1 text-xs text-muted-foreground">{{ member.code }}</span>
              <p v-if="member.note" class="mt-0.5 truncate text-xs text-muted-foreground">{{ member.note }}</p>
            </div>
            <div class="flex shrink-0 items-center gap-1">
              <label :for="`weight-${member.code}`" class="sr-only">{{ member.name }}权重</label>
              <input
                :id="`weight-${member.code}`"
                v-model="weightDrafts[member.code]"
                type="number"
                inputmode="decimal"
                min="0"
                max="100"
                step="0.01"
                placeholder="权重"
                class="h-9 w-20 rounded-md border bg-transparent px-2 text-right text-sm outline-none focus-visible:ring-2 focus-visible:ring-primary"
                @keyup.enter="saveWeight(member)"
              >
              <span class="text-xs text-muted-foreground">%</span>
              <button
                class="min-h-9 rounded-md px-2 text-xs hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary disabled:opacity-50"
                :disabled="savingCode === member.code || weightDrafts[member.code] === (member.weight ?? '')"
                @click="saveWeight(member)"
              >保存</button>
            </div>
          </li>
        </ul>
      </section>
    </div>
  </div>
</template>
